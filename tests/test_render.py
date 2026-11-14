"""End-to-end rendering: the flags have to show up in the produced PDF."""

import io
import re

import pytest
from pypdf import PdfReader

from pagedrop import engine, flags

TALL = "<html><body><h1>Report</h1>{}</body></html>".format(
    "".join(f"<p>Line {i} of the report, long enough to fill a line of the page.</p>" for i in range(80))
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "tall.html"
    path.write_text(TALL, encoding="utf-8")
    return path


def pages_content(reader) -> bytes:
    return b"".join(
        page.get_contents().get_data() for page in reader.pages if page.get_contents() is not None
    )


def convert(source, *argv) -> bytes:
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([str(source), "out.pdf", *argv])
    flags.check_limitations(ns)
    return engine.render(flags.build_job(ns))


def pages(data):
    return PdfReader(io.BytesIO(data)).pages


def text_of(page) -> str:
    return page.extract_text() or ""


def supports_confinement() -> bool:
    """Older engine releases ignore resource policies; they cannot be confined."""
    try:
        import xhtml2pdf.config.resources as resources
    except ImportError:
        return False
    return hasattr(resources, "ResourceAccessPolicy")


def test_smoke_test_produces_a_real_pdf(source):
    data = convert(source)
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 2000
    assert len(pages(data)) >= 2


def test_page_numbers_are_per_page(source):
    data = convert(source, "--footer-center", "Page [page] of [topage]")
    text = [text_of(page) for page in pages(data)]
    assert re.search(r"Page 1 of %d" % len(text), text[0].replace("\n", " "))
    assert re.search(r"Page 2 of %d" % len(text), text[1].replace("\n", " "))


def test_header_and_footer_text_land_on_every_page(source):
    data = convert(source, "--margin-top", "30mm", "--margin-bottom", "30mm",
                   "--header-left", "ACME", "--header-right", "Confidential",
                   "--footer-center", "keep")
    for page in pages(data):
        text = text_of(page).replace("\n", " ")
        assert "ACME" in text and "Confidential" in text and "keep" in text


def test_header_html_lands_in_the_top_margin(source, tmp_path):
    band = tmp_path / "head.html"
    band.write_text(
        '<html><head><style>body{font-size:14pt}</style></head>'
        "<body><div>BANDCONTENT [title]</div></body></html>",
        encoding="utf-8",
    )
    data = convert(source, "--margin-top", "40mm", "--title", "7", "--header-html", str(band))
    rendered = pages(data)
    assert "BANDCONTENT 7" in text_of(rendered[0])
    assert "BANDCONTENT 7" in text_of(rendered[1])


def test_orientation_and_size_are_applied(source):
    data = convert(source, "--page-size", "A5", "--orientation", "landscape")
    box = pages(data)[0].mediabox
    assert (int(box.width), int(box.height)) == (595, 419)  # A5 turned sideways


def test_margins_move_the_content_box(source):
    narrow = convert(source, "--margin-left", "80mm", "--margin-right", "80mm")
    wide = convert(source, "--margin-left", "10mm", "--margin-right", "10mm")
    assert len(pages(narrow)) > len(pages(wide))


def test_title_becomes_pdf_metadata(source):
    data = convert(source, "--title", "Board Pack")
    assert PdfReader(io.BytesIO(data)).metadata.title == "Board Pack"


def test_document_title_is_used_when_no_flag_is_given(source):
    page = source.parent / "titled.html"
    page.write_text("<html><head><title>From The Head</title></head><body><p>x</p></body></html>", "utf-8")
    data = convert(page)
    assert PdfReader(io.BytesIO(data)).metadata.title == "From The Head"


def test_outline_is_written_when_asked(source):
    data = convert(source, "--outline")
    assert PdfReader(io.BytesIO(data)).outline


def test_no_outline_by_default_flag(source):
    data = convert(source, "--no-outline")
    assert not PdfReader(io.BytesIO(data)).outline


def test_grayscale_removes_rgb_operators(source):
    colored = source.parent / "colored.html"
    colored.write_text(
        '<html><body><p style="color: #ff0000; background:#00ff00">Red on green</p>'
        "<p>plain</p></body></html>",
        encoding="utf-8",
    )
    color = convert(colored)
    grey = convert(colored, "--grayscale")

    def rgb_operators(data):
        reader = PdfReader(io.BytesIO(data))
        found = []
        for page in reader.pages:
            content = page.get_contents()
            if content is not None:
                found += re.findall(rb"\d*\.?\d+ \d*\.?\d+ \d*\.?\d+ rg", content.get_data())
        return found

    def gray_operators(data):
        reader = PdfReader(io.BytesIO(data))
        return re.findall(rb"\d\.\d{4} [gG]\b", pages_content(reader))

    assert rgb_operators(color)
    assert not rgb_operators(grey)
    assert gray_operators(grey)
    assert grey.startswith(b"%PDF")
    assert "Red on green" in text_of(pages(grey)[0])


def test_encoding_flag_decodes_the_input(tmp_path):
    page = tmp_path / "latin.html"
    page.write_bytes("<html><body><p>Grüße, naïf</p></body></html>".encode("windows-1252"))
    data = convert(page, "--encoding", "windows-1252")
    assert "Grüße" in text_of(pages(data)[0])


def test_meta_charset_windows_1252_is_honoured(tmp_path):
    page = tmp_path / "meta.html"
    page.write_bytes(
        '<html><head><meta charset="windows-1252"><title>Test</title></head>'
        '<body><p>Grüße, naïf</p></body></html>'.encode("windows-1252")
    )
    data = convert(page)
    assert "Grüße" in text_of(pages(data)[0])
    assert "naïf" in text_of(pages(data)[0])


def test_meta_charset_latin_1_is_honoured(tmp_path):
    page = tmp_path / "meta.html"
    page.write_bytes(
        '<html><head><meta charset="latin-1"><title>Test</title></head>'
        '<body><p>Grüße, naïf</p></body></html>'.encode("latin-1")
    )
    data = convert(page)
    assert "Grüße" in text_of(pages(data)[0])
    assert "naïf" in text_of(pages(data)[0])


def test_meta_charset_http_equiv_is_honoured(tmp_path):
    page = tmp_path / "meta.html"
    page.write_bytes(
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
        '<title>Test</title></head><body><p>Grüße, naïf</p></body></html>'.encode("windows-1252")
    )
    data = convert(page)
    assert "Grüße" in text_of(pages(data)[0])


def test_no_meta_charset_defaults_to_utf8(tmp_path):
    page = tmp_path / "no_meta.html"
    page.write_text('<html><body><p>Grüße, naïf</p></body></html>', encoding="utf-8")
    data = convert(page)
    assert "Grüße" in text_of(pages(data)[0])
    assert "naïf" in text_of(pages(data)[0])


def test_explicit_encoding_overrides_meta_charset(tmp_path):
    page = tmp_path / "meta.html"
    page.write_bytes(
        '<html><head><meta charset="windows-1252"><title>Test</title></head>'
        '<body><p>Grüße, naïf</p></body></html>'.encode("windows-1252")
    )
    # Force UTF-8 decoding: should produce mojibake
    data = convert(page, "--encoding", "utf-8")
    text = text_of(pages(data)[0])
    assert "Grüße" not in text
    assert "naïf" not in text


def test_unknown_meta_charset_falls_back_to_utf8(tmp_path, capsys):
    page = tmp_path / "meta.html"
    page.write_bytes(
        '<html><head><meta charset="unknown-charset-xyz"><title>Test</title></head>'
        '<body><p>Hello World</p></body></html>'.encode("utf-8")
    )
    data = convert(page)
    assert "Hello World" in text_of(pages(data)[0])
    err = capsys.readouterr().err
    assert "unknown charset" in err.lower()


def test_undecodable_meta_charset_falls_back_to_utf8(tmp_path, capsys):
    page = tmp_path / "meta.html"
    # Declare UTF-16 but write as UTF-8 (undecodable as UTF-16)
    page.write_bytes(
        '<html><head><meta charset="utf-16"><title>Test</title></head>'
        '<body><p>Hello World</p></body></html>'.encode("utf-8")
    )
    data = convert(page)
    assert "Hello World" in text_of(pages(data)[0])
    err = capsys.readouterr().err
    assert "failed to decode" in err.lower()


def test_user_style_sheet_is_applied(source):
    css = source.parent / "extra.css"
    css.write_text("p { font-size: 3pt }", encoding="utf-8")
    small = convert(source, "--user-style-sheet", str(css))
    big = convert(source)
    assert len(pages(small)) < len(pages(big))


@pytest.fixture
def branded(tmp_path):
    from PIL import Image

    assets = tmp_path.parent / "assets"
    assets.mkdir(exist_ok=True)
    logo = assets / "logo.png"
    Image.new("RGB", (40, 40), "red").save(logo)
    doc = tmp_path / "branded.html"
    doc.write_text(
        f'<html><body><img src="{logo}" width="40" height="40"><p>with logo</p></body></html>',
        encoding="utf-8",
    )
    return doc


def test_local_assets_outside_the_document_are_read_by_default(branded):
    assert images_in(convert(branded)) == 1


@pytest.mark.skipif(not supports_confinement(), reason="engine release predates resource policies")
def test_disable_local_file_access_keeps_the_document_to_its_own_directory(branded):
    assert images_in(convert(branded, "--disable-local-file-access")) == 0


def images_in(data: bytes) -> int:
    return sum(len(page.images) for page in PdfReader(io.BytesIO(data)).pages)


def test_engine_failure_is_reported_not_crashed(source, monkeypatch):
    def explode(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("xhtml2pdf.pisa.pisaDocument", explode)
    with pytest.raises(Exception, match="could not render"):
        convert(source)
