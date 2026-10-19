"""Length and paper-size parsing, in points once parsed."""

from __future__ import annotations

import re
from typing import Tuple

from .errors import ShimError

# CSS reference pixel: 96px to the inch, 72pt to the inch.
UNIT_TO_PT = {
    "px": 0.75,
    "pt": 1.0,
    "in": 72.0,
    "cm": 28.346456692913385,
    "mm": 2.834645669291339,
    "q": 0.7086614173228346,
}

_LENGTH_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")

PAPER_SIZES = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "a6": (105.0, 148.0),
    "b4": (250.0, 353.0),
    "b5": (176.0, 250.0),
    "c5": (162.0, 229.0),
    "executive": (7.5, 10.0),
    "folio": (8.5, 13.0),
    "legal": (8.5, 14.0),
    "letter": (8.5, 11.0),
    "quarto": (8.0, 10.0),
    "tabloid": (11.0, 17.0),
    "11x17": (11.0, 17.0),
}

# The sizes above that are given in inches rather than millimetres.
_INCHES = {"executive", "folio", "legal", "letter", "quarto", "tabloid", "11x17"}

_CUSTOM_RE = re.compile(r"^(\d+(?:\.\d+)?[a-z]*)\s*[x*]\s*(\d+(?:\.\d+)?[a-z]*)$", re.IGNORECASE)


def mm(value: float) -> float:
    """Millimetres as points, for the defaults spelled in the flag table."""
    return to_pt(value, "mm")


def to_pt(value: float, unit: str) -> float:
    try:
        factor = UNIT_TO_PT[unit]
    except KeyError:
        raise ShimError(f"unknown unit '{unit}', expected one of {', '.join(sorted(UNIT_TO_PT))}") from None
    return value * factor


def parse_length(text: object, default_unit: str = "mm") -> float:
    """A length in points: ``12``, ``12mm``, ``0.5in``, ``-1``."""
    match = _LENGTH_RE.match(str(text))
    if not match:
        raise ShimError(f"'{text}' is not a length, expected e.g. 10, 10mm, 0.5in")
    number, unit = match.group(1), (match.group(2) or default_unit).lower()
    return to_pt(float(number), unit)


def page_size(name: str) -> Tuple[float, float]:
    """A paper size in points, portrait, from wkhtmltopdf's ``--page-size``."""
    key = str(name).strip().lower()
    if key in PAPER_SIZES:
        width, height = PAPER_SIZES[key]
        factor = 72.0 if key in _INCHES else 2.834645669291339
        return (width * factor, height * factor)

    custom = _CUSTOM_RE.match(key)
    if custom:
        width = parse_length(custom.group(1), default_unit="mm")
        height = parse_length(custom.group(2), default_unit="mm")
        return (width, height)

    raise ShimError(
        f"unknown paper size '{name}', expected one of "
        + ", ".join(sorted(PAPER_SIZES, key=str.upper))
        + " or WIDTHxHEIGHT such as 210mmx297mm"
    )


def apply_orientation(size: Tuple[float, float], orientation: str) -> Tuple[float, float]:
    value = str(orientation).strip().lower()
    if value in ("portrait", "p"):
        return size
    if value in ("landscape", "l"):
        return (size[1], size[0])
    raise ShimError(f"unknown orientation '{orientation}', expected Portrait or Landscape")
