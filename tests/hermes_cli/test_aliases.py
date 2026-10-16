"""Behavior contracts for shared quick-command alias registration and resolution."""

from hermes_cli.aliases import manage_aliases, resolve_alias


def test_resolve_alias_preserves_user_arguments():
    result = resolve_alias("/ss recent", {"ss": {"type": "alias", "target": "/sessions"}})

    assert result is not None
    assert result.command == "/sessions recent"
    assert result.alias_used == "ss"
    assert result.error is None


def test_resolve_alias_chain_combines_target_and_user_arguments():
    result = resolve_alias(
        "/old user-arg",
        {
            "old": {"type": "alias", "target": "/middle fixed-one"},
            "middle": {"type": "alias", "target": "sessions fixed-two"},
        },
    )

    assert result is not None
    assert result.command == "/sessions fixed-two fixed-one user-arg"


def test_resolve_alias_reports_cycle_and_empty_target():
    cycle = resolve_alias("/a", {"a": {"type": "alias", "target": "/b"}, "b": {"type": "alias", "target": "/a"}})
    empty = resolve_alias("/empty", {"empty": {"type": "alias", "target": " "}})

    assert cycle is not None and cycle.error and "cycle" in cycle.error.lower()
    assert empty is not None and empty.error and "empty" in empty.error.lower()


def test_resolve_alias_leaves_unmatched_and_exec_commands_alone():
    quick_commands = {"shell": {"type": "exec", "command": "echo ok"}, "elsewhere": {"type": "alias", "target": "/sessions"}}

    assert resolve_alias("/shell", quick_commands) is None
    assert resolve_alias("/help", quick_commands) is None


def test_manage_aliases_uses_injected_writer_and_updates_config_only_on_success():
    config = {"quick_commands": {}}
    writes = []

    def save_value(key_path, value):
        writes.append((key_path, value))
        return True

    result = manage_aliases('ss "/sessions"', config, save_value)

    assert result.action == "set"
    assert result.name == "ss"
    assert config["quick_commands"]["ss"] == {"type": "alias", "target": "/sessions"}
    assert writes == [("quick_commands.ss", {"type": "alias", "target": "/sessions"})]


def test_manage_aliases_does_not_mutate_config_when_save_fails():
    config = {"quick_commands": {}}

    result = manage_aliases("ss /sessions", config, lambda _key, _value: False)

    assert result.action == "error"
    assert config["quick_commands"] == {}