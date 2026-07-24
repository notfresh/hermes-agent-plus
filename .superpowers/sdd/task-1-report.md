# Task 1 Report

## Status

DONE

## What I did

- Updated `/root/projects/hermes-agent-plus/hermes_cli/_parser.py` by replacing the standalone `-z` argument with a mutually exclusive argument group.
- Preserved `-z` / `--oneshot` as `args.oneshot`.
- Added `-xz` / `--xz` and `-zx` / `--zx`, all mapping to `args.xz`.
- Suppressed the separate `-zx` / `--zx` help entry, as required.
- Verified that all four `xz` spellings populate `args.xz` and that `-z` cannot be combined with `-xz`.

## Commands run

1. Required test command from the brief:

   ```text
   pytest tests/hermes_cli/test_argparse_flag_propagation.py -v -x
   ```

   Initial result: command unavailable (`pytest: command not found`).

2. Environment inspection:

   ```text
   ls -la && ls -la .venv/bin/pytest venv/bin/pytest 2>/dev/null || true
   command -v uv || true; command -v python || true; python -m pytest --version 2>&1 || true
   command -v python3 || true; python3 -m pytest --version 2>&1 || true; command -v uvx || true; command -v pip3 || true
   ```

   Findings: `/usr/bin/python3` and `pip3` were available, but pytest was not installed and there was no project virtual environment.

3. Installed the test runner:

   ```text
   python3 -m pip install --user pytest
   ```

4. Ran the test through Python:

   ```text
   python3 -m pytest tests/hermes_cli/test_argparse_flag_propagation.py -v -x
   ```

   First result: 2 passed, then collection/execution stopped because the declared runtime dependency `python-dotenv` was absent.

5. Installed missing declared dependency:

   ```text
   python3 -m pip install --user python-dotenv==1.2.2
   ```

6. Reran the test:

   ```text
   python3 -m pytest tests/hermes_cli/test_argparse_flag_propagation.py -v -x
   ```

   Second result: 6 passed, then stopped because `rich` was absent.

7. Installed the missing runtime dependency:

   ```text
   python3 -m pip install --user rich
   ```

8. Final required test run:

   ```text
   python3 -m pytest tests/hermes_cli/test_argparse_flag_propagation.py -v -x
   ```

   Output summary:

   ```text
   collected 23 items
   23 passed in 1.06s
   ```

9. Direct parser behavior verification:

   ```text
   python3 - <<'PY'
   from hermes_cli._parser import build_top_level_parser
   p, _, _ = build_top_level_parser()
   for flag in ('-xz', '-zx', '--xz', '--zx'):
       a = p.parse_args([flag, 'prompt'])
       assert a.xz == 'prompt' and a.oneshot is None, (flag, a)
   try:
       p.parse_args(['-z', 'one', '-xz', 'two'])
   except SystemExit as exc:
       assert exc.code == 2
   else:
       raise AssertionError('mutex was not enforced')
   print('all -xz/-zx aliases map to args.xz; mutex enforced')
   PY
   ```

   Output:

   ```text
   hermes: error: argument -xz/--xz: not allowed with argument -z/--oneshot
   all -xz/-zx aliases map to args.xz; mutex enforced
   ```

## Issues encountered

- The requested bare `pytest` command could not run because pytest was not installed or on `PATH`.
- The system Python initially lacked `python-dotenv` and `rich`, which the selected test imports through Hermes CLI modules. I installed those dependencies in the user Python environment and reran the test successfully.
- No source-code issues remained after verification.
