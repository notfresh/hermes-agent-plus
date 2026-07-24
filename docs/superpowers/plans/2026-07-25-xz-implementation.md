# `-xz` / `-zx` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hermes -xz` / `hermes -zx` — a oneshot mode that loads the most recent CLI/TUI session history before sending the prompt. Identical output contract to `hermes -z` (silent, stdout-only response) but with full conversational context.

**Architecture:** Three files change: `_parser.py` adds `-xz`/`-zx` flags in a new mutually-exclusive group with `-z`; `main.py` dispatches to a new `run_oneshot_with_session()` function when `args.xz` is set; `oneshot.py` adds the new function and a `_run_agent_with_history()` helper that passes `conversation_history` to `AIAgent`.

**Tech Stack:** Python argparse, hermes_state.SessionDB, run_agent.AIAgent

---

## Global Constraints

- Exit code 0: normal completion; 1: exception/no response; 2: user error (no session, bad args)
- Error messages to stderr, prefixed `hermes -xz:`
- `-z` and `-xz`/`-zx` are mutually exclusive (argparse `add_mutually_exclusive_group`)
- Both `-xz` and `-zx` map to `args.xz` (same field, same behavior)
- `source=None` in `SessionDB.search_sessions()` returns ALL sessions ordered by `last_active DESC`
- `SessionDB.get_messages_as_conversation(session_id, repair_alternation=True)` returns `List[Dict[str, Any]]`
- New turn is persisted via existing `_flush_messages_to_session_db` path (no new persistence logic needed)

---

## Task 1: Add `-xz` / `-zx` flags to the parser

**Files:**
- Modify: `hermes_cli/_parser.py:99-114` (the existing `-z` block)

**Interfaces:**
- Produces: `args.xz` is set when user passes `-xz PROMPT`, `-zx PROMPT`, `--xz PROMPT`, or `--zx PROMPT`

**Notes:**
- The new group must be inserted before `--usage-file` so the group is defined before its members are added.
- `metavar="PROMPT"` and `default=None` match the existing `-z` pattern.

- [ ] **Step 1: Read the current `-z` definition in `_parser.py` to see exact line range**

```bash
sed -n '99,114p' hermes_cli/_parser.py
```

- [ ] **Step 2: Replace the standalone `-z` add_argument with a mutually-exclusive group containing both `-z` and `-xz`/`-zx`**

```python
    # -z / --oneshot and -xz / --xz / -zx are mutually exclusive.
    # Both -xz and -zx map to args.xz (identical behaviour).
    oneshot_group = parser.add_mutually_exclusive_group()
    oneshot_group.add_argument(
        "-z",
        "--oneshot",
        dest="oneshot",
        metavar="PROMPT",
        default=None,
        help=(
            "One-shot mode: send a single prompt and print ONLY the final "
            "response text to stdout. No banner, no spinner, no tool "
            "previews, no session_id line. Tools, memory, rules, and "
            "AGENTS.md in the CWD are loaded as normal; approvals are "
            "auto-bypassed. Intended for scripts / pipes."
        ),
    )
    oneshot_group.add_argument(
        "-xz",
        "--xz",
        dest="xz",
        metavar="PROMPT",
        default=None,
        help=(
            "One-shot mode with session history: like -z, but loads the most "
            "recent CLI/TUI session's full conversation before sending the prompt. "
            "-xz and -zx are synonyms. Exits after printing the final response."
        ),
    )
    oneshot_group.add_argument(
        "-zx",
        "--zx",
        dest="xz",
        metavar="PROMPT",
        default=None,
        # No help text — users discover it via -xz's description.
        help=argparse.SUPPRESS,
    )
```

- [ ] **Step 3: Verify the edit looks correct**

```bash
sed -n '99,145p' hermes_cli/_parser.py
```

- [ ] **Step 4: Run existing parser tests to confirm no regression**

```bash
pytest tests/hermes_cli/test_argparse_flag_propagation.py -v -x
```

- [ ] **Step 5: Commit**

```bash
git add hermes_cli/_parser.py
git commit -m "feat(parser): add -xz/-zx flags in mutex group with -z"
```

---

## Task 2: Add `run_oneshot_with_session` and `_run_agent_with_history` to `oneshot.py`

**Files:**
- Modify: `hermes_cli/oneshot.py` (append two new functions at the end of the file, after line 451)

**Interfaces:**
- Consumes: `prompt`, `model`, `provider`, `toolsets`, `usage_file` from caller; `SessionDB` from `hermes_state`
- Produces: `run_oneshot_with_session(prompt, model, provider, toolsets, usage_file) -> int`

**Notes:**
- Session resolution uses `_resolve_last_session(source=None)` so CLI and TUI sessions are both considered.
- `get_messages_as_conversation(session_id, repair_alternation=True)` gives the history list.
- A fresh `SessionDB()` (not `_create_session_db_for_oneshot()`) is passed to `AIAgent` so the new turn is persisted.
- The `AIAgent` call is identical to `_run_agent` except it also passes `session_id=session_id`, `session_db=session_db`, and `conversation_history=conversation_history`.

- [ ] **Step 1: Read the end of `oneshot.py` to confirm where to append**

```bash
tail -20 hermes_cli/oneshot.py
```

- [ ] **Step 2: Add `run_oneshot_with_session` and `_run_agent_with_history` after line 451**

```python
def run_oneshot_with_session(
    prompt: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    toolsets: object = None,
    usage_file: Optional[str] = None,
) -> int:
    """Execute a single prompt with the full history of the most recent session.

    Identical to ``run_oneshot`` in output contract (silent, stdout-only final
    response, exit codes 0/1/2) but prepends the most recent CLI/TUI session's
    message history to the prompt so the agent has conversational context.

    Args:
        prompt: The user message to send.
        model: Optional model override.
        provider: Optional provider override.
        toolsets: Optional comma-separated string or iterable of toolsets.
        usage_file: Optional path for a JSON usage report.

    Returns the exit code.  Caller should sys.exit() with the return.
    """
    # Silence stdlib loggers for the entire call tree.
    logging.disable(logging.CRITICAL)

    # Validate --provider requires --model (same contract as run_oneshot).
    env_model_early = os.getenv("HERMES_INFERENCE_MODEL", "").strip()
    if provider and not ((model or "").strip() or env_model_early):
        sys.stderr.write(
            "hermes -xz: --provider requires --model (or HERMES_INFERENCE_MODEL). "
            "Pass both explicitly, or neither to use your configured defaults.\n"
        )
        return 2

    explicit_toolsets, toolsets_error = _validate_explicit_toolsets(toolsets)
    if toolsets_error:
        sys.stderr.write(toolsets_error)
        return 2
    use_config_toolsets = _normalize_toolsets(toolsets) is None

    # Resolve the most recent session (CLI or TUI).
    session_id: Optional[str] = None
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        sessions = db.search_sessions(source=None, limit=1)
        if sessions:
            session_id = sessions[0]["id"]
        db.close()
    except Exception:
        pass

    if not session_id:
        sys.stderr.write("hermes -xz: no session found to resume\n")
        return 2

    # Load the conversation history for that session.
    conversation_history: list = []
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        conversation_history = db.get_messages_as_conversation(
            session_id, repair_alternation=True
        )
        db.close()
    except Exception:
        pass

    if not conversation_history:
        sys.stderr.write("hermes -xz: no session found to resume\n")
        return 2

    # Set YOLO mode and auto-accept hooks.
    os.environ["HERMES_YOLO_MODE"] = "1"
    os.environ["HERMES_ACCEPT_HOOKS"] = "1"
    declare_stateless_channel()

    # Redirect stderr and stdout to devnull for the call tree.
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    devnull = open(os.devnull, "w", encoding="utf-8")

    response: Optional[str] = None
    result: dict = {}
    failure: BaseException | None = None
    try:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            try:
                response, result = _run_agent_with_history(
                    prompt,
                    session_id=session_id,
                    conversation_history=conversation_history,
                    model=model,
                    provider=provider,
                    toolsets=explicit_toolsets,
                    use_config_toolsets=use_config_toolsets,
                )
            except BaseException as exc:
                failure = exc
    finally:
        try:
            devnull.close()
        except Exception:
            pass

    if failure is not None:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            _write_usage_file(usage_file, result, failure=repr(failure))
            raise failure
        _write_usage_file(usage_file, result, failure=str(failure))
        real_stderr.write(f"hermes -xz: agent failed: {failure}\n")
        real_stderr.flush()
        return 1

    _write_usage_file(usage_file, result)

    if response:
        real_stdout.write(response)
        if not response.endswith("\n"):
            real_stdout.write("\n")
        real_stdout.flush()

    if (result.get("failed") or result.get("partial")) and not (response or "").strip():
        return 2

    if not (response or "").strip():
        real_stderr.write("hermes -xz: no final response was produced; treating the run as failed.\n")
        real_stderr.flush()
        return 1

    return 0


def _run_agent_with_history(
    prompt: str,
    session_id: str,
    conversation_history: list[dict],
    model: Optional[str] = None,
    provider: Optional[str] = None,
    toolsets: object = None,
    use_config_toolsets: bool = True,
) -> tuple[str, dict]:
    """Build an AIAgent with session history and run a single conversation turn.

    This is the counterpart to ``_run_agent`` used by ``run_oneshot``; the difference
    is that ``conversation_history`` is pre-loaded from the session store and
    ``session_id`` / ``session_db`` are passed so the turn is persisted back.
    """
    from hermes_cli.config import load_config
    from hermes_cli.models import detect_provider_for_model
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from hermes_cli.tools_config import _get_platform_tools
    from hermes_state import SessionDB
    from run_agent import AIAgent

    cfg = load_config()

    # Resolve effective model: explicit arg → env var → config.
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        cfg_model = model_cfg
    else:
        cfg_model = model_cfg.get("default") or model_cfg.get("model") or ""

    env_model = os.getenv("HERMES_INFERENCE_MODEL", "").strip()
    effective_model = (model or "").strip() or env_model or cfg_model

    # Resolve effective provider.
    effective_provider = (provider or "").strip() or None
    explicit_base_url_from_alias: Optional[str] = None
    if effective_provider is None and (model or env_model):
        explicit_model = (model or "").strip() or env_model
        if explicit_model:
            try:
                from hermes_cli import model_switch as _ms
                _ms._ensure_direct_aliases()
                direct = _ms.DIRECT_ALIASES.get(explicit_model.strip().lower())
            except Exception:
                direct = None
            if direct is not None:
                effective_model = direct.model
                effective_provider = direct.provider
                if direct.base_url:
                    explicit_base_url_from_alias = direct.base_url.rstrip("/")
            else:
                cfg_provider = ""
                if isinstance(model_cfg, dict):
                    cfg_provider = str(model_cfg.get("provider") or "").strip().lower()
                current_provider = (
                    cfg_provider
                    or os.getenv("HERMES_INFERENCE_PROVIDER", "").strip().lower()
                    or "auto"
                )
                detected = detect_provider_for_model(explicit_model, current_provider)
                if detected:
                    effective_provider, effective_model = detected

    runtime = resolve_runtime_provider(
        requested=effective_provider,
        target_model=effective_model or None,
        explicit_base_url=explicit_base_url_from_alias,
    )

    # Resolve toolsets.
    toolsets_list = _normalize_toolsets(toolsets)
    if toolsets_list is None and use_config_toolsets:
        toolsets_list = sorted(_get_platform_tools(cfg, "cli"))

    # Full SessionDB so this turn is persisted back to the session.
    session_db = SessionDB()

    # Fallback chain.
    _fb = get_fallback_chain(cfg)

    agent = AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=effective_model,
        enabled_toolsets=toolsets_list,
        session_id=session_id,
        session_db=session_db,
        quiet_mode=True,
        platform="cli",
        credential_pool=runtime.get("credential_pool"),
        fallback_model=_fb or None,
        clarify_callback=_oneshot_clarify_callback,
    )

    agent.suppress_status_output = True
    agent.stream_delta_callback = None
    agent.tool_gen_callback = None

    result = agent.run_conversation(prompt, conversation_history=conversation_history)
    return (result.get("final_response") or "", result)
```

- [ ] **Step 3: Verify it parses (import check)**

```bash
python -c "from hermes_cli.oneshot import run_oneshot_with_session, _run_agent_with_history; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add hermes_cli/oneshot.py
git commit -m "feat(oneshot): add run_oneshot_with_session and _run_agent_with_history"
```

---

## Task 3: Wire `-xz` dispatch in `main.py`

**Files:**
- Modify: `hermes_cli/main.py:15130-15143` (the existing oneshot branch)

**Interfaces:**
- Consumes: `args.xz` from argparse namespace
- Produces: calls `run_oneshot_with_session()` and exits

**Notes:**
- Insert the `args.xz` branch BEFORE the existing `args.oneshot` branch so the check order is: `xz` → `oneshot` → resume.
- Also update the Termux fast-path at line 12974 to handle `args.xz` similarly.

- [ ] **Step 1: Read the current dispatch block in main.py**

```bash
sed -n '15125,15165p' hermes_cli/main.py
```

- [ ] **Step 2: Replace the oneshot dispatch block to check args.xz first**

The new block should be:

```python
    # Handle top-level --xz / -xz / -zx: oneshot with session history.
    # Check this before --oneshot since they are mutually exclusive and argparse
    # allows both to be present in the namespace (only one is non-None).
    if getattr(args, "xz", None):
        from hermes_cli.oneshot import run_oneshot_with_session

        sys.exit(
            run_oneshot_with_session(
                args.xz,
                model=getattr(args, "model", None),
                provider=getattr(args, "provider", None),
                toolsets=getattr(args, "toolsets", None),
                usage_file=getattr(args, "usage_file", None),
            )
        )

    # Handle top-level --oneshot / -z: single-shot mode, stdout = final
    # response only, nothing else. Bypasses cli.py entirely.
    if getattr(args, "oneshot", None):
        from hermes_cli.oneshot import run_oneshot

        sys.exit(
            run_oneshot(
                args.oneshot,
                model=getattr(args, "model", None),
                provider=getattr(args, "provider", None),
                toolsets=getattr(args, "toolsets", None),
                usage_file=getattr(args, "usage_file", None),
            )
        )
```

- [ ] **Step 3: Also update the Termux fast-path around line 12974**

```bash
sed -n '12970,12990p' hermes_cli/main.py
```

Add an `args.xz` check before the `args.oneshot` check in `_try_termux_fast_cli_launch()`. If `getattr(args, "xz", None)` is set, dispatch to `run_oneshot_with_session` the same way.

- [ ] **Step 4: Verify main.py still imports without error**

```bash
python -c "import hermes_cli.main; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add hermes_cli/main.py
git commit -m "feat(main): dispatch -xz/-zx to run_oneshot_with_session"
```

---

## Task 4: Add tests

**Files:**
- Create: `tests/hermes_cli/test_xz_flag.py`

**Interfaces:**
- Tests: parser, dispatch, and the `run_oneshot_with_session` function

- [ ] **Step 1: Write parser test — verify mutex group works**

```python
"""Tests for the -xz / -zx / -z mutex group and dispatch."""
from __future__ import annotations

import argparse
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
```

- [ ] **Step 2: Write unit test for `run_oneshot_with_session` — no session found**

```python
"""Tests for run_oneshot_with_session."""
from __future__ import annotations

import pytest


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
```

- [ ] **Step 3: Run the new tests**

```bash
pytest tests/hermes_cli/test_xz_flag.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/hermes_cli/test_xz_flag.py
git commit -m "test: add tests for -xz/-zx flag and run_oneshot_with_session"
```

---

## Task 5: Manual verification

**Files:** none

- [ ] **Step 1: Verify `hermes -xz --help` shows the new flag**

```bash
python -m hermes_cli.main --help 2>&1 | grep -A3 "\-xz"
```

Expected: help text for `-xz` appears.

- [ ] **Step 2: Verify `-z` and `-xz` together fails gracefully**

```bash
python -m hermes_cli.main -z "hello" -xz "world" 2>&1 | head -5
```

Expected: argparse error about mutually exclusive options.

- [ ] **Step 3: Smoke test — no session present, correct error**

```bash
python -m hermes_cli.main -xz "hello" 2>&1
```

Expected: `hermes -xz: no session found to resume` on stderr, exit code 2 (or 0 with a different error if no SessionDB can be opened at all — both are acceptable for this smoke test).

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| `-xz` / `-zx` synonyms | Task 1 |
| `-z` and `-xz` mutually exclusive | Task 1 |
| Dispatch in `main.py` | Task 3 |
| `run_oneshot_with_session` function | Task 2 |
| `_run_agent_with_history` function | Task 2 |
| Load most recent session via `search_sessions(source=None)` | Task 2 |
| Load history via `get_messages_as_conversation(repair_alternation=True)` | Task 2 |
| Pass `session_id` and `session_db` to `AIAgent` | Task 2 |
| Pass `conversation_history` to `agent.run_conversation()` | Task 2 |
| Write usage file | Task 2 (reuses `_write_usage_file`) |
| Exit codes 0/1/2 | Task 2 |
| Error prefix `hermes -xz:` | Task 2 |
| Termux fast-path update | Task 3 |
| Parser tests | Task 4 |
| Unit tests for no-session and empty-history edge cases | Task 4 |
