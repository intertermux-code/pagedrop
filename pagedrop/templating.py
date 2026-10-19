"""The ``[page]``-style variables wkhtmltopdf understands in headers and footers.

Two of them -- the current page and the page count -- are only known while the
page is being drawn, so they are handed to the print engine as tags and stay
correct on every page. Everything else is resolved once, at conversion time.
"""

from __future__ import annotations

import html
import re
from typing import Dict, List, Optional

PAGE_NUMBER_TAG = "<pdf:pagenumber/>"
PAGE_COUNT_TAG = "<pdf:pagecount/>"

TAG_RE = re.compile(r"<[^>]*>")
TOKEN_RE = re.compile(r"\[([a-z]+)\]")

# Tokens that resolve to something the engine cannot know per page. They come
# out empty, and the caller is told so rather than left guessing.
DEGRADED = {
    "section": "[section] needs WebKit's per-page chapter tracking; it renders empty",
    "subsection": "[subsection] needs WebKit's per-page chapter tracking; it renders empty",
    "valuelist": "[valuelist] has no source in this engine; it renders empty",
}


def _values(ctx: Dict[str, object]) -> Dict[str, str]:
    now = ctx["now"]
    title = str(ctx.get("title") or "")
    url = str(ctx.get("url") or "")
    return {
        "page": PAGE_NUMBER_TAG,
        "topage": PAGE_COUNT_TAG,
        "frompage": "1",
        "date": now.strftime("%m/%d/%y"),
        "isodate": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timestamp": str(int(now.timestamp())),
        "year": now.strftime("%Y"),
        "month": now.strftime("%m"),
        "day": now.strftime("%d"),
        "title": title,
        "doctitle": title,
        "url": url,
        "webpage": url,
        **{name: "" for name in DEGRADED},
    }


def _replace(text: str, values: Dict[str, str], notes: Optional[List[str]]) -> str:
    def one(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        if notes is not None and name in DEGRADED:
            notes.append(DEGRADED[name])
        return values[name]

    return TOKEN_RE.sub(one, text)


def _outside_tags(markup: str, values: Dict[str, str], notes: Optional[List[str]]) -> str:
    """Substitute in text runs only, never inside a tag or a <style> block."""
    parts: List[str] = []
    style_depth = 0
    cursor = 0
    for tag in TAG_RE.finditer(markup):
        chunk = markup[cursor : tag.start()]
        parts.append(chunk if style_depth else _replace(chunk, values, notes))
        name = tag.group(0)[1:].lstrip("/").split(None, 1)[0].rstrip(">").lower()
        if name == "style" or name == "script":
            style_depth += -1 if tag.group(0).startswith("</") else 1
        parts.append(tag.group(0))
        cursor = tag.end()
    tail = markup[cursor:]
    parts.append(tail if style_depth else _replace(tail, values, notes))
    return "".join(parts)


def substitute(
    text: str,
    ctx: Dict[str, object],
    *,
    escape: bool = False,
    notes: Optional[List[str]] = None,
) -> str:
    """Expand wkhtmltopdf header/footer variables in ``text``.

    With ``escape`` the input is treated as a literal string from the command
    line and HTML-escaped first, so a user's ``<`` cannot open a tag.
    """
    if escape:
        text = html.escape(text, quote=False)
    return _outside_tags(text, _values(ctx), notes)
