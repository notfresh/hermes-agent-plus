# Shell Context Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a background daemon (`shell-context`) that pre-warms `discover_plugins()` and `discover_mcp_tools()`, keeping results cached. On `-z / -xz / -zx`, if the daemon is running, skip inline discovery and use the pre-warmed cache instead.

**Architecture:** A new module `hermes_cli/shell_context.py` owns: (a) lock/pid file management (copy of gateway pattern), (b) a UDS HTTP server with `/health`, `/prewarmed_plugins`, `/prewarmed_mcp` endpoints, (c) the fork-on-demand logic. `main.py` calls a new `_check_shell_context_daemon()` before `_prepare_agent_startup()` in the oneshot path and uses its result to skip discovery.

**Tech Stack:** Python `fcntl.flock`, `asyncio` + `aiohttp` UDS server, `os.fork()`, `atexit`

---

## Global Constraints

- Lock path: `$HERMES_HOME/shell-context.lock`; PID path: `$HERMES_HOME/shell-context.pid`; Socket path: `$HERMES_HOME/shell-context.sock`
- UDS endpoints: `GET /health` → `{"status": "ready", "pid": int, "prewarmed": {"plugins": bool, "mcp": bool}}`; `GET /prewarmed_plugins` → `{"plugins": [{"name": str, "version": str}]}`; `GET /prewarmed_mcp` → `{"servers": {name: {"tools": [...], "error": str|null}}}`
- Pre-warm: `discover_plugins()` + `discover_mcp_tools()` — same functions called inline by `_prepare_agent_startup`
- If daemon is not running or UDS query fails, fall back to inline discovery (existing behavior unchanged)
- Parent `-z` process waits up to ~2s for daemon `/health` to become `"ready"`, then falls back to inline if timeout

---

## Task 1: Lock/PID/Socket Infrastructure in `hermes_cli/shell_context.py`

**Files:**
- Create: `hermes_cli/shell_context.py`

**Interfaces:**
- Produces: `acquire_shell_context_lock()`, `release_shell_context_lock()`, `write_shell_context_pid()`, `remove_shell_context_pid()`, `is_shell_context_lock_active()`, `get_shell_context_pid()`, `_lock_path()`, `_pid_path()`, `_socket_path()` — all module-level functions

Copy the gateway pattern from `gateway/status.py`. Key functions:

```python
import os
import fcntl
import atexit
import json
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def _lock_path() -> Path:
    return Path(HERMES_HOME) / "shell-context.lock"

def _pid_path() -> Path:
    return Path(HERMES_HOME) / "shell-context.pid"

def _socket_path() -> Path:
    return Path(HERMES_HOME) / "shell-context.sock"

def acquire_shell_context_lock() -> bool:
    """Try to acquire exclusive lock. Returns True if acquired, False if already held."""
    lock_file = open(_lock_path(), "w")
    try:
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False

def release_shell_context_lock(lock_file=None) -> None:
    """Release the lock."""
    if lock_file is None:
        try:
            lock_file = open(_lock_path(), "w")
            fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        return
    try:
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass

def write_shell_context_pid() -> None:
    """Write {pid, start_time} to pid file."""
    pid_file = _pid_path()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(json.dumps({
        "pid": os.getpid(),
        "start_time": os.path.getctime(pid_file) if pid_file.exists() else 0,
    }))

def remove_shell_context_pid() -> None:
    """Remove the pid file."""
    try:
        _pid_path().unlink()
    except Exception:
        pass

def is_shell_context_lock_active() -> bool:
    """Check if the lock is currently held by another process."""
    try:
        lock_file = open(_lock_path(), "w")
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True

def get_shell_context_pid() -> int | None:
    """Read PID from pid file."""
    try:
        return json.loads(_pid_path().read_text())["pid"]
    except Exception:
        return None
```

**Steps:**

- [ ] **Step 1: Create `hermes_cli/shell_context.py`** with all functions above
- [ ] **Step 2: Run import check**

```bash
python -c "from hermes_cli.shell_context import acquire_shell_context_lock, is_shell_context_lock_active, _lock_path, _socket_path; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add hermes_cli/shell_context.py
git commit -m "feat(shell-context): add lock/pid/socket infrastructure"
```

---

## Task 2: UDS Server and Pre-warm Logic

**Files:**
- Modify: `hermes_cli/shell_context.py` (append new code)

**Interfaces:**
- Consumes: `acquire_shell_context_lock()`, `release_shell_context_lock()`, `write_shell_context_pid()`, `remove_shell_context_pid()`, `_socket_path()`
- Produces: `run_uds_server()` (blocking async function), `prewarm()` (sync function), `check_daemon_health() -> dict | None`

```python
import asyncio
from aiohttp import web

# Module-level cache set after prewarm completes
_prewarmed_plugins: list[dict] = []
_prewarmed_mcp: dict = {}
_prewarm_done: bool = False

async def _handle_health(request):
    return web.json_response({
        "status": "ready" if _prewarm_done else "warming",
        "pid": os.getpid(),
        "prewarmed": {"plugins": _prewarm_done, "mcp": _prewarm_done},
    })

async def _handle_plugins(request):
    return web.json_response({"plugins": _prewarmed_plugins})

async def _handle_mcp(request):
    return web.json_response({"servers": _prewarmed_mcp})

async def run_uds_server(lock_file):
    """Run the UDS HTTP server. Blocks until SIGTERM."""
    app = web.Application()
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/prewarmed_plugins", _handle_plugins)
    app.router.add_get("/prewarmed_mcp", _handle_mcp)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.UnixSite(runner, str(_socket_path()))
    await site.start()

    # Remove socket file on exit
    atexit.register(lambda: _socket_path().unlink(missing_ok=True))

    # Wait forever (SIGTERM from daemon stop)
    await asyncio.Event().wait()

def prewarm() -> None:
    """Run discover_plugins() and discover_mcp_tools(). Stores results in module globals."""
    global _prewarmed_plugins, _prewarmed_mcp, _prewarm_done

    # discover_plugins
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        from hermes_cli.plugins import _plugin_manager
        _prewarmed_plugins = [
            {"name": p.name, "version": getattr(p, "version", "unknown")}
            for p in _plugin_manager._plugins.values()
        ]
    except Exception as e:
        _prewarmed_plugins = []

    # discover_mcp_tools
    try:
        from tools.mcp_tool import discover_mcp_tools
        discover_mcp_tools()
        # Import the cached MCP tools result
        from tools.mcp_tool import _mcp_tool_registry
        _prewarmed_mcp = {}
        for name, server in (_mcp_tool_registry._servers or {}).items():
            _prewarmed_mcp[name] = {
                "tools": getattr(server, "_tools", []),
                "error": getattr(server, "_error", None),
            }
    except Exception as e:
        _prewarmed_mcp = {}

    _prewarm_done = True

def check_daemon_health() -> dict | None:
    """Query the running daemon's /health endpoint over UDS. Returns None if daemon not running."""
    import urllib.request
    try:
        sock_path = _socket_path()
        if not sock_path.exists():
            return None
        # Use http://localhost/ with UDS — aiohttp.UnixConnector
        import aiohttp
        import asyncio
        async def _query():
            async with aiohttp.UnixConnector(path=str(sock_path)) as conn:
                async with aiohttp.ClientSession(connector=conn) as sess:
                    async with sess.get("http://localhost/health") as resp:
                        return await resp.json()
        return asyncio.run(_query())
    except Exception:
        return None
```

**Steps:**

- [ ] **Step 1: Append UDS server + prewarm functions to `hermes_cli/shell_context.py`**
- [ ] **Step 2: Run import check**

```bash
python -c "from hermes_cli.shell_context import prewarm, run_uds_server, check_daemon_health; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add hermes_cli/shell_context.py
git commit -m "feat(shell-context): add UDS server and prewarm logic"
```

---

## Task 3: Fork-on-Demand Logic

**Files:**
- Modify: `hermes_cli/shell_context.py` (append new code)

**Interfaces:**
- Produces: `ensure_shell_context_daemon() -> bool` — returns True if daemon is running and warm, False to fall back to inline

```python
import os
import time
import subprocess

def ensure_shell_context_daemon() -> bool:
    """Check if daemon is running. If not, fork one and wait for it to become ready.

    Returns True if the daemon is warm and ready. Caller should skip inline discovery.
    Returns False if daemon is not available (fall back to inline discovery).
    """
    # Check if lock is already held (daemon running)
    if not is_shell_context_lock_active():
        return False  # No daemon, fall back to inline

    # Daemon is running — check if warm
    health = check_daemon_health()
    if health is None:
        return False

    if health.get("status") == "ready":
        return True

    # Daemon is warming up — poll for up to 2s
    for _ in range(10):  # 10 retries × 200ms = 2s
        time.sleep(0.2)
        health = check_daemon_health()
        if health and health.get("status") == "ready":
            return True

    return False

def _launch_daemon() -> int:
    """Fork a child process that becomes the daemon. Parent returns child PID."""
    pid = os.fork()
    if pid > 0:
        # Parent
        return pid

    # Child: re-acquire lock (fork does NOT inherit flock state across exec)
    # In child: the flock is released, so we re-acquire
    lock_file = open(str(_lock_path()), "w")
    try:
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os._exit(1)  # Another daemon started; exit gracefully

    write_shell_context_pid()
    atexit.register(remove_shell_context_pid)

    # Run prewarm synchronously in this child process
    prewarm()

    # Now serve UDS (blocking)
    asyncio.run(run_uds_server(lock_file))
    os._exit(0)
```

Also add a `start_daemon()` function that calls `acquire_shell_context_lock()` first — if already held, do nothing; if acquired, fork and launch.

```python
def start_daemon() -> bool:
    """Start the daemon if not already running. Returns True if started or already running."""
    if not acquire_shell_context_lock():
        # Already running
        return True
    # We hold the lock now — fork the daemon
    _launch_daemon()
    return True
```

**Steps:**

- [ ] **Step 1: Append fork/demand logic to `hermes_cli/shell_context.py`**
- [ ] **Step 2: Run import check**

```bash
python -c "from hermes_cli.shell_context import ensure_shell_context_daemon, start_daemon; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add hermes_cli/shell_context.py
git commit -m "feat(shell-context): add fork-on-demand daemon launch"
```

---

## Task 4: Wire into `-z` / `-xz` / `-zx` in `main.py`

**Files:**
- Modify: `hermes_cli/main.py`

**Interfaces:**
- Consumes: `ensure_shell_context_daemon()`, `shell_context.py` functions
- Produces: Modified `_prepare_agent_startup()` skips `discover_plugins()` and `discover_mcp_tools()` when daemon is warm

**Where to modify:** In `_prepare_agent_startup()` at line 12835:

1. At the START of `_prepare_agent_startup()` (before the existing code), call `ensure_shell_context_daemon()`. If it returns True, set a module-level flag `_shell_context_warm = True`.

2. In the `discover_plugins()` block (line 12857-12864): wrap with `if not getattr(args, "_shell_context_warm", False):`

3. In the `discover_mcp_tools()` block (line 12890-12900): wrap with same guard

The cleanest way to do this is to add a helper at the top of the function:

```python
def _prepare_agent_startup(args) -> None:
    # Shell context daemon: if warm, skip plugin/MCP discovery
    _shell_context_warm = False
    try:
        from hermes_cli.shell_context import ensure_shell_context_daemon
        if ensure_shell_context_daemon():
            _shell_context_warm = True
    except Exception:
        pass

    if getattr(args, "yolo", False):
        ...
```

Then wrap the two discovery calls:

```python
    if not _shell_context_warm:
        try:
            from hermes_cli.plugins import discover_plugins
            discover_plugins()
        except Exception:
            logger.warning("plugin discovery failed at CLI startup", exc_info=True)

    # ... the inline MCP block ...
    if not _shell_context_warm and _run_inline_mcp_discovery:
        try:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
        except Exception:
            logger.debug("MCP tool discovery failed at CLI startup", exc_info=True)
```

**Note:** The same `_prepare_agent_startup` is called for interactive chat too — but the oneshot `-z` path calls it via `_prepare_agent_startup(args)` in `main()` at line 15128 (before the oneshot dispatch). The daemon check will only meaningfully skip work when `args.oneshot` or `args.xz` is set.

**Also:** Add the daemon launch to the oneshot dispatch block in `main()`. In `run_oneshot_with_session()` (in `oneshot.py`), before calling `_prepare_agent_startup(args)` in the parent process, ensure the daemon is started. Actually `_prepare_agent_startup` is called in the parent process before the oneshot dispatch. So the check above handles it. But we also need to start the daemon on first use — add this in the oneshot branch in `main.py`:

```python
if getattr(args, "xz", None):
    # Start daemon if not running (fork-on-demand)
    try:
        from hermes_cli.shell_context import start_daemon
        start_daemon()
    except Exception:
        pass  # Fall back to inline if this fails
    from hermes_cli.oneshot import run_oneshot_with_session
    sys.exit(run_oneshot_with_session(...))
```

Do the same for the `args.oneshot` branch.

**Also update Termux fast path** at `_try_termux_fast_cli_launch()` — add the `start_daemon()` call before the oneshot dispatch there too.

**Steps:**

- [ ] **Step 1: Read current `_prepare_agent_startup` to confirm exact lines**
- [ ] **Step 2: Add daemon check at top of `_prepare_agent_startup`**
- [ ] **Step 3: Wrap `discover_plugins()` and `discover_mcp_tools()` calls with `_shell_context_warm` guard**
- [ ] **Step 4: Add `start_daemon()` call to both oneshot dispatch branches in `main()`**
- [ ] **Step 5: Add to Termux fast path**
- [ ] **Step 6: Run import check**

```bash
python -c "import hermes_cli.main; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add hermes_cli/main.py
git commit -m "feat(main): wire shell-context daemon into -z/-xz/-zx"
```

---

## Task 5: Tests

**Files:**
- Create: `tests/hermes_cli/test_shell_context.py`

```python
"""Tests for shell-context daemon."""
from __future__ import annotations
import pytest
from hermes_cli.shell_context import (
    acquire_shell_context_lock,
    release_shell_context_lock,
    is_shell_context_lock_active,
    _lock_path,
    _pid_path,
    _socket_path,
    check_daemon_health,
    ensure_shell_context_daemon,
    start_daemon,
)

class TestLockManagement:
    def test_lock_not_held_initially(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from hermes_cli import shell_context
        # Re-import to pick up env
        assert not is_shell_context_lock_active()

    def test_acquire_and_release(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from hermes_cli import shell_context
        assert acquire_shell_context_lock()
        assert is_shell_context_lock_active()
        release_shell_context_lock()
        assert not is_shell_context_lock_active()

    def test_double_acquire_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from hermes_cli import shell_context
        assert acquire_shell_context_lock()
        assert not acquire_shell_context_lock()  # Should fail
        release_shell_context_lock()

class TestSocketPaths:
    def test_paths_under_hermes_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from hermes_cli import shell_context
        assert str(_lock_path()).startswith(str(tmp_path))
        assert str(_pid_path()).startswith(str(tmp_path))
        assert str(_socket_path()).startswith(str(tmp_path))
```

Also add integration test that mocks `prewarm()` and verifies `ensure_shell_context_daemon` returns correct value.

**Steps:**

- [ ] **Step 1: Create `tests/hermes_cli/test_shell_context.py`**
- [ ] **Step 2: Run tests**

```bash
pytest tests/hermes_cli/test_shell_context.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/hermes_cli/test_shell_context.py
git commit -m "test(shell-context): add tests for lock/pid/socket infrastructure"
```

---

## Spec Coverage

| Spec requirement | Task |
|---|---|
| Lock/pid/socket infrastructure | Task 1 |
| UDS server with /health, /prewarmed_plugins, /prewarmed_mcp | Task 2 |
| Pre-warm discover_plugins + discover_mcp_tools | Task 2 |
| Fork-on-demand daemon launch | Task 3 |
| Parent polls /health and falls back to inline | Task 3, Task 4 |
| -z/-xz/-zx skip discovery when daemon is warm | Task 4 |
| Termux fast path support | Task 4 |
| Tests | Task 5 |
