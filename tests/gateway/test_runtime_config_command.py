from types import SimpleNamespace

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource
from hermes_cli.commands import GATEWAY_KNOWN_COMMANDS, resolve_command


def _event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.FEISHU,
            user_id="user-a",
            chat_id="chat-a",
            user_name="tester",
            chat_type="group",
        ),
    )


def test_config_is_registered_as_a_gateway_command() -> None:
    assert resolve_command("config").name == "config"
    assert "config" in GATEWAY_KNOWN_COMMANDS


@pytest.mark.asyncio
async def test_config_command_delegates_to_source_adapter() -> None:
    calls = []

    class Adapter:
        def handle_runtime_config(self, source, args):
            calls.append((source, args))
            return "handled"

    runner = object.__new__(gateway_run.GatewayRunner)
    adapter = Adapter()
    runner._delivery_adapter_for = lambda source: adapter

    result = await runner._handle_config_command(_event("/config set feishu.noat on"))

    assert result == "handled"
    assert calls == [(_event("/config set feishu.noat on").source, "set feishu.noat on")]


@pytest.mark.asyncio
async def test_config_command_reports_unsupported_adapter() -> None:
    runner = object.__new__(gateway_run.GatewayRunner)
    runner._delivery_adapter_for = lambda source: SimpleNamespace()

    result = await runner._handle_config_command(_event("/config list"))

    assert "not supported" in result.lower()