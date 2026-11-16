import io

from pypdf import PdfReader

from pagedrop import cli


COVER = """<html><head><style>@page { size: 200mm 280mm; margin: 0 }</style></head>
<body><h1>Cover</h1></body></html>"""

BODY = "<html><body><h1>The Report</h1>{}</body></html>".format(
    "".join(f"<p>Body paragraph {i}, long enough to fill the page.</p>" for i in range(40))
)

BODY_WITH_META = """<html><head><title>Body Title</title>
<meta name="author" content="Body Author">
<meta name="subject" content="Body Subject">
<meta name="keywords" content="alpha, beta">
</head><body><h1>The Report</h1><p>Body text.</p></body></html>"""


def run(*argv) -> int:
    return cli.main([str(arg) for arg in argv], prog="wkhtmltopdf")


def read(path) -> PdfReader:
    return PdfReader(io.BytesIO(path.read_bytes()))


def test_cover_join_keeps_body_info_dict(tmp_path):
    cover = tmp_path / "cover.html"
    body = tmp_path / "body.html"
    out = tmp_path / "merged.pdf"
    cover.write_text(COVER, encoding="utf-8")
    body.write_text(BODY_WITH_META, encoding="utf-8")

    assert run("cover", cover, body, out, "--title", "CLI Title") == 0

    meta = read(out).metadata
    assert meta is not None
    assert meta.title == "CLI Title"
    assert meta.author == "Body Author"
    assert meta.get("/Subject") == "Body Subject"
    assert meta.get("/Keywords") == "alpha, beta"
    assert meta.get("/Producer")
    assert meta.get("/Creator") is not None


def test_cover_flag_join_keeps_body_info_dict(tmp_path):
    cover = tmp_path / "cover.html"
    body = tmp_path / "body.html"
    out = tmp_path / "merged.pdf"
    cover.write_text(COVER, encoding="utf-8")
    body.write_text(BODY_WITH_META, encoding="utf-8")

    assert run("--cover", cover, body, out) == 0

    meta = read(out).metadata
    assert meta is not None
    assert meta.title == "Body Title"
    assert meta.author == "Body Author"


def test_cover_join_keeps_cover_info_dict_when_body_has_none(tmp_path):
    cover = tmp_path / "cover.html"
    body = tmp_path / "body.html"
    out = tmp_path / "merged.pdf"
    cover.write_text(
        "<html><head><title>Cover Title</title>"
        '<meta name="author" content="Cover Author"></head>'
        "<body><h1>Cover</h1></body></html>",
        encoding="utf-8",
    )
    body.write_text("<html><body><h1>Body</h1><p>plain</p></body></html>", encoding="utf-8")

    assert run("cover", cover, body, out) == 0

    meta = read(out).metadata
    assert meta is not None
    assert meta.title == "Cover Title"
    assert meta.author == "Cover Author"


def test_cover_less_run_info_dict_unchanged(tmp_path):
    body = tmp_path / "body.html"
    out = tmp_path / "out.pdf"
    body.write_text(BODY_WITH_META, encoding="utf-8")

    assert run(body, out) == 0

    meta = read(out).metadata
    assert meta is not None
    assert meta.title == "Body Title"
    assert meta.author == "Body Author"
