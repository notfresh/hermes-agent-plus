"""Tests for the -xz / -zx / -z mutex group and dispatch."""
from __future__ import annotations

import pytest
from hermes_cli._parser import build_top_level_parser


class TestXZParser:
    def setup_method(self):
        self.parser, self._subparsers, self._chat = build_top_level_parser()

    def test_xz_sets_args_xz(self):
        args = self.parser.parse_args(["-xz", "hello world"])
        assert args.xz == "hello world"
        assert args.oneshot is None

    def test_zx_alias_sets_args_xz(self):
        args = self.parser.parse_args(["-zx", "hello world"])
        assert args.xz == "hello world"
        assert args.oneshot is None

    def test_oneshot_sets_args_oneshot(self):
        args = self.parser.parse_args(["-z", "hello world"])
        assert args.oneshot == "hello world"
        assert args.xz is None

    def test_z_and_xz_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["-z", "hello", "-xz", "hello"])

    def test_zx_and_z_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["-zx", "hello", "-z", "hello"])

    def test_z_and_xz_with_long_forms_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["--oneshot", "hello", "--xz", "hello"])

    def test_xz_accepts_model_flag(self):
        args = self.parser.parse_args(["-xz", "hello", "-m", "anthropic/claude-sonnet-4"])
        assert args.xz == "hello"
        assert args.model == "anthropic/claude-sonnet-4"

    def test_xz_accepts_provider_flag(self):
        args = self.parser.parse_args(["-xz", "hello", "--provider", "openrouter"])
        assert args.xz == "hello"
        assert args.provider == "openrouter"

    def test_xz_accepts_toolsets_flag(self):
        args = self.parser.parse_args(["-xz", "hello", "-t", "filesystem,search"])
        assert args.xz == "hello"
        assert args.toolsets == "filesystem,search"

    def test_xz_accepts_usage_file_flag(self):
        args = self.parser.parse_args(["-xz", "hello", "--usage-file", "/tmp/usage.json"])
        assert args.xz == "hello"
        assert args.usage_file == "/tmp/usage.json"


class TestRunOneshotWithSession:
    def test_no_session_returns_2_and_error_message(self, capsys, monkeypatch):
        # Mock SessionDB.search_sessions to return empty.
        class FakeDB:
            def search_sessions(self, source=None, limit=1):
                return []
            def close(self):
                pass

        monkeypatch.setattr("hermes_state.SessionDB", lambda: FakeDB())

        from hermes_cli.oneshot import run_oneshot_with_session
        result = run_oneshot_with_session("hello")
        assert result == 2
        captured = capsys.readouterr()
        assert "hermes -xz: no session found to resume" in captured.err

    def test_empty_conversation_history_returns_2(self, capsys, monkeypatch):
        # Mock search_sessions to return a session but get_messages_as_conversation empty.
        class FakeDB:
            def __init__(self):
                self.closed = False
            def search_sessions(self, source=None, limit=1):
                return [{"id": "test-session"}]
            def get_messages_as_conversation(self, session_id, repair_alternation=False):
                return []
            def close(self):
                self.closed = True

        monkeypatch.setattr("hermes_state.SessionDB", lambda: FakeDB())

        from hermes_cli.oneshot import run_oneshot_with_session
        result = run_oneshot_with_session("hello")
        assert result == 2
        captured = capsys.readouterr()
        assert "hermes -xz: no session found to resume" in captured.err