# Spec: Shell Context Daemon (`shell-context`) — Pre-warm Daemon for `-z / -xz / -zx`

## Overview

> **Note:** In this document, `-z` refers to all oneshot modes: `-z`, `-xz`, and `-zx`. They share the same discovery and pre-warm logic.

A background daemon (`shell-context`) that pre-warms plugin and MCP discovery,
keeping results cached in-memory. When `hermes -z`, `hermes -xz`, or `hermes -zx`
runs, it checks for the
running daemon via a lock file and queries the pre-warmed cache over a Unix
Domain Socket, bypassing the expensive `discover_plugins()` and `discover_mcp_tools()`
calls entirely.

```
hermes -z "hello"    # first time: daemon not running → fork daemon → pre-warm → return
hermes -xz "hello"   # daemon already warm → query via UDS → instant response
hermes -zx "hello"   # daemon already warm → query via UDS → instant response
```

## Architecture

### Process Management (gateway pattern)

Daemon lifecycle managed via filesystem locks — same pattern as `gateway.lock` /
`gateway.pid` in `gateway/status.py`:

- `$HERMES_HOME/shell-context.lock` — held via `fcntl.flock`; released on exit
- `$HERMES_HOME/shell-context.pid` — JSON `{pid, start_time}`; verified before use

Acquire protocol on daemon start:
1. Try `fcntl.flock(LOCK_EX | LOCK_NB)` on `shell-context.lock`
2. If lock held by another process → daemon already running; exit 0
3. Write `shell-context.pid`
4. Register `atexit` cleanup

### IPC: Unix Domain Socket

Socket path: `$HERMES_HOME/shell-context.sock`

Minimal HTTP-over-UDS surface:

```
GET /health          → 200 {"status": "ready", "pid": int, "prewarmed": {"plugins": bool, "mcp": bool}}
GET /prewarmed_plugins → 200 {"plugins": [{"name": str, "version": str}]}
GET /prewarmed_mcp    → 200 {"servers": {name: {"tools": [...], "error": str|null}}}
```

`hermes -z` uses `http://localhost/` with `UDSConnectionContext` from `aiohttp`
to connect and query — same pattern as the gateway's API server but over UDS.

### What is pre-warmed

1. **`discover_plugins()`** — full plugin scan (`PluginManager.discover_and_load`);
   result is the in-memory `_plugins` dict already held by the singleton
2. **`discover_mcp_tools()`** — synchronous MCP server probes; cached per-server
   so the first probe result is reused for all subsequent invocations

Config (`load_config()`) and the OpenRouter model catalog are **NOT** pre-warmed:
they are already cached after the first `-z` run via `_LOAD_CONFIG_CACHE` and
`_openrouter_catalog_cache`. Pre-warming them in the daemon would require the
daemon to share the same module-level caches as the `-z` process, which requires
either multiprocessing-safe shared memory or in-process forking — both more
complex than the current scope.

### Daemon startup (fork-on-demand)

`hermes -z` at startup:

1. Check if `shell-context.lock` is held (non-blocking flock)
2. If held → daemon running; connect to `shell-context.sock` and query `/health`
3. If not held → fork a child process that becomes the daemon:
   - Child: releases the inherited flock (per `fork()` semantics the lock is
     NOT held in the child), re-acquires it, starts UDS server, runs
     `discover_plugins()` + `discover_mcp_tools()`, then enters the UDS serve loop
   - Parent: connects to socket, waits for `/health` to return `ready`, then
     proceeds with the actual `-z` run

This means the parent process (the user's `-z` invocation) only blocks for
the daemon's startup **once** — on subsequent calls the daemon is already up.

### Graceful shutdown

Daemon has no主动 shutdown — it runs until killed or the system reboots.
On crash, the `flock` is automatically released by the OS.

A `shell-context stop` command can be added later that sends SIGTERM to the PID
read from `shell-context.pid`.

## Files

| File | Purpose |
|---|---|
| `hermes_cli/agent_daemon.py` | New: UDS server, pre-warm logic, fork parent-side IPC |
| `hermes_cli/main.py` | Modify: `-z` entry point checks/launches daemon |
| `hermes_cli/__init__.py` | Add `agent` subcommand stub (future: `shell-context start/stop`) |
| `gateway/status.py` | Reference: lock/pid pattern to copy |

## Interaction with existing code

- `discover_plugins()` — already idempotent (`_discovered` flag); called once per daemon lifetime
- `discover_mcp_tools()` — already cached per `mcp_startup.py`; daemon calls it once
- `hermes -z` / `-xz` / `-zx` — only change: check daemon before calling `_prepare_agent_startup()`;
  if daemon is warm, skip `discover_plugins()` and `discover_mcp_tools()` from the inline path
- Gateway — unchanged; independent of this daemon

## Open questions (resolved)

**Q: What if the daemon is pre-warming when -z is called?**
A: Parent `-z` process connects to the socket and waits for `/health` to return
`ready`. If the socket is not yet listening (daemon still running discovery),
the connection is refused — parent retries with exponential backoff (max 3 tries,
~2s total), then falls back to inline discovery.

**Q: What is shared between daemon and -z process?**
A: Nothing. They are completely separate processes. Cached data lives only in
the daemon's memory. The socket API is the only communication channel.

**Q: Does the daemon need to re-run discovery on restart?**
A: Yes — on daemon crash/restart, all in-memory caches are lost. The first `-z`
after a daemon restart pays the full discovery cost again. This matches the
existing `-z` behavior.

**Q: Does this affect `-z` without daemon?**
A: No. If the daemon is not running or the UDS query fails, `-z` falls back
to the existing inline discovery path exactly as it does today.
