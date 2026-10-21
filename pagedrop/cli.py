"""The ``wkhtmltopdf`` command line.

The help page is generated from the flag table, so what a user reads and what
the parser accepts are the same list.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional, Sequence

from . import engine, flags
from .errors import ShimError
from .spec import Job

GROUP_TITLES = {
    "global": "Global Options",
    "outline": "Outline Options",
    "page": "Page Options",
    "header-and-footer": "Headers And Footer Options",
    "documents": "Documents",
}

VARIABLES = (
    "[page] [frompage] [topage] [date] [isodate] [time] [timestamp] [year] "
    "[month] [day] [title] [doctitle] [url] [webpage] [section] [subsection]"
)

# The engine logs under "xhtml2pdf.*", and the root logger only keeps
# warnings, so a level of its own is needed for anything else.
LOG_LEVELS = {
    "none": logging.CRITICAL + 10,
    "info": logging.INFO,
    "error": logging.ERROR,
}


class _ConsoleHandler(logging.StreamHandler):
    """The engine log on stderr, replaced on every run so it follows stderr."""

    pagedrop_console = True


def engine_version() -> str:
    try:
        from importlib.metadata import version

        return version("xhtml2pdf")
    except Exception:  # noqa: BLE001 - the version line must never fail
        return "unknown"


def version_text(prog: str) -> str:
    from . import __version__

    return f"{prog} {__version__} (pagedrop shim, engine xhtml2pdf {engine_version()})"


def help_text(prog: str) -> str:
    lines: List[str] = [
        "Name",
        f"  {prog} - convert HTML documents to PDF",
        "",
        "Synopsis",
        f"  {prog} [GLOBAL FLAG] [INPUT] [OUTPUT]",
        "",
        "Description",
        "  A drop-in replacement for the archived wkhtmltopdf. It takes the flags",
        "  conversion scripts already pass and renders the document with a",
        "  maintained print engine that installs from pip alone. Options that",
        "  cannot be honoured are refused with an explanation, never ignored.",
        "  Use '-' for INPUT or OUTPUT to read or write the document on a pipe.",
        "",
    ]
    for group in flags.GROUPS:
        table = [flag for flag in flags.FLAGS if flag.group == group]
        if not table:
            continue
        lines.append(GROUP_TITLES[group] + ":")
        lines.extend(flag.help_line() for flag in table)
        lines.append("")

    for title, level in (
        ("Refused, with an explanation:", flags.UNSUPPORTED),
        ("Accepted only at the value wkhtmltopdf defaults to:", flags.DEFAULT_ONLY),
    ):
        names = [f.name for f in flags.FLAGS if f.support == level]
        lines.append(title)
        for index in range(0, len(names), 6):
            lines.append("  " + ", ".join(names[index : index + 6]))
    lines += [
        "",
        "Variables:",
        "  Header and footer text and HTML expand these, the way wkhtmltopdf does:",
        f"  {VARIABLES}",
        "",
        "Exit codes:",
        "  0  the PDF was written",
        "  1  the arguments were refused, or the document could not be rendered",
        "",
        "See also:",
        "  https://github.com/intertermux-code/pagedrop",
        "",
    ]
    return "\n".join(lines)


def _configure_logging(ns: argparse.Namespace) -> None:
    levels = []
    if getattr(ns, "quiet", None):
        levels.append(LOG_LEVELS["error"])
    requested = getattr(ns, "log_level", None)
    if requested is not None:
        name = str(requested).lower()
        if name not in LOG_LEVELS:
            raise ShimError(
                f"unknown log level '{requested}', expected one of "
                + ", ".join(LOG_LEVELS)
            )
        levels.append(LOG_LEVELS[name])

    logger = logging.getLogger("xhtml2pdf")
    for handler in list(logger.handlers):
        if isinstance(handler, _ConsoleHandler):
            logger.removeHandler(handler)
    if levels:
        logger.setLevel(max(levels))  # the quieter of the two wins
        console = _ConsoleHandler(sys.stderr)
        console.setLevel(logger.level)
        logger.addHandler(console)
        logger.propagate = False
    else:
        logger.setLevel(logging.WARNING)

    log_path = getattr(ns, "log_path", None)
    if log_path:
        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)


def _write_output(path: str, data: bytes) -> None:
    if path == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def report(note: str, prog: str, log_path: Optional[str] = None) -> None:
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(note + "\n")
    else:
        sys.stderr.write(f"{prog}: {note}\n")


def run(argv: Sequence[str], prog: str) -> Job:
    """Parse, translate, render. Raises ShimError for anything refused."""
    parser = flags.ArgumentParser(prog)
    ns = parser.parse_args(flags.expand_options_files(list(argv)))
    if getattr(ns, "help", False):
        sys.stdout.write(help_text(prog))
        raise SystemExit(0)
    if getattr(ns, "version", False):
        sys.stdout.write(version_text(prog) + "\n")
        raise SystemExit(0)

    if not ns.input or not ns.output:
        raise ShimError(f"missing <input> and <output> arguments - try '{prog} --help'")

    _configure_logging(ns)
    flags.check_limitations(ns)
    job = flags.build_job(ns)
    data = engine.render(job)
    _write_output(ns.output, data)
    return job


def _prog_name() -> str:
    name = os.path.basename(sys.argv[0])
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    if name.startswith("__main__"):  # python -m pagedrop
        return __package__ or "wkhtmltopdf"
    return name or "wkhtmltopdf"


def main(argv: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> int:
    prog = prog or _prog_name()
    try:
        job = run(list(sys.argv[1:] if argv is None else argv), prog)
    except ShimError as error:
        sys.stderr.write(f"{prog}: {error}\n")
        return 1
    except SystemExit:
        return 0
    if not job.quiet:
        for note in job.notes:
            report(note, prog, job.log_path)
    return 0
