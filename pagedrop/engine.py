"""Turning a Job into PDF bytes.

The engine is xhtml2pdf on top of ReportLab: pure Python, no system libraries,
so ``pip install`` is the whole installation story. wkhtmltopdf's page model --
a content box inside the margins, with header and footer stamped into those
margins on every page -- maps onto its ``@page`` and ``@frame`` rules almost
directly, which is what makes the flags translatable at all.
"""

from __future__ import annotations

import html as html_module
import os
import re
from typing import List, Optional

from .errors import EngineError
from .grayscale import to_grayscale
from .spec import Band, Job

HEADER_ID = "wkhtmltopdfDropinHeader"
FOOTER_ID = "wkhtmltopdfDropinFooter"

_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(r"(<head\b[^>]*>)", re.IGNORECASE)
_HTML_OPEN_RE = re.compile(r"(<html\b[^>]*>)", re.IGNORECASE)
_BODY_OPEN_RE = re.compile(r"(<body\b[^>]*>)", re.IGNORECASE)

_OUTLINE_HEADINGS = "h1, h2, h3, h4, h5, h6"


def _frame(name: str, content_id: str, top: float, left: float, width: float, height: float) -> str:
    return (
        f"@frame {name} {{ -pdf-frame-content: {content_id}; "
        f"top: {top:.2f}pt; left: {left:.2f}pt; width: {width:.2f}pt; height: {height:.2f}pt; }}"
    )


def _band_css(band: Band, content_id: str, is_header: bool) -> str:
    edge = "border-bottom" if is_header else "border-top"
    line = f" {edge}: 0.75pt solid black;" if band.line else ""
    return (
        f"#{content_id} {{ font-family: {band.font_name}; font-size: {band.font_size}pt; "
        f"color: {band.font_color}; padding: 0; margin: 0;{line} }}\n"
        f"#{content_id} table {{ width: 100%; }}\n"
        f"#{content_id} td {{ border: none; padding: 0; }}"
    )


def _band_markup(band: Band) -> str:
    """The flow content the band frame draws: the html fragment, then the text cells."""
    parts: List[str] = []
    if band.html:
        parts.append(band.html)
    if band.left or band.center or band.right:
        cells = []
        for side, width in (("left", "33%"), ("center", "34%"), ("right", "33%")):
            text = getattr(band, side)
            cells.append(
                f'<td style="width:{width}; text-align:{side}; vertical-align:top">{text or "&nbsp;"}</td>'
            )
        parts.append("<table><tr>" + "".join(cells) + "</tr></table>")
    return "\n".join(parts)


def page_css(job: Job) -> str:
    """The ``@page`` rules: paper, margins, and one frame per band."""
    top, right, bottom, left = job.margins
    content_width = job.page_width - left - right
    rules = [f"@page {{ size: {job.page_width:.2f}pt {job.page_height:.2f}pt;",
             f"  margin: {top:.2f}pt {right:.2f}pt {bottom:.2f}pt {left:.2f}pt;"]

    for band, content_id, is_header in (
        (job.header, HEADER_ID, True),
        (job.footer, FOOTER_ID, False),
    ):
        if band is None or not band.wanted:
            continue
        depth = band.depth
        if is_header:
            rules.append("  " + _frame(f"wkhtmltopdf-dropin-{content_id}", content_id, 0.0, left, content_width, depth))
        else:
            rules.append(
                "  "
                + _frame(
                    f"wkhtmltopdf-dropin-{content_id}",
                    content_id,
                    job.page_height - job.margins[2] + band.spacing,
                    left,
                    content_width,
                    depth,
                )
            )
    rules.append("}")

    if not job.outline:
        rules.append(f"{_OUTLINE_HEADINGS} {{ -pdf-outline: false; }}")
    elif job.outline_depth is not None and 0 < job.outline_depth < 6:
        hidden = ", ".join(f"h{level}" for level in range(job.outline_depth + 1, 7))
        rules.append(f"{hidden} {{ -pdf-outline: false; }}")

    for band, content_id, is_header in (
        (job.header, HEADER_ID, True),
        (job.footer, FOOTER_ID, False),
    ):
        if band is not None and band.wanted:
            rules.append(band.css)
            rules.append(_band_css(band, content_id, is_header))

    if job.stylesheet:
        rules.append(job.stylesheet)
    return "\n".join(rules) + "\n"


def inject(document: str, head: str, body: str) -> str:
    """Put generated CSS into ``<head>`` and markup at the start of ``<body>``."""
    if _HEAD_CLOSE_RE.search(document):
        document = _HEAD_CLOSE_RE.sub(head + "</head>", document, count=1)
    elif _HEAD_OPEN_RE.search(document):
        document = _HEAD_OPEN_RE.sub(r"\1" + head, document, count=1)
    elif _HTML_OPEN_RE.search(document):
        document = _HTML_OPEN_RE.sub(r"\1<head>" + head + "</head>", document, count=1)
    else:
        document = "<html><head>" + head + "</head><body>" + body + "</body></html>"
        return document

    if _BODY_OPEN_RE.search(document):
        return _BODY_OPEN_RE.sub(r"\1" + body, document, count=1)
    return document.replace("</body>", body + "</body>", 1) if "</body>" in document else document + body


def assemble(job: Job) -> str:
    """The document handed to the engine: the input plus generated page rules."""
    head = f"<style>\n{page_css(job)}\n</style>\n"
    if job.title:
        head += f"<title>{html_module.escape(str(job.title), quote=False)}</title>\n"

    bands = []
    for band, content_id in ((job.header, HEADER_ID), (job.footer, FOOTER_ID)):
        if band is not None and band.wanted:
            bands.append(f'<div id="{content_id}">{_band_markup(band)}</div>')
    return inject(job.html, head, "\n".join(bands))


def resource_policy(job: Job):
    """How far the engine may reach for images and fonts the document names.

    The engine grew a confinement policy that wkhtmltopdf never had. Without
    lifting it, a report whose logo sits at an absolute path would quietly
    lose it, so local reads are open by default -- which is what upstream's
    ``--enable-local-file-access`` means, and what it defaults to.
    """
    try:
        from xhtml2pdf.config.resources import ResourceAccessPolicy
    except ImportError:
        if job.confine_local_files:
            raise EngineError(
                "--disable-local-file-access needs an xhtml2pdf release that ships "
                "ResourceAccessPolicy; this one cannot confine the document"
            )
        return None

    roots = tuple(part for part in os.environ.get("PAGEDROP_RESOURCE_ROOTS", "").split(os.pathsep) if part)
    return ResourceAccessPolicy(
        base_dir=job.base_dir,
        extra_roots=roots,
        allow_local_outside_base=not job.confine_local_files,
    )


def render(job: Job) -> bytes:
    from xhtml2pdf import pisa  # imported late so --help stays instant

    document = assemble(job)
    kwargs = {}
    policy = resource_policy(job)
    if policy is not None:
        kwargs["resource_policy"] = policy
    try:
        result = pisa.pisaDocument(
            document,
            dest_bytes=True,
            path=job.base_dir,
            context_meta={"title": str(job.title or "")},
            **kwargs,
        )
    except Exception as error:  # noqa: BLE001 - the engine raises anything at us
        raise EngineError(f"the print engine could not render this document: {error}") from None

    data: Optional[bytes] = result
    if not data or not data.startswith(b"%PDF"):
        raise EngineError("the print engine produced no PDF output")
    return to_grayscale(data) if job.grayscale else data
