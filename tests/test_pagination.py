"""The page model at its edges: one page, no pages, and pages that split.

Everything here is asserted on a PDF read back with ``pypdf``, because the
failure mode these cases have in common is a document that renders without
complaining and lies afterwards.
"""

import io
import re

import pytest
from pypdf import PdfReader

from pagedrop import engine, flags
from pagedrop.errors import ShimError

TALL = "<html><body><h1>Report</h1>{}</body></html>".format(
    "".join(f"<p>Line {i} of the report, long enough to fill a line of the page.</p>" for i in range(80))
)

ROWS = "".join(f"<tr><td>row{i}</td><td>{i * 7}</td></tr>" for i in range(150))


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "tall.html"
    path.write_text(TALL, encoding="utf-8")
    return path


def markup(tmp_path, text, name="doc.html"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def convert(document, *argv) -> bytes:
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([str(document), "out.pdf", *argv])
    flags.check_limitations(ns)
    return engine.render(flags.build_job(ns))


def pages(data):
    return PdfReader(io.BytesIO(data)).pages


def text_of(page) -> str:
    return (page.extract_text() or "").replace("\n", " ")


def numbered(*argv):
    return ("--margin-bottom", "25mm", "--footer-center", "Page [page] of [topage]", *argv)


def test_a_bare_fragment_reaches_the_page_it_is_printed_on(tmp_path):
    """A fragment with no <html> wrapper used to be thrown away by the injection."""
    document = markup(tmp_path, "<p>just a fragment, no document around it</p>")
    data = convert(document, *numbered())
    rendered = pages(data)
    assert len(rendered) == 1
    assert "just a fragment" in text_of(rendered[0])
    assert "Page 1 of 1" in text_of(rendered[0])


def test_a_backslash_in_a_title_or_a_band_is_only_a_character(tmp_path):
    """The generated markup is spliced in, never used as a substitution template."""
    document = markup(tmp_path, "<html><body><p>content</p></body></html>")
    data = convert(document, "--title", r"Pack \q 42", "--footer-left", r"copy\g<1>desk")
    assert PdfReader(io.BytesIO(data)).metadata.title == r"Pack \q 42"
    assert "copy\\g<1>desk" in text_of(pages(data)[0])


def test_one_page_documents_number_themselves_as_the_last(tmp_path):
    document = markup(tmp_path, "<html><body><p>Short and complete.</p></body></html>")
    data = convert(document, *numbered())
    rendered = pages(data)
    assert len(rendered) == 1
    assert "Page 1 of 1" in text_of(rendered[0])


@pytest.mark.parametrize(
    "body",
    ["<html><body></body></html>", "<body></body>", "", "<html><body><!-- nothing at all --></body></html>"],
)
def test_an_empty_document_is_still_a_valid_one_page_pdf(tmp_path, body):
    document = markup(tmp_path, body, name="empty.html")
    data = convert(document)
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(pages(data)) == 1


def test_an_empty_document_still_carries_its_header_and_footer(tmp_path):
    document = markup(tmp_path, "<html><head></head><body></body></html>")
    data = convert(document, "--margin-top", "30mm", "--header-left", "ACME", *numbered())
    rendered = pages(data)
    assert len(rendered) == 1
    assert "ACME" in text_of(rendered[0])
    assert "Page 1 of 1" in text_of(rendered[0])


def test_a_long_table_splits_between_rows_and_counts_its_pages(tmp_path):
    document = markup(tmp_path, f"<html><body><table border='1'>{ROWS}</table></body></html>")
    data = convert(document, *numbered())
    rendered = pages(data)
    assert len(rendered) > 2

    for number, page in enumerate(rendered, start=1):
        assert f"Page {number} of {len(rendered)}" in text_of(page)

    printed = " ".join(text_of(page) for page in rendered)
    for row in (0, 74, 149):
        assert f"row{row}" in printed


def test_a_split_in_the_middle_of_an_element_keeps_counting(tmp_path):
    """One paragraph longer than a page: the split is inside a single element."""
    document = markup(tmp_path, "<html><body><p>" + "filling the page with words. " * 900 + "</p></body></html>")
    data = convert(document, *numbered())
    rendered = pages(data)
    assert len(rendered) > 2
    for number, page in enumerate(rendered, start=1):
        assert f"Page {number} of {len(rendered)}" in text_of(page)


def test_a_line_too_wide_for_the_page_does_not_break_the_document(tmp_path):
    document = markup(tmp_path, "<html><body><p>" + "W" * 5000 + "</p></body></html>")
    assert len(pages(convert(document))) == 1


def test_the_bands_appear_on_the_first_page_and_the_last(source):
    data = convert(source, "--margin-top", "30mm", *numbered(), "--header-right", "Confidential")
    rendered = pages(data)
    assert len(rendered) > 2
    for page in (rendered[0], rendered[1], rendered[-1]):
        assert "Confidential" in text_of(page)
    assert "Page 1 of" in text_of(rendered[0])
    assert f"Page {len(rendered)} of {len(rendered)}" in text_of(rendered[-1])


def test_the_footer_sits_in_the_bottom_margin_not_over_the_content(source):
    plain = convert(source)
    with_footer = convert(source, *numbered())
    assert len(pages(with_footer)) > len(pages(plain)), "the band has to take room from the content"


@pytest.mark.parametrize(
    "argv",
    [
        ["--page-width", "0"],
        ["--page-height", "0"],
        ["--margin-left", "250mm"],
        ["--margin-top", "400mm"],
        ["--page-size", "210mmx297mm", "--margin", "110mm"],
    ],
)
def test_a_page_with_no_room_left_on_it_is_refused(source, argv):
    with pytest.raises(ShimError):
        convert(source, *argv)


@pytest.mark.parametrize("argv", [["--margin-top", "-20"], ["--margin", "-5"]])
def test_a_negative_margin_is_refused_rather_than_drawn_off_page(source, argv):
    with pytest.raises(ShimError, match="negative"):
        convert(source, *argv)


def test_a_negative_band_spacing_is_refused(source):
    with pytest.raises(ShimError, match="header-spacing"):
        convert(source, "--header-spacing", "-5", "--header-left", "H")


def test_the_page_box_is_measured_before_anything_is_rendered(tmp_path):
    """The refusal must not depend on the document being readable or even there."""
    document = markup(tmp_path, "<html><body><p>x</p></body></html>")
    with pytest.raises(ShimError, match="margins leave"):
        convert(document, "--margin-left", "300mm", "--header-html", str(tmp_path / "absent.html"))


def test_frame_geometry_stays_inside_the_page(source):
    job = flags.build_job(
        flags.ArgumentParser("p").parse_args([str(source), "out.pdf", "--margin-bottom", "40mm",
                                               "--footer-spacing", "10mm", "--footer-center", "Page [page]"])
    )
    css = engine.page_css(job)
    frame = re.search(r"@frame [^{]*\{([^}]*)\}", css).group(1)
    bottom = float(re.search(r"top: ([-\d.]+)pt", frame).group(1)) + float(re.search(r"height: ([-\d.]+)pt", frame).group(1))
    assert bottom <= job.page_height + 0.01
