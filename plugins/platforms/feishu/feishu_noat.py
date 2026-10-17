"""Persistent per-user, per-chat Feishu no-at overrides."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import RLock

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)


class OverridePersistenceError(OSError):
    """Raised when an override changed in memory but could not be saved."""


class FeishuNoAtOverrideStore:
    """Store mentionless overrides scoped to one Feishu chat and user."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_hermes_home() / "state" / "noat_overrides.json")
        self._overrides: set[tuple[str, str]] = set()
        self._lock = RLock()
        self._load()

    def is_enabled(self, chat_id: str, user_id: str) -> bool:
        key = self._key(chat_id, user_id)
        if key is None:
            return False
        with self._lock:
            return key in self._overrides

    def set_enabled(self, chat_id: str, user_id: str, enabled: bool) -> bool:
        key = self._key(chat_id, user_id)
        if key is None:
            return False
        with self._lock:
            already_enabled = key in self._overrides
            if already_enabled == enabled:
                return False
            if enabled:
                self._overrides.add(key)
            else:
                self._overrides.remove(key)
            if not self._save():
                raise OverridePersistenceError(
                    f"failed to persist Feishu no-at overrides to {self._path}"
                )
            return True

    @staticmethod
    def _key(chat_id: str, user_id: str) -> tuple[str, str] | None:
        chat = str(chat_id or "").strip()
        user = str(user_id or "").strip()
        return (chat, user) if chat and user else None

    def _load(self) -> None:
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to load Feishu no-at overrides from %s: %s", self._path, exc)
            return

        pairs = payload.get("overrides", []) if isinstance(payload, dict) else []
        self._overrides = {
            (str(pair[0]), str(pair[1]))
            for pair in pairs
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] and pair[1]
        }

    def _save(self) -> bool:
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(
                    {"version": 1, "overrides": sorted(self._overrides)},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self._path)
            return True
        except OSError as exc:
            logger.warning("Failed to save Feishu no-at overrides to %s: %s", self._path, exc)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return False