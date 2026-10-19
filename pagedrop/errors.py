"""Errors that stop the conversion.

Everything the shim can decide to refuse raises one of these so the CLI can
print a single line and exit 1, the way wkhtmltopdf does.
"""

from __future__ import annotations


class ShimError(Exception):
    """A refusal the user asked for: bad flags, an unsupported option."""


class EngineError(ShimError):
    """The print engine failed on a document the flags were fine with."""
