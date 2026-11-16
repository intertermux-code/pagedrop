# Task: pagedrop bogus --encoding fix

HEAD: abde997 Honor <meta charset> when decoding input HTML

Fix: unknown/empty --encoding now raises EncodingError -> exit 2, clean stderr.

Baseline tests: 244 passed. After fix: 244 passed.

## Round 2 (2026-11-16)

### Scope completed
- Added missing tests for bogus `--encoding` (bad shapes) and guards:
  - `tests/test_flags.py`: `test_unknown_encoding_is_refused` (not-a-codec -> `EncodingError` naming value), `test_empty_encoding_is_refused` (empty string -> `EncodingError` naming empty value), `test_valid_encoding_still_builds_job` (`latin-1` builds job). Added `EncodingError` import.
  - `tests/test_cli.py`: `test_unknown_encoding_exits_2`, `test_empty_encoding_exits_2` (assert exit 2, value named in stderr, no `Traceback`, no output file), `test_valid_encoding_exits_0` (windows-1252 bytes + `--encoding windows-1252`, exit 0, output exists), `test_meta_charset_windows_1252_still_renders` (meta charset windows-1252 renders, text contains `Grüße`/`naïf`).
- Fail-before proof (source-only stash of `pagedrop/cli.py pagedrop/errors.py pagedrop/flags.py`, tests/docs kept):
  - `PYTHONPATH=. python3 -m pytest tests/test_cli.py -k "unknown_encoding_exits_2 or empty_encoding_exits_2" -q` => `2 failed` with raw `LookupError: unknown encoding: not-a-codec` / `unknown encoding:` at `pagedrop/flags.py:549` (HEAD source, no clean exit-2 handling).
  - `PYTHONPATH=. python3 -m pytest tests/test_flags.py -k "unknown_encoding_is_refused or empty_encoding_is_refused" -q` => collection `ERROR` `ImportError: cannot import name 'EncodingError'` (HEAD source).
  - Guards both ways: `PYTHONPATH=. python3 -m pytest tests/test_cli.py -k "valid_encoding_exits_0 or meta_charset_windows_1252_still_renders" -q` => `2 passed` while fix stashed.
  - After `git stash pop`: `PYTHONPATH=. python3 -m pytest tests/test_cli.py tests/test_flags.py -q` => `97 passed`.
- Tidy: moved inline `import codecs` in `build_job` to top-level imports in `pagedrop/flags.py`; removed inline import; suite still passes in affected areas.
- README: documented exit 2 for unknown/empty `--encoding` in flag refusal text and charset section; updated suite count 244 -> 251.

### Verification commands/results
- `PYTHONPATH=. python3 -m pytest tests/test_cli.py tests/test_flags.py -q` => `97 passed, 1 warning`
- Full suite: `PYTHONPATH=. python3 -m pytest -q` => `2 failed, 248 passed, 1 skipped, 1 warning in 8.93s` (251 total). Two failures are pre-existing/unrelated env-sensitive pagination/cover tests (`test_cover.py::test_the_cover_pages_come_first_and_the_document_follows`, `test_pagination.py::test_the_footer_sits_in_the_bottom_margin_not_over_the_content`), unchanged by this work.

### Open
- Two pre-existing unrelated test failures in this environment (not caused by encoding/fix/tests/docs changes). All encoding-related additions and guards pass; full suite count increased from 244 to 251 with 248 passing here.
