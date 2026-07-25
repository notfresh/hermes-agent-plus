import os
import fcntl
import atexit
import json
import sys
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