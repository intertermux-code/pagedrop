import io

import pytest
from pypdf import PdfReader

from pagedrop import flags
from pagedrop.errors import ShimError


def parse(argv):
    """The two steps the CLI takes, so the table can be tested on its own."""
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args(list(argv))
    flags.check_limitations(ns)
    return ns


@pytest.fixture
def page(tmp_path):
    path = tmp_path / "doc.html"
    path.write_text("<html><body><p>Hello</p></body></html>", encoding="utf-8")
    return str(path)


@pytest.fixture
def out(tmp_path):
    return str(tmp_path / "out.pdf")


def job_for(tmp_path, page, out, extra=()):
    argv = [page, out, *extra]
    return flags.build_job(parse(argv))


def test_defaults_match_wkhtmltopdf(tmp_path, page, out):
    job = job_for(tmp_path, page, out)
    assert job.page_width == pytest.approx(595.28, abs=0.5)  # A4
    assert job.page_height == pytest.approx(841.89, abs=0.5)
    top, right, bottom, left = job.margins
    assert (top, right, bottom, left) == pytest.approx((28.35,) * 4, abs=0.1)  # 10mm
    assert job.outline is True
    assert job.grayscale is False


def test_margins_are_translated_in_the_given_unit(tmp_path, page, out):
    job = job_for(tmp_path, page, out, ["--margin-unit", "inch", "--margin", "1"])
    assert job.margins == pytest.approx((72.0,) * 4)


def test_short_margin_flag_equals_long_flag(tmp_path, page, out):
    short = job_for(tmp_path, page, out, ["-m", "12mm"])
    long = job_for(tmp_path, page, out, ["--margin", "12mm"])
    assert short.margins == long.margins


def test_short_margin_flag_requires_a_value(page, out):
    with pytest.raises(Exception, match="requires a value"):
        flags.ArgumentParser("wkhtmltopdf").parse_args([page, out, "-m"])


def test_mixed_units_and_bare_numbers(tmp_path, page, out):
    job = job_for(
        tmp_path, page, out,
        ["--margin-top", "2cm", "--margin-right", "15", "--margin-bottom", "0.5in", "--margin-left", "36pt"],
    )
    top, right, bottom, left = job.margins
    assert top == pytest.approx(56.7, abs=0.1)
    assert right == pytest.approx(42.5, abs=0.1)  # bare numbers are mm
    assert bottom == pytest.approx(36.0)
    assert left == pytest.approx(36.0)


def test_named_page_size_and_landscape(tmp_path, page, out):
    job = job_for(tmp_path, page, out, ["--page-size", "Letter", "--orientation", "Landscape"])
    assert (job.page_width, job.page_height) == pytest.approx((792.0, 612.0))


def test_custom_page_size(tmp_path, page, out):
    job = job_for(tmp_path, page, out, ["--page-size", "100mmx80mm"])
    assert (job.page_width, job.page_height) == pytest.approx((283.46, 226.77), abs=0.1)


def test_explicit_width_and_height_win(tmp_path, page, out):
    job = job_for(tmp_path, page, out, ["--page-width", "120mm", "--page-height", "200mm"])
    assert (job.page_width, job.page_height) == pytest.approx((340.16, 566.93), abs=0.1)


def test_unknown_paper_size_is_refused(page, out):
    ns = parse([page, out, "--page-size", "Foolscap"])
    with pytest.raises(Exception, match="unknown paper size"):
        flags.build_job(ns)


def test_unknown_orientation_is_refused(page, out):
    ns = parse([page, out, "--orientation", "Sideways"])
    with pytest.raises(Exception, match="unknown orientation"):
        flags.build_job(ns)


def test_header_text_bands(page, out):
    ns = parse([
        page, out,
        "--header-left", "ACME", "--header-center", "Page [page]", "--header-right", "Confidential",
        "--header-line", "--header-font-size", "9", "--header-spacing", "4",
    ])
    job = flags.build_job(ns)
    assert job.header.left == "ACME"
    assert job.header.center == "Page <pdf:pagenumber/>"
    assert job.header.right == "Confidential"
    assert job.header.line is True
    assert job.header.font_size == 9.0
    assert job.header.spacing == pytest.approx(11.34, abs=0.1)


def test_header_html_is_inlined_and_stripped_of_page_rules(tmp_path, page, out):
    band = tmp_path / "head.html"
    band.write_text(
        "<html><head><style>@page { size: A3; margin: 0 } td { color: red }</style></head>"
        "<body><div>Invoice [title]</div></body></html>",
        encoding="utf-8",
    )
    ns = parse([page, out, "--header-html", str(band), "--title", "42"])
    job = flags.build_job(ns)
    assert job.header.html == "<div>Invoice 42</div>"
    assert "size: A3" not in job.header.css
    assert "color: red" in job.header.css


def test_a_band_without_margin_room_is_refused(page, out):
    ns = parse([page, out, "--header-left", "x", "--margin-top", "10mm", "--header-spacing", "12"])
    with pytest.raises(Exception, match="leaves no room for the header"):
        flags.build_job(ns)


def test_footer_defaults_its_own_band_depth(page, out):
    ns = parse([page, out, "--footer-center", "x"])
    job = flags.build_job(ns)
    assert job.footer.margin > job.footer.spacing


def test_no_bands_by_default(page, out):
    job = flags.build_job(parse([page, out]))
    assert job.header is None and job.footer is None


def test_title_and_encoding(page, out):
    ns = parse([page, out, "--title", "Q3 report", "--encoding", "latin-1"])
    job = flags.build_job(ns)
    assert job.title == "Q3 report"


def test_outline_flags(page, out):
    assert flags.build_job(parse([page, out, "--no-outline"])).outline is False
    assert flags.build_job(parse([page, out, "--outline-depth", "2"])).outline_depth == 2


def test_grayscale_flag(page, out):
    assert flags.build_job(parse([page, out, "--grayscale"])).grayscale is True


def test_user_style_sheet_is_loaded(tmp_path, page, out):
    css = tmp_path / "extra.css"
    css.write_text("body { font-size: 9pt }", encoding="utf-8")
    ns = parse([page, out, "--user-style-sheet", str(css)])
    assert "font-size: 9pt" in flags.build_job(ns).stylesheet


@pytest.mark.parametrize(
    "argv",
    [
        ["--javascript-delay", "200"],
        ["--enable-javascript"],
        ["--cookie", "a", "b"],
        ["--proxy", "http://x"],
        ["--toc"],
        ["--dump-outline", "o.xml"],
        ["--viewport-size", "1024x768"],
        ["--load-error-handling", "ignore"],
        ["--enable-smart-shrinking"],
        ["--no-print-media-type"],
    ],
)
def test_refused_options_say_why(page, out, argv):
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([page, out, *argv])
    with pytest.raises(Exception) as error:
        flags.check_limitations(ns)
    message = str(error.value)
    assert "is not supported:" in message and len(message.split("is not supported:")[1]) > 30


@pytest.mark.parametrize("argv", [["--zoom", "1"], ["--dpi", "96"], ["--copies", "1"], ["--zoom", "1.0"]])
def test_options_accepted_at_their_default(page, out, argv):
    parse([page, out, *argv])


@pytest.mark.parametrize("argv", [["--zoom", "0.7"], ["--dpi", "300"], ["--copies", "2"]])
def test_the_same_options_refused_off_their_default(page, out, argv):
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([page, out, *argv])
    with pytest.raises(Exception, match="is not supported"):
        flags.check_limitations(ns)


@pytest.mark.parametrize("argv", [
    ["--outline-depth", "deep"],
    ["--outline-depth", "2.5"],
    ["--header-font-size", "big"],
    ["--footer-font-size", "huge"],
])
def test_a_number_option_refuses_a_value_that_is_not_a_number(page, out, argv):
    with pytest.raises(ShimError) as error:
        parse([page, out, *argv])

    option, value = argv
    message = str(error.value)
    assert option in message and f"'{value}'" in message


def test_a_number_option_is_refused_by_the_job_too(page, out):
    """build_job is reachable without the check, so it refuses there as well."""
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([page, out, "--outline-depth", "deep"])
    with pytest.raises(ShimError, match="outline-depth"):
        flags.build_job(ns)


def test_a_band_font_size_is_refused_by_the_job_too(page, out):
    ns = flags.ArgumentParser("wkhtmltopdf").parse_args([page, out, "--header-left", "x", "--header-font-size", "big"])
    with pytest.raises(ShimError, match="header-font-size"):
        flags.build_job(ns)


def test_a_number_option_still_takes_the_numbers_it_did(page, out):
    assert flags.build_job(parse([page, out, "--outline-depth", "0"])).outline_depth == 0
    job = flags.build_job(parse([page, out, "--header-left", "x", "--header-font-size", " 9.5 "]))
    assert job.header.font_size == 9.5
    assert flags.build_job(parse([page, out, "--footer-left", "x", "--footer-font-size", "12"])).footer.font_size == 12.0


@pytest.mark.parametrize("argv", [["--print-media-type"], ["--disable-smart-shrinking"],
                                  ["--enable-local-file-access"], ["--quiet"], ["--lowquality"],
                                  ["--disable-javascript"], ["--no-header-line"]])
def test_inherent_options_are_accepted(page, out, argv):
    parse([page, out, *argv])


def test_inert_options_do_not_reach_the_job(page, out):
    job = flags.build_job(parse([page, out, "--print-media-type", "--disable-smart-shrinking"]))
    assert job.header is None


def test_options_file_is_spliced(tmp_path, page, out):
    opts = tmp_path / "opts.txt"
    opts.write_text("--page-size Letter\n--margin-top 20mm  # comment\n", encoding="utf-8")
    argv = flags.expand_options_files(["--options-file", str(opts), page, out])
    assert argv == ["--page-size", "Letter", "--margin-top", "20mm", page, out]


def test_options_file_accepts_full_line_comments(tmp_path, page, out):
    opts = tmp_path / "opts.txt"
    opts.write_text("# page size\n--page-size Letter\n\n    # margins\n--margin-top 20mm\n",
                    encoding="utf-8")
    argv = flags.expand_options_files(["--options-file", str(opts), page, out])
    assert argv == ["--page-size", "Letter", "--margin-top", "20mm", page, out]


def test_options_file_comment_does_not_become_an_argument(tmp_path, page, out):
    opts = tmp_path / "opts.txt"
    opts.write_text("# a comment at column 0\n--page-size Letter\n", encoding="utf-8")
    # cli.run() parses the spliced list, not the raw argv.
    argv = flags.expand_options_files([page, out, "--options-file", str(opts)])
    job = flags.build_job(parse(argv))
    assert (job.page_width, job.page_height) == pytest.approx((612.0, 792.0))


def test_options_file_keeps_hash_inside_a_value(tmp_path, page, out):
    opts = tmp_path / "opts.txt"
    opts.write_text("--footer-left ACME#42\n", encoding="utf-8")
    argv = flags.expand_options_files(["--options-file", str(opts), page, out])
    assert argv[:2] == ["--footer-left", "ACME#42"]


def test_every_flag_is_documented():
    text = "\n".join(flag.help_line() for flag in flags.FLAGS)
    for flag in flags.FLAGS:
        assert flag.name in text


def test_help_mentions_the_engine_limits():
    from pagedrop.cli import help_text

    text = help_text("wkhtmltopdf")
    assert "Refused, with an explanation:" in text
    assert "Accepted only at the value wkhtmltopdf defaults to:" in text
    assert "--javascript-delay" in text
    assert "[topage]" in text


def render(page, out, extra=()):
    from pagedrop import engine

    job = flags.build_job(parse([page, out, *extra]))
    return engine.render(job)


def test_pdf_page_size_follows_the_flags(tmp_path, page, out):
    data = render(page, out, ["--page-size", "Letter", "--orientation", "Landscape"])
    box = PdfReader(io.BytesIO(data)).pages[0].mediabox
    assert (int(box.width), int(box.height)) == (792, 612)
