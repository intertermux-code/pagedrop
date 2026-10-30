"""The wkhtmltopdf flag table.

One entry per option the shim knows about: how it is spelled, which section of
``--help`` it belongs to, and whether the print engine can actually honour it.
The parser, the help text and the refusal messages are all generated from this
table so they cannot drift apart.

Support levels
    SUPPORTED     translated into the engine's page model
    INHERENT      the engine already behaves this way, so the flag is a no-op
    DEFAULT_ONLY  accepted at the value wkhtmltopdf defaults to, refused above it
    UNSUPPORTED   refused, with the reason
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import templating
from .errors import ShimError
from .fragments import extract_fragment
from .resources import read_resource
from .spec import Band, Job
from .units import apply_orientation, mm, page_size, parse_length

SUPPORTED = "supported"
INHERENT = "inherent"
DEFAULT_ONLY = "default-only"
UNSUPPORTED = "unsupported"

DEFAULT_MARGIN = mm(10)
DEFAULT_BAND_DEPTH = mm(15)
NO_JS = "the print engine runs no JavaScript"


class Flag:
    def __init__(
        self,
        name: str,
        summary: str,
        group: str,
        metavar: Optional[str] = None,
        short: Optional[str] = None,
        support: str = SUPPORTED,
        limitation: str = "",
        default: Optional[str] = None,
    ) -> None:
        self.name = name
        self.summary = summary
        self.group = group
        self.metavar = metavar
        self.short = short
        self.support = support
        self.limitation = limitation
        self.default = default

    @property
    def dest(self) -> str:
        return self.name[2:].replace("-", "_")

    @property
    def option_strings(self) -> List[str]:
        return [self.name] + ([self.short] if self.short else [])

    @property
    def is_boolean(self) -> bool:
        return self.metavar is None

    def help_line(self) -> str:
        value = f" {self.metavar}" if self.metavar else ""
        left = f"  {self.name}{value}"
        if self.short:
            left = f"  {self.short}, {left.strip()}"
        return f"{left:<44}{self.summary} [{self.group}]"


FLAGS: List[Flag] = [
    # --- global -------------------------------------------------------------
    Flag("--quiet", "Be less verbose, maintained for backwards compatibility", "global",
         short="-q", support=INHERENT),
    Flag("--log-level", "Log level: none, info, error", "global", metavar="<level>"),
    Flag("--encoding", "Set the default text encoding, for input", "global", metavar="<encoding>"),
    Flag("--title", "The title of the generated pdf file", "global", metavar="<text>"),
    Flag("--dpi", "Change the dpi explicitly (default 96)", "global", metavar="<dpi>", short="-d",
         support=DEFAULT_ONLY, default="96",
         limitation="--dpi other than 96 cannot be honoured: the engine lays out against a fixed CSS reference pixel"),
    Flag("--zoom", "Use this zoom factor (default 1)", "global", metavar="<float>",
         support=DEFAULT_ONLY, default="1",
         limitation="--zoom is not supported: the engine does not reflow to fit. Scale the document in CSS instead, e.g. body { font-size: 90% }"),
    Flag("--disable-smart-shrinking",
         "Disable the intelligent shrinking strategy used by WebKit", "global", support=INHERENT),
    Flag("--enable-smart-shrinking",
         "Enable the intelligent shrinking strategy used by WebKit (default)", "global",
         support=UNSUPPORTED,
         limitation="WebKit's shrink-to-fit is not reproduced; set the type scale in CSS instead"),
    Flag("--print-media-type", "Use print media-type instead of screen", "global", support=INHERENT),
    Flag("--no-print-media-type", "Do not use print media-type instead of screen (default)", "global",
         support=UNSUPPORTED, limitation="the engine only ever applies print media styles"),
    Flag("--user-style-sheet", "Specify a user style sheet, to load with every page", "global",
         metavar="<url>"),
    Flag("--enable-local-file-access",
         "Allowed conversion of a local file to read in other local files. (default)", "global",
         support=INHERENT),
    Flag("--disable-local-file-access", "Disallow reading other local files", "global",
         support=SUPPORTED),
    Flag("--enable-javascript", "Do allow web pages to run javascript (default)", "global",
         support=UNSUPPORTED,
         limitation=f"{NO_JS}; pre-render the dynamic content, or keep wkhtmltopdf for this document"),
    Flag("--disable-javascript", "Do not allow web pages to run javascript", "global", support=INHERENT),
    Flag("--javascript-delay", "Wait some milliseconds for javascript finish (default 200)", "global",
         metavar="<msec>", support=UNSUPPORTED, limitation=f"{NO_JS}, so there is nothing to wait for"),
    Flag("--run-script", "Run this additional JavaScript after the page is loaded", "global",
         metavar="<string>", support=UNSUPPORTED, limitation=NO_JS),
    Flag("--no-stop-slow-scripts", "Do not stop slow running scripts", "global", support=INHERENT),
    Flag("--cookie", "Add a cookie to the request", "global", metavar="<key> <value>",
         support=UNSUPPORTED,
         limitation="the shim does not carry authenticated sessions; save the page and pass it as a file"),
    Flag("--cookie-jar", "Read and write cookies from and to the supplied cookie jar file", "global",
         metavar="<name>", support=UNSUPPORTED, limitation="the shim does not carry authenticated sessions"),
    Flag("--username", "User name for authentication", "global", metavar="<string>",
         support=UNSUPPORTED, limitation="the shim does not authenticate when it fetches a URL"),
    Flag("--password", "Password for authentication", "global", metavar="<string>",
         support=UNSUPPORTED, limitation="the shim does not authenticate when it fetches a URL"),
    Flag("--proxy", "Use proxy server [:<type>://]<host>[:<port>]", "global", metavar="<string>",
         support=UNSUPPORTED, limitation="the shim fetches URLs directly and has no proxy option"),
    Flag("--load-error-handling", "Determine how to handle errors while loading resources", "global",
         metavar="<handler>", support=UNSUPPORTED,
         limitation="a resource the engine cannot read fails the conversion; there is no ignore mode"),
    Flag("--options-file", "Read additional options from <file>", "global", metavar="<file>"),
    Flag("--log-path", "Write the conversion log to <file>", "global", metavar="<file>"),
    Flag("--lowquality", "Generates lower quality pdf/ps", "global", short="-l", support=INHERENT),
    Flag("--copies", "Number of copies to print into the pdf file (default 1)", "global",
         metavar="<number>", support=DEFAULT_ONLY, default="1",
         limitation="--copies greater than 1 is not supported; duplicate the pages with a PDF tool afterwards"),
    # --- outline ------------------------------------------------------------
    Flag("--outline", "Put an outline into the pdf (default)", "outline"),
    Flag("--no-outline", "Do not put an outline into the pdf", "outline"),
    Flag("--outline-depth", "Set the depth of the outline (default 4)", "outline", metavar="<level>"),
    Flag("--dump-outline", "Dump the outline to a file", "outline", metavar="<file>",
         support=UNSUPPORTED,
         limitation="--dump-outline is not implemented; the outline itself is written into the PDF"),
    # --- page ---------------------------------------------------------------
    Flag("--page-size", "Set paper size to: A4, Letter, etc. (default A4)", "page", metavar="<Size>",
         short="-s"),
    Flag("--page-width", "Page width", "page", metavar="<unitreal>"),
    Flag("--page-height", "Page height", "page", metavar="<unitreal>"),
    Flag("--orientation", "Set orientation to Landscape or Portrait (default Portrait)", "page",
         metavar="<orientation>", short="-O"),
    Flag("--grayscale", "PDF will be generated in grayscale", "page", short="-g"),
    Flag("--image-dpi", "When embedding images scale them down to this dpi (default 600)", "page",
         metavar="<integer>", support=DEFAULT_ONLY, default="600",
         limitation="--image-dpi is not honoured; images are placed at the size their CSS asks for"),
    Flag("--image-quality", "When jpeg compressing images use this quality (default 94)", "page",
         metavar="<integer>", support=DEFAULT_ONLY, default="94",
         limitation="--image-quality is not honoured; images keep their original encoding"),
    Flag("--viewport-size", "Force viewport size for all pages", "page", metavar="<size>",
         support=UNSUPPORTED, limitation="there is no screen viewport; the page box is the layout box"),
    # --- margins ------------------------------------------------------------
    Flag("--margin-unit", "Allowed units are mm, cm, inch, pt, px (default mm)", "page",
         metavar="<unit>"),
    Flag("--margin", "Set the page margins (default 10mm)", "page", metavar="<unitreal>",
         short="-m"),
    Flag("--margin-top", "Set the page top margin (default 10mm)", "page", metavar="<unitreal>",
         short="-T"),
    Flag("--margin-right", "Set the page right margin (default 10mm)", "page", metavar="<unitreal>",
         short="-R"),
    Flag("--margin-bottom", "Set the page bottom margin (default 10mm)", "page", metavar="<unitreal>",
         short="-B"),
    Flag("--margin-left", "Set the page left margin (default 10mm)", "page", metavar="<unitreal>",
         short="-L"),
    # --- headers and footers ------------------------------------------------
    Flag("--header-html", "Adds a html header", "header-and-footer", metavar="<url>"),
    Flag("--footer-html", "Adds a html footer", "header-and-footer", metavar="<url>"),
    Flag("--header-left", "Left aligned header text", "header-and-footer", metavar="<text>"),
    Flag("--header-center", "Centered header text", "header-and-footer", metavar="<text>"),
    Flag("--header-right", "Right aligned header text", "header-and-footer", metavar="<text>"),
    Flag("--footer-left", "Left aligned footer text", "header-and-footer", metavar="<text>"),
    Flag("--footer-center", "Centered footer text", "header-and-footer", metavar="<text>"),
    Flag("--footer-right", "Right aligned footer text", "header-and-footer", metavar="<text>"),
    Flag("--header-spacing", "Spacing between header and content in mm (default 0)",
         "header-and-footer", metavar="<real>"),
    Flag("--footer-spacing", "Spacing between footer and content in mm (default 0)",
         "header-and-footer", metavar="<real>"),
    Flag("--header-line", "Display line below the header", "header-and-footer"),
    Flag("--no-header-line", "Do not display line below the header (default)", "header-and-footer",
         support=INHERENT),
    Flag("--footer-line", "Display line above the footer", "header-and-footer"),
    Flag("--no-footer-line", "Do not display line above the footer (default)", "header-and-footer",
         support=INHERENT),
    Flag("--header-font-name", "Set header font name (default Arial)", "header-and-footer",
         metavar="<name>"),
    Flag("--header-font-size", "Set header font size (default 12)", "header-and-footer",
         metavar="<size>"),
    Flag("--header-font-color", "Set header font color (default #000000)", "header-and-footer",
         metavar="<color>"),
    Flag("--footer-font-name", "Set footer font name (default Arial)", "header-and-footer",
         metavar="<name>"),
    Flag("--footer-font-size", "Set footer font size (default 12)", "header-and-footer",
         metavar="<size>"),
    Flag("--footer-font-color", "Set footer font color (default #000000)", "header-and-footer",
         metavar="<color>"),
    # --- documents ----------------------------------------------------------
    Flag("--cover", "Add a cover document, without the header or footer of the page document",
         "documents", metavar="<path|url>"),
    Flag("--toc", "Add a table of contents document", "documents", support=UNSUPPORTED,
         limitation="table-of-contents documents are not supported in v1"),
]

GROUPS = ("global", "outline", "page", "header-and-footer", "documents")

BY_OPTION: Dict[str, Flag] = {}
for _flag in FLAGS:
    for _option in _flag.option_strings:
        BY_OPTION[_option] = _flag
del _flag, _option

# The flags that draw into the page margins. A cover document gets its own copy
# of them and none from the page document, which is what makes it a cover.
BAND_OPTIONS = frozenset(flag.dest for flag in FLAGS if flag.group == "header-and-footer")

_MARGIN_UNITS = {"mm": "mm", "cm": "cm", "in": "in", "inch": "in", "pt": "pt", "px": "px"}


class ArgumentParser(argparse.ArgumentParser):
    """argparse, but a usage error exits 1 and reads like wkhtmltopdf."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog=prog, add_help=False, allow_abbrev=False)
        self.add_argument("-h", "--help", action="store_true", dest="help")
        self.add_argument("-V", "--version", action="store_true", dest="version")
        for flag in FLAGS:
            kwargs: Dict[str, object] = {"dest": flag.dest, "default": None}
            if flag.is_boolean:
                kwargs["action"] = "store_true"
            else:
                kwargs["metavar"] = flag.metavar
                if flag.name == "--cookie":
                    kwargs["nargs"] = 2
            self.add_argument(*flag.option_strings, **kwargs)
        # Both positionals are optional at parse time so --help and --version
        # work on their own; run() checks that a pair was actually given.
        self.add_argument("input", nargs="?", metavar="<input>")
        self.add_argument("output", nargs="?", metavar="<output>")

    def error(self, message: str) -> "NoReturn":  # type: ignore[name-defined] # noqa: F821
        raise ShimError(_usage_error(self.prog, message))


def _usage_error(prog: str, message: str) -> str:
    """argparse's wording is its own; wkhtmltopdf's is shorter."""
    if "unrecognized arguments" in message:
        unknown = message.split(":", 1)[1].strip().split(" ")[0]
        kind = "option" if unknown.startswith("-") else "argument"
        return f"unrecognized {kind} '{unknown.lstrip('-')}' - try '{prog} --help'"
    missing_value = re.search(r"argument (\S+?):", message)
    if missing_value and "expected one argument" in message:
        return f"option '{missing_value.group(1).split('/')[0]}' requires a value"
    return f"{message} - try '{prog} --help'"


def expand_options_files(argv: Sequence[str]) -> List[str]:
    """Splice ``--options-file`` contents into the argument list, as upstream does."""
    argv = list(argv)
    if "--options-file" not in argv and not any(a.startswith("--options-file=") for a in argv):
        return argv

    out: List[str] = []
    index = 0
    while index < len(argv):
        option = argv[index]
        path = None
        if option == "--options-file":
            if index + 1 >= len(argv):
                raise ShimError("option '--options-file' requires a value")
            path, index = argv[index + 1], index + 2
        elif option.startswith("--options-file="):
            path, index = option.split("=", 1)[1], index + 1
        else:
            out.append(option)
            index += 1
            continue
        out.extend(_read_options_file(path))
    return out


def _read_options_file(path: str) -> List[str]:
    text = read_resource(path, os.getcwd()).decode("utf-8", "replace")
    # A comment is "#" at the head of a line or after whitespace; requiring the
    # whitespace first turned every full-line comment into three stray arguments.
    lines = [re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines()]
    words = [word for line in lines for word in shlex.split(line) if word]
    if any(word == "--options-file" or word.startswith("--options-file=") for word in words):
        raise ShimError("nested --options-file is not supported")
    return words


def _same_value(value: object, default: Optional[str]) -> bool:
    if str(value).strip() == str(default).strip():
        return True
    try:
        return float(value) == float(default)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


# The flags whose value the job reads back as a plain number. Lengths are not
# among them: ``--margin 2cm`` carries its own unit and parse_length is the one
# that says whether it is a length. Keyed by dest, and whether it has to be a
# whole one.
_NUMERIC_OPTIONS = {
    "outline_depth": True,
    "header_font_size": False,
    "footer_font_size": False,
}


def _number(value: object, option: str, whole: bool = False) -> float:
    """A flag value the engine needs as a number, refused by name when it is not one."""
    kind, example = ("a whole number", "4") if whole else ("a number", "12")
    try:
        return int(str(value).strip()) if whole else float(str(value).strip())
    except ValueError:
        raise ShimError(f"option '{option}' takes {kind}, e.g. {example}, not '{value}'") from None


def check_limitations(ns: argparse.Namespace) -> None:
    """Refuse what cannot be done, before anything is read from disk."""
    for flag in FLAGS:
        value = getattr(ns, flag.dest, None)
        if value is None or value is False:
            continue
        if flag.support is UNSUPPORTED:
            raise ShimError(f"option '{flag.name}' is not supported: {flag.limitation}")
        if flag.support is DEFAULT_ONLY and not _same_value(value, flag.default):
            raise ShimError(f"option '{flag.name}' is not supported: {flag.limitation}")
        if flag.dest in _NUMERIC_OPTIONS:
            _number(value, flag.name, _NUMERIC_OPTIONS[flag.dest])


def _get(ns: argparse.Namespace, name: str) -> Optional[object]:
    return getattr(ns, name.replace("-", "_"), None)


def _lookup_option(name: str) -> Optional[Flag]:
    """A flag named the way a command line or an options object would name it."""
    for candidate in (name, "--" + name, "-" + name):
        flag = BY_OPTION.get(candidate)
        if flag is not None:
            return flag
    return None


def namespace_from_options(options: Mapping[str, object]) -> argparse.Namespace:
    """The namespace a set of command-line flags would have produced.

    Keys are the flag names spelled with or without their leading dashes, which
    is the same shape as ``pdfkit``'s options dict and lets a conversion move
    between the two without a translation table.
    """
    ns = argparse.Namespace(input=None, output=None)
    for flag in FLAGS:
        setattr(ns, flag.dest, None)
    for key, value in options.items():
        flag = _lookup_option(str(key).strip())
        if flag is None:
            raise ShimError(f"unrecognized option '{key}'")
        if value is None or value is False:
            continue
        setattr(ns, flag.dest, True if flag.is_boolean else str(value))
    return ns


def without_bands(ns: argparse.Namespace) -> argparse.Namespace:
    """The same options minus every header and footer flag: a cover's namespace."""
    for dest in BAND_OPTIONS:
        setattr(ns, dest, None)
    return ns


# The flags that name a page box. Their absence means the defaults, which a
# document carrying its own ``@page`` should not be made to fight.
GEOMETRY_OPTIONS = (
    "page-size", "page-width", "page-height", "orientation",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "margin-unit",
)


def geometry_given(ns: argparse.Namespace) -> bool:
    """Whether the command line named a page box, rather than leaving it to the defaults."""
    return any(_get(ns, name) is not None for name in GEOMETRY_OPTIONS)


def read_option(uri: str, base_dir: str, encoding: str) -> str:
    """A file named on the command line: relative to the shell first, then the document.

    People type these paths next to the input file, and the two are usually in
    different directories once a template library has written the input out.
    """
    for directory in (os.getcwd(), base_dir):
        try:
            return read_resource(uri, directory).decode(encoding, "replace")
        except ShimError:
            continue
    raise ShimError(f"cannot read '{uri}'")


def margin_unit(ns: argparse.Namespace) -> str:
    unit = str(_get(ns, "margin-unit") or "mm").lower()
    if unit not in _MARGIN_UNITS:
        raise ShimError(f"unknown margin unit '{unit}', expected one of mm, cm, inch, pt, px")
    return _MARGIN_UNITS[unit]


def _band(ns: argparse.Namespace, kind: str, unit: str, ctx: Dict[str, object], notes: List[str]) -> Optional[Band]:
    side_of_margin = "top" if kind == "header" else "bottom"
    html_value = _get(ns, f"{kind}-html")
    texts = {side: _get(ns, f"{kind}-{side}") for side in ("left", "center", "right")}
    line = bool(_get(ns, f"{kind}-line"))
    if html_value is None and not any(texts.values()) and not line:
        return None

    spacing_value = _get(ns, f"{kind}-spacing")
    spacing = parse_length(spacing_value, unit) if spacing_value is not None else 0.0
    if spacing < 0:
        raise ShimError(f"option '--{kind}-spacing' cannot be negative: the band would leave its margin")
    margin_value = _get(ns, f"margin-{side_of_margin}")
    all_sides = _get(ns, "margin")
    if margin_value is not None:
        margin = parse_length(margin_value, unit)
    elif all_sides is not None:
        margin = parse_length(all_sides, unit)
    else:
        margin = DEFAULT_BAND_DEPTH + spacing

    band = Band(margin=margin, spacing=spacing, line=line)
    if html_value is not None:
        raw = read_option(str(html_value), str(ctx["base_dir"]), str(ctx["encoding"]))
        styles, body = extract_fragment(raw)
        band.html = templating.substitute(body, ctx, notes=notes)
        band.css = styles
    for side, text in texts.items():
        if text is not None:
            setattr(band, side, templating.substitute(str(text), ctx, escape=True, notes=notes))

    for attribute, option in (("font_name", "font-name"), ("font_size", "font-size"), ("font_color", "font-color")):
        value = _get(ns, f"{kind}-{option}")
        if value is not None:
            setattr(band, attribute, _number(value, f"--{kind}-{option}") if attribute == "font_size" else str(value))

    if band.depth <= 0:
        raise ShimError(
            f"--{kind}-spacing leaves no room for the {kind}: set --margin-{side_of_margin} "
            "to more than the spacing"
        )
    return band


def _check_page_box(width: float, height: float, margins: Tuple[float, float, float, float]) -> None:
    """Refuse a page the engine cannot lay out, before it lays out anything.

    A box with no room inside it does not come back as a blank page: the frame
    geometry goes negative, ReportLab shouts about ``@frame`` definitions on
    stderr, and the PDF it writes has content sitting outside the media box.
    Better to name the flag that did it.
    """
    top, right, bottom, left = margins
    for side, value in (("top", top), ("right", right), ("bottom", bottom), ("left", left)):
        if value < 0:
            raise ShimError(f"the {side} margin is negative: margins are measured inwards from the page edge")

    if width <= 0 or height <= 0:
        raise ShimError(
            f"the page box is {width:.2f}pt x {height:.2f}pt: --page-width and --page-height must both be positive"
        )
    content_width, content_height = width - left - right, height - top - bottom
    if content_width <= 0 or content_height <= 0:
        raise ShimError(
            f"the margins leave {content_width:.2f}pt x {content_height:.2f}pt for the content: "
            "reduce the margins or choose a larger page"
        )


def build_job(ns: argparse.Namespace, document: Optional[bytes] = None) -> Job:
    """Translate parsed options into a render job.

    ``document`` is the markup when it is not something the job can read from
    disk by itself: standard input in the CLI's case is read through
    ``ns.input == "-"``, and the conversion service hands the body straight over.
    """
    notes: List[str] = []
    encoding = str(_get(ns, "encoding") or "utf-8")
    unit = margin_unit(ns)

    if document is not None:
        data, source = document, str(ns.input or "<request>")
        base_dir = _base_dir(source)
    elif ns.input == "-":
        data, source, base_dir = sys.stdin.buffer.read(), "<stdin>", os.getcwd()
    else:
        data, source, base_dir = read_resource(ns.input, os.getcwd()), ns.input, _base_dir(ns.input)
    html = data.decode(encoding, "replace")

    width, height = page_size(str(_get(ns, "page-size") or "A4"))
    if _get(ns, "page-width") is not None:
        width = parse_length(_get(ns, "page-width"), unit)
    if _get(ns, "page-height") is not None:
        height = parse_length(_get(ns, "page-height"), unit)
    width, height = apply_orientation((width, height), str(_get(ns, "orientation") or "Portrait"))

    def margin(name: str) -> float:
        value = _get(ns, name)
        if value is None:
            value = _get(ns, "margin")
        return parse_length(value, unit) if value is not None else DEFAULT_MARGIN

    margins = (margin("margin-top"), margin("margin-right"), margin("margin-bottom"), margin("margin-left"))
    _check_page_box(width, height, margins)

    ctx: Dict[str, object] = {
        "now": datetime.now().astimezone(),
        "title": str(_get(ns, "title") or ""),
        "url": source,
        "base_dir": base_dir,
        "encoding": encoding,
        "notes": notes,
    }

    stylesheet = ""
    if _get(ns, "user-style-sheet") is not None:
        stylesheet = read_option(str(_get(ns, "user-style-sheet")), base_dir, encoding)

    depth = _get(ns, "outline-depth")
    return Job(
        html=html,
        source=source,
        base_dir=base_dir,
        page_width=width,
        page_height=height,
        margins=margins,
        header=_band(ns, "header", unit, ctx, notes),
        footer=_band(ns, "footer", unit, ctx, notes),
        title=_get(ns, "title"),
        outline=not _get(ns, "no-outline"),
        outline_depth=_number(depth, "--outline-depth", whole=True) if depth is not None else None,
        grayscale=bool(_get(ns, "grayscale")),
        stylesheet=stylesheet,
        log_path=str(_get(ns, "log-path")) if _get(ns, "log-path") is not None else None,
        quiet=bool(_get(ns, "quiet")),
        confine_local_files=bool(_get(ns, "disable-local-file-access")),
        notes=notes,
    )


def _base_dir(source: str) -> str:
    if "://" in source:
        return os.getcwd()
    return os.path.dirname(os.path.abspath(source))

