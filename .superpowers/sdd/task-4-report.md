# Task 4 Report: Wire shell-context daemon into oneshot dispatch

## Status: DONE

## Summary
Updated `/root/projects/hermes-agent-plus/hermes_cli/main.py` to integrate the shell-context daemon with `-z` / `-xz` / `-zx` startup paths. Warm daemon state now suppresses redundant plugin and MCP discovery, while oneshot paths start the daemon on demand and retain inline fallback behavior when daemon startup fails.

## Changes Made

### `_prepare_agent_startup`
- Calls `ensure_shell_context_daemon()` at startup and records whether the daemon is warm.
- Skips Python plugin discovery when the daemon is warm.
- Skips inline MCP tool discovery when the daemon is warm.
- Existing exception handling and shell-hook registration remain intact.

### Oneshot dispatch
- Added guarded `start_daemon()` calls before `run_oneshot_with_session` for `--xz` / `-xz` / `-zx`.
- Added guarded `start_daemon()` calls before `run_oneshot` for `--oneshot` / `-z`.
- Applied the same startup behavior in the Termux fast CLI path.
- Daemon failures are swallowed so existing inline execution remains available.

## Verification

Ran:

```text
python3 -c "import hermes_cli.main; print('OK')"
```

Result:

```text
OK
```

## Commit

Changes were committed with:

```text
feat(main): wire shell-context daemon into -z/-xz/-zx
```
