"""Cover documents: the leading page or two, with its own page settings.

wkhtmltopdf has always taken a cover as an object of its own, and the reason
matters here. A cover is laid out on its own paper, is numbered separately and,
above all, carries none of the running header or footer of the report it
fronts. Rendering it as a second document and stitching the two PDFs together
is what makes all three of those hold, rather than one document whose first
pages are made to look different by a stylesheet.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import engine, flags
from .errors import ShimError
from .resources import write_output
from .spec import Job

KEYWORD = "cover"

# -h/--help/-V/--version are added by the parser itself, not by the flag table.
PSEUDO_OPTIONS = ("-h", "--help", "-V", "--version")

# The one flag whose value is two words. It is refused either way, but splitting
# the command line must not mistake its arguments for paths.
_EXTRA_VALUES = {"--cookie": 2}


@dataclass
class Command:
    """``[GLOBAL FLAG] COVER [FLAG] INPUT [FLAG] OUTPUT [GLOBAL FLAG]``."""

    global_options: List[str] = field(default_factory=list)
    cover: str = ""
    cover_options: List[str] = field(default_factory=list)
    document: str = ""
    document_options: List[str] = field(default_factory=list)
    output: str = ""


def _is_option(token: str) -> bool:
    return token.startswith("-") and len(token) > 1


def _option_words(argv: Sequence[str], index: int, prog: str) -> Tuple[List[str], int]:
    """An option and the arguments that belong to it, plus the index after them."""
    token = argv[index]
    if "=" in token or token in PSEUDO_OPTIONS:
        return [token], index + 1

    flag = flags.BY_OPTION.get(token)
    if flag is None:
        raise ShimError(f"unrecognized option '{token.lstrip('-')}' - try '{prog} {KEYWORD} --help'")
    count = _EXTRA_VALUES.get(token, 0 if flag.is_boolean else 1)
    if index + count >= len(argv):
        raise ShimError(f"option '{token}' requires a value")
    return list(argv[index : index + count + 1]), index + count + 1


def parse(argv: Sequence[str], prog: str = KEYWORD) -> Command:
    """Split a cover command line into the two documents it describes.

    Options attach to the object they follow, the way wkhtmltopdf spells local
    options. The flags before the cover and the ones after the output are
    global, because there is no object for them to belong to: a flat command
    line has always let people put them last, and ``--grayscale`` at the end of
    a cover run means the whole run, not the last document of it. ``--help``
    and ``--version`` are global wherever they appear, since they ask about the
    command rather than about one of its documents.
    """
    command = Command()
    paths: List[str] = []

    def bucket() -> List[str]:
        if not paths or len(paths) >= 3:
            return command.global_options
        return command.cover_options if len(paths) == 1 else command.document_options

    index = 0
    while index < len(argv):
        token = argv[index]
        if _is_option(token):
            words, index = _option_words(argv, index, prog)
            # Asking for help is about the command, not about whichever object
            # the flag happened to follow.
            (command.global_options if token in PSEUDO_OPTIONS else bucket()).extend(words)
            continue
        paths.append(token)
        index += 1

    asked = any(word in PSEUDO_OPTIONS for word in command.global_options)
    if len(paths) != 3 and not asked:
        raise ShimError(f"'{KEYWORD}' takes <cover>, <input> and <output>, not {len(paths)} path(s)")
    # A help request is answered before the arguments are looked at, so it is
    # not held to their number.
    command.cover, command.document, command.output = (list(paths) + ["", "", ""])[:3]
    return command


def _names_bands(options: Sequence[str]) -> bool:
    """Whether a cover was given a header or footer of its own."""
    for word in options:
        flag = flags.BY_OPTION.get(word.split("=", 1)[0])
        if flag is not None and flag.group == "header-and-footer":
            return True
    return False


def cover_job(ns: argparse.Namespace, source: str, document: Optional[bytes] = None,
              own_bands: bool = False) -> Job:
    """A copy of the page document's options, aimed at ``source``, band-free.

    ``own_bands`` says the cover was given a header or footer on the command
    line; short of that the running bands stay with the document they were
    written for. A cover that names its own page box keeps it: the shim's
    defaults are a fallback, not an instruction to argue with the stylesheet.
    Giving the cover a band is the end of that argument, because a band is
    placed in a page margin, and only the shim knows the margin it was drawn
    from once its own ``@page`` rules are in play.
    """
    cover_ns = argparse.Namespace(**vars(ns))
    if not own_bands:
        flags.without_bands(cover_ns)
    cover_ns.input, cover_ns.output, cover_ns.cover = source, None, None
    job = flags.build_job(cover_ns, document=document)
    job.own_page = (
        not flags.geometry_given(ns)
        and engine.declares_page(job.html)
        and not any(band is not None and band.wanted for band in (job.header, job.footer))
    )
    return job


def render(jobs: Sequence[Job]) -> bytes:
    """Every document in turn, concatenated into one PDF."""
    rendered = [engine.render(job) for job in jobs]
    if len(rendered) == 1:
        return rendered[0]

    from pypdf import PdfWriter  # imported late so --help stays instant

    writer = PdfWriter()
    for data in rendered:
        writer.append(io.BytesIO(data), import_outline=True)

    title = str(jobs[-1].title or "")
    if title:
        # The last document is the one being titled; the cover only fronts it.
        writer.add_metadata({"/Title": title})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def jobs_for(ns: argparse.Namespace) -> List[Job]:
    """The document the flags describe, with the cover named by ``--cover`` in front."""
    document = flags.build_job(ns)
    if getattr(ns, "cover", None):
        return [cover_job(ns, str(ns.cover)), document]
    return [document]


def _namespace(options: List[str], source: str, prog: str) -> argparse.Namespace:
    ns = flags.ArgumentParser(prog).parse_args(flags.expand_options_files(options))
    ns.input, ns.output = source, None
    return ns


def run(argv: Sequence[str], prog: str) -> Job:
    """``pagedrop cover [GLOBAL FLAG] COVER [FLAG] INPUT [FLAG] OUTPUT [GLOBAL FLAG]``."""
    command = parse(argv, prog)
    document_ns = _namespace(command.global_options + command.document_options, command.document, prog)
    cover_ns = _namespace(command.global_options + command.cover_options, command.cover, prog)

    if getattr(document_ns, "help", False):
        # cli imports this module, so its help page is reached at call time.
        from . import cli

        sys.stdout.write(cli.help_text(f"{prog} {KEYWORD}", KEYWORD))
        raise SystemExit(0)
    if getattr(document_ns, "version", False):
        from . import cli

        sys.stdout.write(cli.version_text(prog) + "\n")
        raise SystemExit(0)
    if document_ns.cover or cover_ns.cover:
        raise ShimError(f"'--cover' is the flag for a cover; the '{KEYWORD}' command already names one")

    flags.check_limitations(cover_ns)
    flags.check_limitations(document_ns)

    cover = cover_job(cover_ns, command.cover, own_bands=_names_bands(command.cover_options))
    document = flags.build_job(document_ns)
    write_output(command.output, render([cover, document]))
    document.notes = cover.notes + document.notes
    return document
