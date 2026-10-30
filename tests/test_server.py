"""``pagedrop serve``, over HTTP with a real client and read-back PDFs."""

import http.client
import io
import json
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from pypdf import PdfReader

from pagedrop import __version__, cli, server
from pagedrop.errors import EngineError, ShimError

DOCUMENT = "<html><body><h1>Served Report</h1><p>Body of the served document.</p></body></html>"
COVER = "<html><body><h1>Served Cover</h1><p>Nothing else.</p></body></html>"

TIMEOUT = 30


def start(**changes):
    """A service of its own, on a port the operating system chose."""
    settings = server.Settings(host="127.0.0.1", port=0, **changes)
    httpd = server.ConversionServer((settings.host, settings.port), settings)
    listening = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05})
    listening.daemon = True
    listening.start()
    return httpd, listening, f"http://127.0.0.1:{httpd.server_address[1]}"


def stop(httpd, listening):
    httpd.shutdown()
    httpd.server_close()
    listening.join(timeout=TIMEOUT)


@pytest.fixture
def running():
    """One service for the whole test, taken down whatever the test did."""
    httpd, listening, base = start()
    try:
        yield base
    finally:
        stop(httpd, listening)


def exchange(conn, method, path, body=None, headers=None):
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()


def call(base, method, path, body=None, **headers):
    """One request on one connection: the status, the headers and the body."""
    host, port = base.split("//", 1)[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=TIMEOUT)
    try:
        return exchange(conn, method, path, body, headers)
    finally:
        conn.close()


def post(base, path, body, content_type=None):
    """A document POSTed the way a conversion script would post it."""
    request = urllib.request.Request(base + path, data=body, method="POST")
    if content_type is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {key.lower(): value for key, value in error.headers.items()}, error.read()


def get(base, path="/health"):
    try:
        with urllib.request.urlopen(base + path, timeout=TIMEOUT) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {key.lower(): value for key, value in error.headers.items()}, error.read()


def json_post(base, payload):
    if isinstance(payload, str):
        body = payload.encode("utf-8")  # the test wrote the JSON itself
    else:
        body = json.dumps(payload).encode("utf-8")
    return post(base, "/convert", body, "application/json")


def options(base, **changes):
    """Convert a document with these flags, and hand back the pages."""
    status, _, body = json_post(base, {"html": DOCUMENT, "options": changes})
    assert status == 200, body
    return as_pdf(body).pages


def as_pdf(data) -> PdfReader:
    return PdfReader(io.BytesIO(data))


def text_of(page) -> str:
    return (page.extract_text() or "").replace("\n", " ")


def box(page):
    return (float(page.mediabox.width), float(page.mediabox.height))


def refusal(data) -> str:
    return json.loads(data)["error"]


class TestHealth:
    def test_it_says_which_pagedrop_this_is(self, running):
        status, headers, body = get(running)

        assert status == 200
        assert "application/json" in headers["content-type"]
        assert json.loads(body) == {
            "status": "ok",
            "version": __version__,
            "engine": server.engine.engine_version(),
            "converting": 0,
            "waiting": 0,
        }

    def test_the_service_names_itself_in_the_reply(self, running):
        assert get(running)[1]["server"] == f"pagedrop/{__version__}"


class TestConversion:
    def test_the_body_of_a_post_is_the_document(self, running):
        status, headers, body = post(running, "/convert", DOCUMENT.encode(), "text/html")
        pages = as_pdf(body).pages

        assert status == 200
        assert headers["content-type"] == "application/pdf"
        assert len(pages) == 1
        assert "Served Report" in text_of(pages[0])

    def test_a_content_type_the_client_guessed_is_still_a_document(self, running):
        """urllib posts form-urlencoded for a body it was handed no type for."""
        status, _, body = post(running, "/convert", DOCUMENT.encode())

        assert status == 200
        assert "Served Report" in text_of(as_pdf(body).pages[0])

    def test_a_fragment_is_wrapped_rather_than_thrown_away(self, running):
        status, _, body = post(running, "/convert", b"<p>Only a paragraph</p>", "text/html")

        assert status == 200
        assert "Only a paragraph" in text_of(as_pdf(body).pages[0])

    def test_an_empty_document_is_still_a_pdf(self, running):
        status, _, body = post(running, "/convert", b"", "text/html")

        assert status == 200
        assert body.startswith(b"%PDF-") and body.rstrip().endswith(b"%%EOF")

    def test_a_query_string_carries_the_options(self, running):
        query = urllib.parse.urlencode({"margin-bottom": "25mm", "footer-center": "Page [page] of [topage]"})
        status, _, body = post(running, f"/convert?{query}", DOCUMENT.encode(), "text/html")

        assert status == 200
        assert "Page 1 of 1" in text_of(as_pdf(body).pages[0])

    def test_json_options_are_the_command_line_flags(self, running):
        pages = options(running, **{"page-size": "A5", "margin": "10mm"})

        assert box(pages[0]) == pytest.approx((419.53, 595.28))

    def test_a_band_and_a_title_given_in_json_reach_the_page(self, running):
        pages = options(running, **{"margin-top": "25mm", "header-left": "ACME"})
        status, _, body = json_post(running, {"html": DOCUMENT, "options": {"title": "Priced List"}})

        assert "ACME" in text_of(pages[0])
        assert status == 200
        assert as_pdf(body).metadata.title == "Priced List"

    def test_grayscale_is_asked_of_the_engine_itself(self, running):
        def paint(**changes) -> bytes:
            status, _, body = json_post(running, {"html": DOCUMENT, "options": changes})
            assert status == 200
            return b"".join(
                page.get_contents().get_data() for page in as_pdf(body).pages if page.get_contents() is not None
            )

        assert re.findall(rb"\d*\.?\d+ \d*\.?\d+ \d*\.?\d+ rg", paint(margin="10mm"))
        assert not re.findall(rb"\d*\.?\d+ \d*\.?\d+ \d*\.?\d+ rg", paint(margin="10mm", grayscale=True))

    def test_a_cover_field_fronts_the_document(self, running):
        status, _, body = json_post(
            running,
            {"html": DOCUMENT, "cover": COVER, "options": {"margin-bottom": "25mm", "footer-left": "Confidential"}},
        )
        pages = as_pdf(body).pages

        assert status == 200
        assert len(pages) == 2
        assert "Served Cover" in text_of(pages[0]) and "Served Report" not in text_of(pages[0])
        assert "Served Report" in text_of(pages[1])
        assert "Confidential" not in text_of(pages[0]), "the document's band stays off the cover"
        assert "Confidential" in text_of(pages[1])

    def test_the_request_is_named_as_the_source_of_a_url_token(self, running):
        pages = options(running, **{"margin-bottom": "25mm", "footer-right": "[url]"})

        assert "<request>" in text_of(pages[0])

    def test_two_requests_share_one_connection(self, running):
        host, port = running.split("//", 1)[1].split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=TIMEOUT)
        try:
            document = exchange(conn, "POST", "/convert", DOCUMENT.encode(), {"Content-Type": "text/html"})
            health = exchange(conn, "GET", "/health")
        finally:
            conn.close()

        assert document[0] == 200 and document[2].startswith(b"%PDF-")
        assert health[0] == 200


class TestRefusals:
    def test_an_option_that_does_not_exist_is_named(self, running):
        status, _, body = json_post(running, {"html": DOCUMENT, "options": {"--nonsense": 1}})

        assert status == 400
        assert "unrecognized option" in refusal(body)

    def test_an_option_the_engine_cannot_honour_is_refused_here_too(self, running):
        status, _, body = json_post(running, {"html": DOCUMENT, "options": {"javascript-delay": 500}})

        assert status == 400
        assert "no JavaScript" in refusal(body)

    @pytest.mark.parametrize("option, value", [
        ("outline-depth", "deep"),
        ("outline-depth", "2.5"),
        ("header-font-size", "big"),
        ("footer-font-size", "huge"),
    ])
    def test_an_option_value_that_is_not_a_number_is_a_bad_request(self, running, option, value):
        status, _, body = json_post(running, {"html": DOCUMENT, "options": {option: value}})

        assert status == 400
        assert f"'--{option}'" in refusal(body) and f"'{value}'" in refusal(body)
        assert b"Traceback" not in body

    def test_a_query_string_option_that_is_not_a_number_is_a_bad_request(self, running):
        query = urllib.parse.urlencode({"outline-depth": "deep"})
        status, _, body = post(running, f"/convert?{query}", DOCUMENT.encode(), "text/html")

        assert status == 400
        assert "whole number" in refusal(body)

    def test_a_number_option_still_takes_its_numbers(self, running):
        pages = options(running, **{"outline-depth": 2, "header-font-size": "9", "header-left": "ACME"})

        assert "Served Report" in text_of(pages[0])
        assert "ACME" in text_of(pages[0])

    def test_a_cover_is_a_field_and_never_a_path_on_the_servers_disk(self, running):
        status, _, body = json_post(running, {"html": DOCUMENT, "options": {"cover": "/etc/passwd"}})

        assert status == 400
        assert "'cover' field" in refusal(body)

    def test_a_request_that_is_not_an_object_is_turned_away(self, running):
        status, _, body = json_post(running, [1, 2, 3])

        assert status == 400
        assert "has to be an object" in refusal(body)

    def test_a_request_that_is_not_json_at_all_is_turned_away(self, running):
        status, _, body = json_post(running, "{html: ")

        assert status == 400
        assert "not JSON" in refusal(body)

    def test_a_request_without_the_document_is_turned_away(self, running):
        status, _, body = json_post(running, {"options": {"margin": "10mm"}})

        assert status == 400
        assert "'html' as a string" in refusal(body)

    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"html": "<p>x</p>", "extra": 1}, "unexpected field 'extra'"),
            ({"html": "<p>x</p>", "options": ["margin"]}, "'options' has to be an object"),
            ({"html": "<p>x</p>", "cover": 42}, "'cover' has to be a string"),
        ],
    )
    def test_a_field_of_the_wrong_shape_is_named(self, running, payload, expected):
        status, _, body = json_post(running, payload)

        assert status == 400
        assert expected in refusal(body)

    def test_a_media_type_that_is_not_a_document_is_refused(self, running):
        status, _, body = post(running, "/convert", b"<html></html>", "application/xml")

        assert status == 415
        assert "text/html or application/json" in refusal(body)

    def test_a_body_without_a_length_is_refused_before_it_is_read(self, running):
        host, port = running.split("//", 1)[1].split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=TIMEOUT)
        try:
            conn.putrequest("POST", "/convert")
            conn.endheaders()
            response = conn.getresponse()
            status, body = response.status, response.read()
        finally:
            conn.close()

        assert status == 411
        assert "Content-Length" in refusal(body)

    def test_a_length_that_is_not_a_number_is_refused(self, running):
        status, _, body = call(running, "POST", "/convert", DOCUMENT.encode(), **{"Content-Length": "too many"})

        assert status == 400
        assert "not a Content-Length" in refusal(body)

    def test_a_negative_length_is_refused(self, running):
        status, _, body = call(running, "POST", "/convert", None, **{"Content-Length": "-5"})

        assert status == 400
        assert "negative body length" in refusal(body)

    def test_a_document_larger_than_the_service_holds(self):
        httpd, listening, base = start(max_body=128)
        try:
            status, headers, body = post(base, "/convert", b"<p>" + b"x" * 400 + b"</p>", "text/html")
        finally:
            stop(httpd, listening)

        assert status == 413
        assert headers["connection"] == "close"
        assert "accepts up to 128" in refusal(body)

    def test_a_document_the_engine_cannot_render_is_a_bad_request(self, running, monkeypatch):
        def refuse(job):
            raise EngineError("the engine would not take this stylesheet")

        monkeypatch.setattr(server.engine, "render", refuse)
        status, _, body = post(running, "/convert", DOCUMENT.encode(), "text/html")

        assert status == 400
        assert "would not take this stylesheet" in refusal(body)

    def test_anything_else_is_an_internal_error_without_a_trace(self, running, monkeypatch, capsys):
        def explode(job):
            raise RuntimeError("a bug, not a bad document")

        monkeypatch.setattr(server.engine, "render", explode)
        status, _, body = post(running, "/convert", DOCUMENT.encode(), "text/html")

        assert status == 500
        assert refusal(body) == "internal server error"
        assert "RuntimeError: a bug" in capsys.readouterr().err

    def test_no_answer_of_this_service_carries_a_trace(self, running, monkeypatch):
        def explode(job):
            raise RuntimeError("boom")

        monkeypatch.setattr(server.engine, "render", explode)
        answers = [
            post(running, "/convert", DOCUMENT.encode(), "application/xml"),
            post(running, "/convert", DOCUMENT.encode(), "application/json"),
            post(running, "/convert", DOCUMENT.encode(), "text/html"),
            get(running, "/nothing"),
            call(running, "POST", "/health", b""),
            call(running, "PUT", "/convert", b"a body that is never read"),
        ]

        for status, _, body in answers:
            assert status >= 400
            assert b"Traceback" not in body


class TestRouting:
    def test_a_get_to_the_converter_points_at_post(self, running):
        status, headers, body = call(running, "GET", "/convert")

        assert status == 405
        assert headers["allow"] == "POST"
        assert "POST the document" in refusal(body)

    def test_a_post_to_the_health_check_points_at_get(self, running):
        status, headers, _ = call(running, "POST", "/health", b"")

        assert status == 405
        assert headers["allow"] == "GET"

    def test_an_unknown_path_lists_what_is_served(self, running):
        status, _, body = call(running, "GET", "/printer")

        assert status == 404
        assert server.ENDPOINTS in refusal(body)

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS"])
    def test_a_method_that_is_not_served_is_refused(self, running, method):
        status, headers, body = call(running, method, "/convert", b"content")

        assert status == 405
        assert headers["allow"] == "GET, POST"
        assert f"{method} is not served" in refusal(body)

    def test_a_trailing_slash_is_the_same_endpoint(self, running):
        assert call(running, "GET", "/health/")[0] == 200

    def test_a_refusal_that_left_a_body_on_the_wire_ends_the_connection(self, running):
        status, headers, _ = call(running, "POST", "/nothing", b"a body nobody read")

        assert status == 404
        assert headers["connection"] == "close"
        assert get(running)[0] == 200


class TestQueue:
    def test_conversions_beyond_the_limit_wait_for_a_slot(self, monkeypatch):
        gate, arrived = hold_the_engine(monkeypatch)
        httpd, listening, base = start(max_concurrent=2)
        results = []
        clients = [
            threading.Thread(target=lambda: results.append(post(base, "/convert", DOCUMENT.encode(), "text/html")))
            for _ in range(5)
        ]
        try:
            for client in clients:
                client.start()
            assert wait_for_work(httpd, 5) == {"converting": 2, "waiting": 3}

            gate.set()
            for client in clients:
                client.join(TIMEOUT)
        finally:
            gate.set()
            stop(httpd, listening)

        assert [status for status, _, _ in results] == [200] * 5
        assert [len(as_pdf(body).pages) for _, _, body in results] == [1] * 5

    def test_work_under_way_is_answered_before_the_port_is_given_back(self, monkeypatch):
        gate, arrived = hold_the_engine(monkeypatch)
        httpd, listening, base = start()
        answered: list = []
        client = threading.Thread(
            target=lambda: answered.append(post(base, "/convert", DOCUMENT.encode(), "text/html"))
        )
        try:
            client.start()
            assert wait_for_work(httpd, 1)["converting"] == 1

            threading.Timer(0.8, gate.set).start()
            started = time.monotonic()
            stop(httpd, listening)
            held = time.monotonic() - started
            client.join(TIMEOUT)
        finally:
            gate.set()

        assert held >= 0.4, "the port came back only once the conversion had been answered"
        assert not client.is_alive() and len(arrived) == 1
        status, _, body = answered[0]
        assert status == 200 and len(as_pdf(body).pages) == 1

    def test_the_report_counts_the_work_in_front_of_the_queue(self, monkeypatch):
        gate, arrived = hold_the_engine(monkeypatch)
        httpd, listening, base = start(max_concurrent=1)
        try:
            first = threading.Thread(target=lambda: post(base, "/convert", DOCUMENT.encode(), "text/html"))
            first.start()
            assert wait_for_work(httpd, 1)["converting"] == 1
            assert json.loads(get(base)[2]) == {
                "status": "ok",
                "version": __version__,
                "engine": server.engine.engine_version(),
                "converting": 1,
                "waiting": 0,
            }

            second = threading.Thread(target=lambda: post(base, "/convert", DOCUMENT.encode(), "text/html"))
            second.start()
            assert wait_for_work(httpd, 2)["waiting"] == 1
            gate.set()
            first.join(TIMEOUT)
            second.join(TIMEOUT)
        finally:
            gate.set()
            stop(httpd, listening)

        assert len(arrived) == 2, "both documents reached the engine, none lost to the queue"


def hold_the_engine(monkeypatch):
    """Every conversion arrives, then waits for the test to let it answer."""
    gate = threading.Event()
    arrived: list = []
    convert = server.engine.render

    def slowly(job):
        arrived.append(job)
        gate.wait(TIMEOUT)
        return convert(job)

    monkeypatch.setattr(server.engine, "render", slowly)
    return gate, arrived


def wait_for_work(httpd, wanted, deadline=10.0) -> dict:
    """The queue report once ``wanted`` conversions are accounted for."""
    limit = time.monotonic() + deadline
    while time.monotonic() < limit:
        report = httpd.queue_status()
        if sum(report.values()) >= wanted:
            return report
        time.sleep(0.05)
    raise AssertionError(f"never saw {wanted} conversions in flight: {report}")


class TestSettings:
    def test_it_binds_the_loopback_by_default(self, monkeypatch):
        monkeypatch.delenv("PAGEDROP_HOST", raising=False)
        monkeypatch.delenv("PAGEDROP_PORT", raising=False)
        settings = server.parse_args([], "pagedrop")

        assert (settings.host, settings.port) == ("127.0.0.1", 8080)
        assert (settings.max_concurrent, settings.max_body) == (4, 32 * 1024 * 1024)

    def test_the_address_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("PAGEDROP_HOST", "0.0.0.0")
        monkeypatch.setenv("PAGEDROP_PORT", "9123")
        settings = server.parse_args([], "pagedrop")

        assert (settings.host, settings.port) == ("0.0.0.0", 9123)

    def test_the_command_line_outranks_the_environment(self, monkeypatch):
        monkeypatch.setenv("PAGEDROP_PORT", "9123")

        assert server.parse_args(["--port", "9200"], "pagedrop").port == 9200
        assert server.parse_args(["-p", "9200"], "pagedrop").port == 9200

    @pytest.mark.parametrize(
        "text, expected",
        [("32", 32), ("4k", 4096), ("8KB", 8192), ("2m", 2 * 1024 ** 2), ("4MB", 4 * 1024 ** 2), ("1GB", 1024 ** 3)],
    )
    def test_a_body_limit_is_spelled_in_bytes_or_in_units(self, text, expected):
        assert server.parse_args(["--max-body", text], "pagedrop").max_body == expected

    @pytest.mark.parametrize("text", ["", "many", "-1", "MB"])
    def test_a_body_limit_that_is_not_a_size_is_refused(self, text):
        with pytest.raises(ShimError) as error:
            server.parse_args(["--max-body", text], "pagedrop")
        assert "is not a size" in str(error.value)

    def test_a_port_that_is_not_a_number_is_refused_wherever_it_came_from(self, monkeypatch):
        monkeypatch.setenv("PAGEDROP_PORT", "eighty")
        with pytest.raises(ShimError) as from_environment:
            server.parse_args([], "pagedrop")
        with pytest.raises(ShimError) as from_command_line:
            server.parse_args(["--port", "eighty"], "pagedrop")

        assert "PAGEDROP_PORT" in str(from_environment.value)
        assert "invalid int value" in str(from_command_line.value)

    @pytest.mark.parametrize("argv", [["--max-concurrent", "0"], ["--max-body", "0"]])
    def test_a_limit_of_nothing_would_stop_everything(self, argv):
        with pytest.raises(ShimError) as error:
            server.parse_args(argv, "pagedrop")
        assert "at least 1" in str(error.value)

    def test_a_usage_error_is_exit_one_and_points_at_the_help_page(self, capsys):
        assert cli.main(["serve", "--nonsense"], prog="pagedrop") == 1
        assert "try 'pagedrop serve --help'" in capsys.readouterr().err

    def test_the_help_page_lists_its_own_options(self, capsys):
        assert cli.main(["serve", "--help"], prog="pagedrop") == 0
        page = capsys.readouterr().out

        assert "--max-concurrent" in page and "--port" in page and "$PAGEDROP_PORT" in page


class TestShutdown:
    def test_it_hands_the_port_back_when_asked(self, capsys):
        assert server.serve(server.Settings(port=0), stopped()) == 0
        report = capsys.readouterr().err

        assert "listening on http://127.0.0.1:" in report
        assert server.ENDPOINTS in report
        assert report.rstrip().endswith("stopped")

    def test_a_port_somebody_else_has_is_reported_as_such(self):
        httpd, listening, base = start()
        port = int(base.rsplit(":", 1)[1])
        try:
            with pytest.raises(ShimError) as error:
                server.serve(server.Settings(port=port), stopped())
            assert f"cannot listen on 127.0.0.1:{port}" in str(error.value)
        finally:
            stop(httpd, listening)

    @pytest.mark.parametrize("signame", [signal.SIGINT, signal.SIGTERM])
    def test_a_signal_stops_a_running_service(self, signame):
        """The whole command, in its own process, told to stop."""
        service = subprocess.Popen(
            [sys.executable, "-m", "pagedrop", "serve", "--port", "0"],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
        )
        try:
            line = service.stderr.readline()
            assert line.startswith("pagedrop serve: listening on http://127.0.0.1:")
            address = re.search(r"http://(\S+?)/", line).group(1)
            assert get(f"http://{address}", "/health")[0] == 200

            service.send_signal(signame)
            assert service.wait(timeout=TIMEOUT) == 0
        finally:
            if service.poll() is None:
                service.kill()
                service.wait(timeout=TIMEOUT)
            assert service.stderr.read().rstrip().endswith("stopped")
            service.stderr.close()


def stopped() -> threading.Event:
    """An event already asking the service to give the port back."""
    stop = threading.Event()
    stop.set()
    return stop
