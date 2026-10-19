from datetime import datetime, timezone

import pytest

from pagedrop import templating

NOW = datetime(2026, 10, 19, 8, 30, 5, tzinfo=timezone.utc)


def sub(text, notes=None, **overrides):
    ctx = {"now": NOW, "title": "Invoice 42", "url": "in.html"}
    ctx.update(overrides)
    return templating.substitute(text, ctx, notes=notes)


def test_page_tokens_become_engine_tags():
    assert sub("Page [page] of [topage]") == "Page <pdf:pagenumber/> of <pdf:pagecount/>"


def test_frompage_is_the_first_page():
    assert sub("[frompage]") == "1"


def test_dates():
    assert sub("[date]|[isodate]|[time]|[year]|[month]|[day]") == (
        "10/19/26|2026-10-19|08:30:05|2026|10|19"
    )


def test_timestamp():
    assert sub("[timestamp]") == str(int(NOW.timestamp()))


def test_title_and_url():
    assert sub("[title] - [url] - [doctitle] - [webpage]") == "Invoice 42 - in.html - Invoice 42 - in.html"


def test_unknown_token_survives():
    assert sub("[notaworkingtoken] stays") == "[notaworkingtoken] stays"


def test_attributes_are_left_alone():
    assert sub('<a href="/page">[page]</a>') == '<a href="/page"><pdf:pagenumber/></a>'


def test_style_content_is_left_alone():
    assert sub("<style>p{content:'[page]'}</style>") == "<style>p{content:'[page]'}</style>"


def test_escaping_happens_before_substitution():
    out = templating.substitute("<b>[page]</b>", {"now": NOW}, escape=True)
    assert out == "&lt;b&gt;<pdf:pagenumber/>&lt;/b&gt;"


def test_degraded_tokens_are_reported():
    notes = []
    sub("[section] and [subsection]", notes=notes)
    assert len(notes) == 2
    assert "section" in notes[0] and "subsection" in notes[1]


def test_no_notes_when_nothing_is_degraded():
    notes = []
    sub("[page] of [topage] on [date]", notes=notes)
    assert notes == []


def test_missing_context_renders_empty():
    assert templating.substitute("[title]", {"now": NOW}) == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
