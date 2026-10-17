from pathlib import Path

import pytest

from plugins.platforms.feishu.feishu_noat import (
    FeishuNoAtOverrideStore,
    OverridePersistenceError,
)


def test_overrides_are_scoped_by_chat_and_user(tmp_path: Path) -> None:
    store = FeishuNoAtOverrideStore(tmp_path / "noat_overrides.json")

    store.set_enabled("chat-a", "user-a", True)

    assert store.is_enabled("chat-a", "user-a") is True
    assert store.is_enabled("chat-a", "user-b") is False
    assert store.is_enabled("chat-b", "user-a") is False


def test_override_state_survives_reload_and_can_be_disabled(tmp_path: Path) -> None:
    path = tmp_path / "noat_overrides.json"
    store = FeishuNoAtOverrideStore(path)

    store.set_enabled("chat-a", "user-a", True)
    reloaded = FeishuNoAtOverrideStore(path)
    assert reloaded.is_enabled("chat-a", "user-a") is True

    reloaded.set_enabled("chat-a", "user-a", False)
    assert FeishuNoAtOverrideStore(path).is_enabled("chat-a", "user-a") is False


def test_corrupt_state_file_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "noat_overrides.json"
    path.write_text("not json", encoding="utf-8")

    store = FeishuNoAtOverrideStore(path)

    assert store.is_enabled("chat-a", "user-a") is False


def test_save_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FeishuNoAtOverrideStore(tmp_path / "noat_overrides.json")
    monkeypatch.setattr(store, "_save", lambda: False)

    with pytest.raises(OverridePersistenceError):
        store.set_enabled("chat-a", "user-a", True)

    assert store.is_enabled("chat-a", "user-a") is True