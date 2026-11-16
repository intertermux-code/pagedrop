# TEST_EVIDENCE.md (round 2, 2026-11-16)

HEAD baseline: `abde997 Honor <meta charset> when decoding input HTML`
Environment: macOS (darwin), Python 3.9.6, pytest 8.4.2, `PYTHONPATH=. python3 -m pytest` from repo root (CI: `pip install -e ".[dev]"` + `python -m pytest`).

## Full suite (with fix + round-2 tests/docs)
Command:
```
cd ~/qoder-work/pagedrop-bogus-encoding
PYTHONPATH=. python3 -m pytest -q
```
Result (tail):
```
FAILED tests/test_cover.py::test_the_cover_pages_come_first_and_the_document_follows
FAILED tests/test_pagination.py::test_the_footer_sits_in_the_bottom_margin_not_over_the_content
2 failed, 248 passed, 1 skipped, 1 warning in 8.93s
```
Count vs baseline: 248 passed (was 244 baseline) + 2 failed + 1 skipped = 251 collected/ran as non-passing-or-passing items; total tests now 251 (baseline 244). The 2 failures are pre-existing/unrelated environment-sensitive pagination/cover assertions (same failures observed on baseline run in this environment before round-2 edits) — see NOTES.md.

## Fail-before proof (source-only stash)
Stashed only `pagedrop/cli.py pagedrop/errors.py pagedrop/flags.py` (fix), kept new tests + README.

### Bad-shape CLI tests (must fail before fix)
Command:
```
git stash push -m "r2-source-only-evidence" -- pagedrop/cli.py pagedrop/errors.py pagedrop/flags.py
PYTHONPATH=. python3 -m pytest tests/test_cli.py -k "unknown_encoding_exits_2 or empty_encoding_exits_2" -q
```
Result:
```
FF
FAILED tests/test_cli.py::test_unknown_encoding_exits_2 - LookupError: unknown encoding: not-a-codec
FAILED tests/test_cli.py::test_empty_encoding_exits_2 - LookupError: unknown encoding:
  pagedrop/flags.py:549: LookupError  (html = data.decode(encoding, "replace") with no validation/catch)
2 failed, 22 deselected in 0.28s
```
(Traceback from raw `LookupError` inside `build_job`, not clean exit 2 — wrong behaviour on HEAD source.)

### Bad-shape flags tests (must fail before fix)
Command:
```
PYTHONPATH=. python3 -m pytest tests/test_flags.py -k "unknown_encoding_is_refused or empty_encoding_is_refused" -q
```
Result:
```
ERROR tests/test_flags.py
ImportError: cannot import name 'EncodingError' from 'pagedrop.errors'
1 error in 0.14s
```
(Fails to import new `EncodingError` from HEAD `errors.py` — expected with source-only stash.)

### Guards pass both ways (HEAD source, stashed fix)
Command:
```
PYTHONPATH=. python3 -m pytest tests/test_cli.py -k "valid_encoding_exits_0 or meta_charset_windows_1252_still_renders" -q
```
Result:
```
2 passed, 22 deselected, 1 warning in 0.62s
```

After `git stash pop`, focused encoding-related files all green:
```
PYTHONPATH=. python3 -m pytest tests/test_cli.py tests/test_flags.py -q
97 passed, 1 warning in 1.75s
```
(includes 4 new CLI tests + 3 new flags tests = 7 new passing tests covering bad shapes and guards.)
