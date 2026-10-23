import re
from pathlib import Path

import pagedrop
from pagedrop import cli


def _pyproject_version():
    text = Path("pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match
    return match.group(1)


def test_version_sync():
    assert _pyproject_version() == pagedrop.__version__


def test_version_cli_output(capsys):
    for prog in ("pagedrop", "wkhtmltopdf"):
        assert cli.main(["--version"], prog=prog) == 0
        out = capsys.readouterr().out
        assert pagedrop.__version__ in out
        assert pagedrop.__version__ == _pyproject_version()