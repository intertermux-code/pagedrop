import io
import re

import pytest
from pypdf import PdfReader

from pagedrop import cli

HTML = """<html><head><title>Quarterly</title></head><body>
<h1>Quarterly report</h1>
<p>{}</p>
</body></html>""".format("Some substantial body text that will fill a page or two. " * 400)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "report.html"
    path.write_text(HTML, encoding="utf-8")
    return path


def run(tmp_path, argv):
    return cli.main([str(arg) for arg in argv], prog="wkhtmltopdf")


def test_version_exits_zero(capsys):
    assert cli.main(["--version"], prog="wkhtmltopdf") == 0
    out = capsys.readouterr().out
    assert re.match(r"wkhtmltopdf 0\.1\.0 \(pagedrop shim, engine xhtml2pdf \d+\.\d+", out)


def test_help_exits_zero_and_looks_like_wkhtmltopdf(capsys):
    assert cli.main(["--help"], prog="wkhtmltopdf") == 0
    out = capsys.readouterr().out
    assert out.startswith("Name\n  wkhtmltopdf - convert HTML documents to PDF")
    for heading in ("Synopsis", "Description", "Global Options:", "Outline Options:",
                    "Page Options:", "Headers And Footer Options:", "Exit codes:"):
        assert heading in out
    assert "--header-spacing <real>" in out


def test_unknown_flag_is_refused(tmp_path, source, capsys):
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--nonsense-flag"]) == 1
    assert "unrecognized option 'nonsense-flag'" in capsys.readouterr().err


def test_option_needing_a_value_is_refused(tmp_path, source, capsys):
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--page-size"]) == 1
    assert "requires a value" in capsys.readouterr().err


def test_missing_arguments_is_refused(capsys):
    assert cli.main([], prog="wkhtmltopdf") == 1
    assert "missing <input> and <output>" in capsys.readouterr().err


def test_unsupported_option_explains_itself(tmp_path, source, capsys):
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--javascript-delay", "500"]) == 1
    assert "no JavaScript" in capsys.readouterr().err


def test_missing_input_file_is_refused(tmp_path, capsys):
    assert run(tmp_path, [tmp_path / "gone.html", tmp_path / "out.pdf"]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_conversion_writes_a_pdf(tmp_path, source):
    target = tmp_path / "out.pdf"
    assert run(tmp_path, [source, target]) == 0
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000
    assert len(PdfReader(io.BytesIO(data)).pages) > 1


def test_output_directory_is_created(tmp_path, source):
    target = tmp_path / "dist" / "deep" / "out.pdf"
    assert run(tmp_path, [source, target]) == 0
    assert target.stat().st_size > 0


def test_degraded_variable_is_reported(tmp_path, source, capsys):
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--footer-center", "[section]"]) == 0
    assert "[section]" in capsys.readouterr().err


def test_quiet_silences_the_degraded_note(tmp_path, source, capsys):
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--quiet", "--footer-center", "[section]"]) == 0
    assert capsys.readouterr().err == ""


def test_log_path_collects_the_notes(tmp_path, source):
    log = tmp_path / "convert.log"
    assert run(tmp_path, [source, tmp_path / "out.pdf", "--log-path", str(log)]) == 0
    assert log.exists()
