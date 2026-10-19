"""``--grayscale``.

The engine has no colour management, but the PDF it writes sets colour with
plain ``rg``/``RG`` operators, so the page content can be rewritten to the
luminance equivalent. Anything the rewrite does not recognise is left alone.
"""

from __future__ import annotations

import io
import re

_RGB_OPERATOR = re.compile(rb"([-+]?(?:\d+\.?\d*|\.\d+)) ([-+]?(?:\d+\.?\d*|\.\d+)) ([-+]?(?:\d+\.?\d*|\.\d+)) (rg|RG)\b")

# ITU-R BT.601 luma, the weighting PDF viewers reach for.
_WEIGHTS = (0.299, 0.587, 0.114)

# A grey takes one operand, so the operator changes with the colour space.
_GRAY_OPERATOR = {b"rg": b"g", b"RG": b"G"}


def desaturate(stream: bytes) -> bytes:
    def one(match: "re.Match[bytes]") -> bytes:
        red, green, blue = (float(match.group(i)) for i in (1, 2, 3))
        luma = max(0.0, min(1.0, red * _WEIGHTS[0] + green * _WEIGHTS[1] + blue * _WEIGHTS[2]))
        return b"%.4f %s" % (luma, _GRAY_OPERATOR[match.group(4)])

    return _RGB_OPERATOR.sub(one, stream)


def to_grayscale(data: bytes) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=io.BytesIO(data))
    for page in writer.pages:
        content = page.get_contents()
        if content is None:
            continue
        original = content.get_data()
        converted = desaturate(original)
        if converted != original:
            content.set_data(converted)
            page.replace_contents(content)  # get_contents hands back a copy, not the page's own

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
