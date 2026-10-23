"""Cover pages, checked on the PDF that comes out of the other end."""

import io
import re

import pytest
from pypdf import PdfReader

from pagedrop import cli

COVER = """<html><head><style>@page { size: 200mm 280mm; margin: 0 }</style></head>
<body><h1>Annual Report Cover</h1><p>Cover only wording</p></body></html>"""

BODY = "<html><body><h1>The Report</h1>{}</body></html>".format(
    "".join(f"<p>Body paragraph {i}, long enough to take up a reasonable amount of the page.</p>" for i in range(40))
)


@pytest.fixture
def documents(tmp_path):
    cover = tmp_path / "cover.html"
    cover.write_text(COVER, encoding="utf-8")
    body = tmp_path / "body.html"
    body.write_text(BODY, encoding="utf-8")
    return cover, body


def run(*argv) -> int:
    return cli.main([str(arg) for arg in argv], prog="wkhtmltopdf")


def read(path) -> PdfReader:
    return PdfReader(io.BytesIO(path.read_bytes()))


def text(page) -> str:
    return (page.extract_text() or "").replace("\n", " ")


def box(page):
    return (float(page.mediabox.width), float(page.mediabox.height))


def test_the_cover_pages_come_first_and_the_document_follows(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out) == 0

    rendered = read(out).pages
    assert len(rendered) == 2, "one cover page, then the document"
    assert "Annual Report Cover" in text(rendered[0])
    assert "Body paragraph 0" not in text(rendered[0])
    assert "The Report" in text(rendered[1])
    assert "Cover only wording" not in text(rendered[1])


def test_the_document_bands_do_not_leak_onto_the_cover(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out, "--margin-top", "30mm", "--margin-bottom", "30mm",
               "--header-left", "ACME Brand", "--footer-center", "Page [page] of [topage]") == 0

    rendered = read(out).pages
    assert "ACME Brand" not in text(rendered[0])
    assert "Page 1 of" not in text(rendered[0])
    assert "ACME Brand" in text(rendered[1])
    assert "Page 1 of %d" % (len(rendered) - 1) in text(rendered[1]), "the document counts its own pages"
    assert f"Page {len(rendered) - 1} of {len(rendered) - 1}" in text(rendered[-1])


def test_a_cover_keeps_the_page_it_asked_for(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out) == 0

    rendered = read(out).pages
    assert box(rendered[0]) == pytest.approx((566.93, 793.70), abs=0.01)  # the cover's own 200mm x 280mm
    assert box(rendered[1]) == pytest.approx((595.28, 841.89))  # the document takes the default page


def test_a_page_given_to_the_whole_run_overrides_the_cover(tmp_path, documents):
    """An explicit page is an instruction, so it outranks the cover's own stylesheet."""
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out, "--page-size", "Letter") == 0

    rendered = read(out).pages
    assert box(rendered[0]) == pytest.approx((612.0, 792.0))
    assert box(rendered[1]) == pytest.approx((612.0, 792.0))


def test_a_cover_can_be_given_its_own_page_on_the_command_line(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, "--page-size", "A5", body, out) == 0

    rendered = read(out).pages
    assert box(rendered[0]) == pytest.approx((419.53, 595.28))
    assert box(rendered[1]) == pytest.approx((595.28, 841.89))


def test_a_cover_can_be_given_a_band_of_its_own(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, "--margin-top", "30mm", "--page-size", "A4",
               "--header-center", "Cover Header", body, out,
               "--header-center", "Document Header") == 0

    rendered = read(out).pages
    assert "Cover Header" in text(rendered[0])
    assert "Document Header" in text(rendered[1])
    assert "Document Header" not in text(rendered[0])


def test_the_cover_flag_takes_the_same_document(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("--cover", cover, body, out) == 0

    rendered = read(out).pages
    assert "Annual Report Cover" in text(rendered[0])
    assert "The Report" in text(rendered[1])


def test_title_and_outline_survive_the_join(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out, "--title", "Board Pack", "--outline") == 0

    reader = read(out)
    assert reader.metadata.title == "Board Pack"
    assert reader.outline, "the document's bookmarks are still there after the join"


def test_grayscale_applies_to_the_whole_run(tmp_path, documents):
    cover, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", cover, body, out, "--grayscale") == 0
    streams = b"".join(
        page.get_contents().get_data() for page in read(out).pages if page.get_contents() is not None
    )
    assert not re.findall(rb"\d*\.?\d+ \d*\.?\d+ \d*\.?\d+ rg", streams)


def test_a_cover_that_is_not_there_exits_cleanly(tmp_path, documents, capsys):
    _, body = documents
    out = tmp_path / "merged.pdf"
    assert run("cover", tmp_path / "gone.html", body, out) == 1
    error = capsys.readouterr().err
    assert "cannot read" in error
    assert "Traceback" not in error
    assert not out.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["cover"],
        ["cover", "only-one.html"],
        ["cover", "a.html", "b.html"],
        ["cover", "a.html", "b.html", "c.pdf", "extra.pdf"],
    ],
)
def test_the_cover_command_wants_three_paths(tmp_path, argv, capsys):
    assert run(*argv) == 1
    assert "takes <cover>, <input> and <output>" in capsys.readouterr().err


def test_an_unknown_option_on_a_cover_is_named(tmp_path, documents, capsys):
    cover, body = documents
    assert run("cover", cover, "--nonsense-flag", body, tmp_path / "out.pdf") == 1
    assert "unrecognized option 'nonsense-flag'" in capsys.readouterr().err


def test_a_cover_refuses_an_option_the_engine_cannot_honour(tmp_path, documents, capsys):
    cover, body = documents
    assert run("cover", cover, body, tmp_path / "out.pdf", "--javascript-delay", "500") == 1
    assert "no JavaScript" in capsys.readouterr().err


def test_cover_and_cover_flag_do_not_both_claim_the_page(tmp_path, documents, capsys):
    cover, body = documents
    assert run("cover", cover, body, tmp_path / "out.pdf", "--cover", cover) == 1
    assert "already names one" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["cover", "--help"], ["cover", "-h"], ["cover", "a.html", "b.html", "out.pdf", "--help"]],
)
def test_the_cover_command_answers_help_wherever_the_flag_sits(argv, capsys):
    assert run(*argv) == 0
    assert "wkhtmltopdf cover [GLOBAL FLAG] <cover> <input> <output> [FLAG]" in capsys.readouterr().out


def test_the_cover_command_names_the_engine_it_renders_with(capsys):
    assert run("cover", "--version") == 0
    assert "engine xhtml2pdf" in capsys.readouterr().out


def test_a_bare_cover_still_gets_its_own_page_box(tmp_path, capsys):
    """No @page in the cover: the flags the command line gave it govern."""
    cover = tmp_path / "plain-cover.html"
    cover.write_text("<html><body><h1>Plain Cover</h1></body></html>", encoding="utf-8")
    body = tmp_path / "body.html"
    body.write_text("<html><body><p>Body</p></body></html>", encoding="utf-8")
    out = tmp_path / "merged.pdf"

    assert run("cover", cover, "--page-size", "A5", body, out) == 0
    rendered = read(out).pages
    assert box(rendered[0]) == pytest.approx((419.53, 595.28))
    assert box(rendered[1]) == pytest.approx((595.28, 841.89))
