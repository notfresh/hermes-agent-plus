from types import SimpleNamespace

from plugins.platforms.feishu.adapter import FeishuAdapter
from plugins.platforms.feishu.feishu_noat import FeishuNoAtOverrideStore


def _adapter(tmp_path):
    adapter = object.__new__(FeishuAdapter)
    adapter._noat_overrides = FeishuNoAtOverrideStore(tmp_path / "noat.json")
    adapter._bot_open_id = "bot"
    adapter._bot_user_id = ""
    adapter._bot_name = "bot"
    adapter._allow_bots = "mentions"
    adapter._group_rules = {}
    adapter._require_mention = True
    adapter._default_group_policy = "open"
    adapter._group_policy = "open"
    adapter._allowed_group_users = set()
    adapter._admins = set()
    return adapter


def _message():
    return SimpleNamespace(chat_type="group", chat_id="chat-a", mentions=[])


def _sender(user_id="user-a", open_id=None):
    return SimpleNamespace(
        sender_type="user",
        sender_id=SimpleNamespace(user_id=user_id, open_id=open_id or user_id),
    )


def test_noat_override_only_bypasses_mention_gate(tmp_path):
    adapter = _adapter(tmp_path)
    message = _message()
    sender = _sender()

    assert adapter._admit(sender, message) == "group_policy_rejected"

    adapter._noat_overrides.set_enabled("chat-a", "user-a", True)

    assert adapter._admit(sender, message) is None


def test_noat_does_not_bypass_disabled_group_policy(tmp_path):
    adapter = _adapter(tmp_path)
    adapter._default_group_policy = "disabled"
    adapter._noat_overrides.set_enabled("chat-a", "user-a", True)

    assert adapter._admit(_sender(), _message()) == "group_policy_rejected"


def test_noat_uses_the_same_primary_id_as_session_source(tmp_path):
    adapter = _adapter(tmp_path)
    adapter._noat_overrides.set_enabled("chat-a", "tenant-user", True)

    assert adapter._admit(_sender(user_id="tenant-user", open_id="app-user"), _message()) is None