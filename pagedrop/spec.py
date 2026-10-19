"""The converted-to structures: what the engine is asked to render."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Band:
    """A header or footer: the page margin it lives in, and what to draw there."""

    margin: float = 0.0  # pt of page margin reserved for this band
    spacing: float = 0.0  # pt gap between the band and the content
    html: str = ""  # already token-substituted markup from --header-html
    css: str = ""  # styles the fragment brought with it
    left: str = ""
    center: str = ""
    right: str = ""
    line: bool = False
    font_name: str = "Helvetica"
    font_size: float = 12.0
    font_color: str = "#000000"

    @property
    def wanted(self) -> bool:
        return bool(self.html or self.left or self.center or self.right or self.line)

    @property
    def depth(self) -> float:
        """How far the band reaches into the page margin."""
        return max(self.margin - self.spacing, 0.0)


@dataclass
class Job:
    """Everything needed to render one document, in points and strings."""

    html: str
    source: str
    base_dir: str = "."
    page_width: float = 595.28
    page_height: float = 841.89
    margins: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # top right bottom left
    header: Optional[Band] = None
    footer: Optional[Band] = None
    title: Optional[str] = None
    outline: bool = True
    outline_depth: Optional[int] = None
    grayscale: bool = False
    stylesheet: str = ""
    log_path: Optional[str] = None
    quiet: bool = False
    confine_local_files: bool = False
    notes: List[str] = field(default_factory=list)
