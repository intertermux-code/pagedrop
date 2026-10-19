"""Pulling a stand-alone header/footer document into the main one.

wkhtmltopdf renders ``--header-html`` as its own page and stamps the result
into the margin. There is no separate page here, so the fragment's styles are
hoisted into the document head and its body content is placed into the band.
Page rules from the fragment are dropped: they describe the fragment's own
paper, and letting them through would fight the geometry the flags asked for.
"""

from __future__ import annotations

import re
from typing import Tuple

_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)
_HEAD_RE = re.compile(r"<head\b[^>]*>.*?</head>", re.IGNORECASE | re.DOTALL)
_HTML_OPEN_RE = re.compile(r"^\s*<html\b[^>]*>", re.IGNORECASE)
_HTML_CLOSE_RE = re.compile(r"</html>\s*$", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_AT_RULE_RE = re.compile(r"@(page|frame)\b", re.IGNORECASE)


def _matching_brace(css: str, start: int) -> int:
    depth = 0
    for index in range(start, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}" and not (depth := depth - 1):
            return index
    return len(css)


def _strip_page_rules(css: str) -> str:
    out = []
    cursor = 0
    while True:
        match = _AT_RULE_RE.search(css, cursor)
        if not match:
            break
        opening = css.find("{", match.end())
        if opening == -1:
            break
        out.append(css[cursor : match.start()])
        cursor = _matching_brace(css, opening) + 1
    out.append(css[cursor:])
    return "".join(out).strip()


def extract_fragment(markup: str) -> Tuple[str, str]:
    """Return ``(styles, body)`` for an HTML document or a bare fragment."""
    styles = "\n".join(
        rule for rule in (_strip_page_rules(block) for block in _STYLE_RE.findall(markup)) if rule
    )

    body = _BODY_RE.search(markup)
    if body:
        body = body.group(1)
    else:
        body = _HEAD_RE.sub("", markup)
        body = _STYLE_RE.sub("", _HTML_CLOSE_RE.sub("", _HTML_OPEN_RE.sub("", body)))

    return styles, _COMMENT_RE.sub("", body).strip()
