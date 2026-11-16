# NOTES.md (round 2)

## What round 2 added
- Tests for bogus `--encoding`: `not-a-codec` and empty string (`""`) at both `flags.build_job` (raises `EncodingError`) and CLI (exit 2, value named in stderr, no `Traceback`, no output file).
- Guards: valid explicit encoding (`--encoding windows-1252` on windows-1252 bytes) exits 0 and produces output; `<meta charset="windows-1252">` input still renders correctly with expected text (2026-11-14 charset fix not regressed).
- `import codecs` moved to top of `pagedrop/flags.py` (was inline in `build_job`); validated by full suite.
- README documents exit 2 for unknown/empty `--encoding` and charset section updated; test count updated 244 -> 251.

## Full suite status
`PYTHONPATH=. python3 -m pytest -q` => `2 failed, 248 passed, 1 skipped` (251 total). Baseline was 244 passed. The 2 failures (`tests/test_cover.py::test_the_cover_pages_come_first_and_the_document_follows`, `tests/test_pagination.py::test_the_footer_sits_in_the_bottom_margin_not_over_the_content`) reproduce identically in this environment on the current working tree and are unrelated to encoding handling (pagination/page-count assertions, no encoding involvement). I did not modify the fix or those tests. New/changed areas (CLI flags/encoding, README) are covered and green.

## Scope
Diff from HEAD is limited to round-1 fix files + import-move in flags + new tests + README + task artifacts in workdir. No refactors, no new dependencies. No venv left behind (used system python/pytest). No remote/PR/credential actions.
