import os
import fcntl
import atexit
import json
import sys
import time
from pathlib import Path

_HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def _lock_path() -> Path:
    return Path(_HERMES_HOME) / "shell-context.lock"

def _pid_path() -> Path:
    return Path(_HERMES_HOME) / "shell-context.pid"

def _socket_path() -> Path:
    return Path(_HERMES_HOME) / "shell-context.sock"

_lock_handle = None

def acquire_shell_context_lock() -> bool:
    """Try to acquire exclusive flock. Returns True if acquired, False if already held."""
    global _lock_handle
    if _lock_handle is not None:
        return True
    _lock_path().parent.mkdir(parents=True, exist_ok=True)
    _lock_handle = open(_lock_path(), "a+", encoding="utf-8")
    try:
        fcntl.fcntl(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (BlockingIOError, OSError):
        _lock_handle.close()
        _lock_handle = None
        return False

def release_shell_context_lock() -> None:
    """Release the lock."""
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        fcntl.fcntl(_lock_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        _lock_handle.close()
    except OSError:
        pass
    _lock_handle = None

def write_shell_context_pid() -> None:
    """Write {pid, start_time} to pid file atomically. Raises FileExistsError if already exists."""
    _pid_path().parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps({"pid": os.getpid(), "start_time": os.path.getctime(_pid_path()) if _pid_path().exists() else 0})
    fd = os.open(_pid_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, record.encode("utf-8"))
    finally:
        os.close(fd)

def remove_shell_context_pid() -> None:
    """Remove the pid file."""
    try:
        _pid_path().unlink()
    except OSError:
        pass

def is_shell_context_lock_active() -> bool:
    """Check if the lock is held by another process."""
    if _lock_handle is not None:
        return True
    if not _lock_path().exists():
        return False
    try:
        handle = open(_lock_path(), "a+", encoding="utf-8")
        fcntl.fcntl(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.fcntl(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        return False
    except (BlockingIOError, OSError):
        return True

def get_shell_context_pid() -> int | None:
    """Read PID from pid file."""
    try:
        return json.loads(_pid_path().read_text())["pid"]
    except Exception:
        return None

import asyncio
from aiohttp import web

# Module-level cache set after prewarm completes
_prewarmed_plugins: list[dict] = []
_prewarmed_mcp: dict = {}
_prewarm_plugins_done: bool = False
_prewarm_mcp_done: bool = False

async def _handle_health(request):
    return web.json_response({
        "status": "ready" if (_prewarm_plugins_done and _prewarm_mcp_done) else "warming",
        "pid": os.getpid(),
        "prewarmed": {"plugins": _prewarm_plugins_done, "mcp": _prewarm_mcp_done},
    })

async def _handle_plugins(request):
    return web.json_response({"plugins": _prewarmed_plugins})

async def _handle_mcp(request):
    return web.json_response({"servers": _prewarmed_mcp})

async def run_uds_server():
    """Run the UDS HTTP server. Blocks forever (until SIGTERM)."""
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

    # Wait forever
    await asyncio.Event().wait()

def prewarm() -> None:
    """Run discover_plugins() and discover_mcp_tools(). Stores results in module globals."""
    global _prewarmed_plugins, _prewarmed_mcp, _prewarm_plugins_done, _prewarm_mcp_done

    # discover_plugins
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        from hermes_cli.plugins import _plugin_manager
        _prewarmed_plugins = [
            {"name": p.name, "version": getattr(p, "version", "unknown")}
            for p in _plugin_manager._plugins.values()
        ]
    except Exception:
        _prewarmed_plugins = []

    _prewarm_plugins_done = True

    # discover_mcp_tools
    try:
        from tools.mcp_tool import discover_mcp_tools
        discover_mcp_tools()
        from tools.mcp_tool import _mcp_tool_registry
        _prewarmed_mcp = {}
        for name, server in (_mcp_tool_registry._servers or {}).items():
            _prewarmed_mcp[name] = {
                "tools": getattr(server, "_tools", []),
                "error": getattr(server, "_error", None),
            }
    except Exception:
        _prewarmed_mcp = {}

    _prewarm_mcp_done = True

def check_daemon_health() -> dict | None:
    """Query the running daemon's /health endpoint over UDS. Returns None if daemon not running."""
    import aiohttp
    import asyncio
    try:
        if not _socket_path().exists():
            return None
        async def _query():
            async with aiohttp.UnixConnector(path=str(_socket_path())) as conn:
                async with aiohttp.ClientSession(connector=conn) as sess:
                    async with sess.get("http://localhost/health") as resp:
                        return await resp.json()
        return asyncio.run(_query())
    except Exception:
        return None

def ensure_shell_context_daemon() -> bool:
    """Check if daemon is running. If not, fork one and wait for it to become ready.

    Returns True if the daemon is warm and ready. Caller should skip inline discovery.
    Returns False if daemon is not available (fall back to inline discovery).
    """
    if not is_shell_context_lock_active():
        return False  # No daemon, fall back to inline

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

def _launch_daemon() -> None:
    """Fork a child process that becomes the daemon. Does not return."""
    pid = os.fork()
    if pid > 0:
        # Parent: pid > 0 is child's PID, just return
        return

    # Child process (pid == 0):
    # Re-acquire the lock in this process (flock is NOT inherited across fork)
    # Use "a+" mode like the parent did
    lock_file = open(str(_lock_path()), "a+", encoding="utf-8")
    try:
        fcntl.fcntl(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os._exit(1)  # Another daemon claimed the lock; exit gracefully

    write_shell_context_pid()
    atexit.register(remove_shell_context_pid)

    # Run prewarm in this child process
    prewarm()

    # Now serve UDS (blocking)
    asyncio.run(run_uds_server())
    os._exit(0)

def start_daemon() -> bool:
    """Start the daemon if not already running. Returns True if started or already running."""
    if not acquire_shell_context_lock():
        # Already held (another process has the lock)
        return True
    # We acquired the lock — fork the daemon
    _launch_daemon()
    return True