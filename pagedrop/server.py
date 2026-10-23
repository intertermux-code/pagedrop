"""``pagedrop serve``: the converter as a long-running HTTP service.

wkhtmltopdf never had a server mode; this is pagedrop's own. The brief is the
reason people run one at all: pay for the interpreter and the engine import
once instead of per document, keep the command line's flag names so a script
turns into a POST, and stay small enough to run beside the application that
needs it. So it is ``http.server`` from the standard library -- one thread per
connection, a bounded number of conversions in flight, the rest queued -- with
no dependency, no worker supervisor and no broker to operate.

Anyone who can reach the port can hand the server markup and the options that
read files off the disk (``--header-html`` and friends), which is why the
default bind is the loopback interface. Treat a shared service the way you
would treat any internal conversion service: on a network you control, behind
something that authenticates.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import timeout as socket_timeout
from typing import Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from . import cover, engine, flags
from .errors import EngineError, ShimError

SUBCOMMAND = "serve"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_MAX_BODY = 32 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 4

# A client that opens a connection and stops talking must not hold a thread.
IO_TIMEOUT_SECONDS = 30

# How often the listening thread notices that it is time to stop.
POLL_INTERVAL_SECONDS = 0.2

ENDPOINTS = "GET /health, POST /convert"

# ``curl -d @report.html`` puts this on the wire while meaning the body as the
# document, so a body carrying it is read as one.
FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"

_SIZE_SUFFIXES = (("kb", 1024), ("mb", 1024 ** 2), ("gb", 1024 ** 3), ("k", 1024), ("m", 1024 ** 2), ("g", 1024 ** 3))


@dataclass
class Settings:
    """Everything the service needs to know about itself."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_body: int = DEFAULT_MAX_BODY
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    verbose: bool = False


class Refused(Exception):
    """A request the service will not act on, and the status that says why."""

    def __init__(self, status: HTTPStatus, message: str, allow: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.allow = allow


def status_report(queue: Optional[Mapping[str, int]] = None) -> Mapping[str, object]:
    """The health payload: which pagedrop, which engine, how busy."""
    from . import __version__

    report: dict = {"status": "ok", "version": __version__, "engine": engine.engine_version()}
    report.update(queue or {})
    return report


def convert(markup: bytes, options: Mapping[str, object], cover_html: Optional[bytes] = None) -> bytes:
    """One request's markup and options, as PDF bytes.

    The options are the command line's flags spelled as keys, so the service
    refuses exactly what the command line refuses -- including ``--cover``,
    whose value would name a file on the server's disk rather than the
    requester's. That one is the request's ``cover`` field instead.
    """
    ns = flags.namespace_from_options(options)
    if getattr(ns, "cover", None) is not None:
        raise ShimError("a cover is the request's 'cover' field, not the 'cover' option")
    flags.check_limitations(ns)
    ns.input = "<request>"
    document = flags.build_job(ns, document=markup)
    if cover_html is None:
        return engine.render(document)

    return cover.render([cover.cover_job(ns, "<cover>", document=cover_html), document])


class _Handler(BaseHTTPRequestHandler):
    server_version = "pagedrop"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = IO_TIMEOUT_SECONDS

    def version_string(self) -> str:
        from . import __version__

        return f"{self.server_version}/{__version__}"

    def do_GET(self) -> None:
        path, _ = _split(self.path)
        if path == "/health":
            self._json(HTTPStatus.OK, status_report(self.server.queue_status()))
        elif path == "/convert":
            self._refuse(HTTPStatus.METHOD_NOT_ALLOWED, f"POST the document to {path}", allow="POST")
        else:
            self._refuse(HTTPStatus.NOT_FOUND, f"no such endpoint '{path}' - {ENDPOINTS}", allow="GET, POST")

    def do_POST(self) -> None:
        path, query = _split(self.path)
        if path == "/convert":
            markup, cover_html, options = self._read_request(query)
            data = self.server.convert(markup, options, cover_html)
            self._reply(HTTPStatus.OK, "application/pdf", data)
        elif path == "/health":
            self._refuse(HTTPStatus.METHOD_NOT_ALLOWED, "GET /health", allow="GET")
        else:
            self._refuse(HTTPStatus.NOT_FOUND, f"no such endpoint '{path}' - {ENDPOINTS}", allow="GET, POST")

    def do_PUT(self) -> None:
        self._refuse(HTTPStatus.METHOD_NOT_ALLOWED, f"{self.command} is not served here - {ENDPOINTS}",
                     allow="GET, POST")

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT

    def _refuse(self, status: HTTPStatus, message: str, allow: Optional[str] = None) -> None:
        """Turn away a request that will not be acted on, body and all.

        The body is never read, so it is still on the wire when the answer goes
        out: the connection ends with the answer rather than leaving those
        bytes to be mistaken for the next request.
        """
        self.close_connection = True
        raise Refused(status, message, allow=allow)

    def handle_one_request(self) -> None:
        """Everything the request raised, answered as JSON and never as a trace."""
        try:
            super().handle_one_request()
        except Refused as refused:
            self._json(refused.status, {"error": str(refused)}, allow=refused.allow)
        except (EngineError, ShimError) as error:
            # The document or its options were wrong; the service is fine.
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, socket_timeout):
            self.close_connection = True
        except Exception as error:  # noqa: BLE001 - a stack trace never leaves here
            sys.stderr.write(f"pagedrop serve: {type(error).__name__}: {error}\n")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def _read_request(self, query: str) -> Tuple[bytes, Optional[bytes], Mapping[str, object]]:
        """The document, its optional cover and its options, out of the request."""
        body = self._read_body()
        media = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()

        if media in ("", "text/html", "text/plain", FORM_MEDIA_TYPE):
            return body, None, {name: values[-1] for name, values in parse_qs(query).items()}
        if media != "application/json":
            raise Refused(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                f"expected text/html or application/json, got '{media or 'no Content-Type'}'",
            )

        request = self._json_body(body)
        unexpected = sorted(set(request) - {"html", "cover", "options"})
        if unexpected:
            raise Refused(
                HTTPStatus.BAD_REQUEST,
                "unexpected field " + ", ".join(f"'{name}'" for name in unexpected)
                + " - expected 'html', and optionally 'cover' and 'options'",
            )
        if not isinstance(request.get("html"), str):
            raise Refused(HTTPStatus.BAD_REQUEST, "a JSON request needs 'html' as a string")

        options = request.get("options") or {}
        if not isinstance(options, dict):
            raise Refused(HTTPStatus.BAD_REQUEST, "'options' has to be an object of flag names to values")
        cover_html = request.get("cover")
        if cover_html is not None and not isinstance(cover_html, str):
            raise Refused(HTTPStatus.BAD_REQUEST, "'cover' has to be a string of HTML when present")

        return (
            request["html"].encode("utf-8"),
            cover_html.encode("utf-8") if cover_html is not None else None,
            options,
        )

    def _read_body(self) -> bytes:
        declared = self.headers.get("Content-Length")
        if declared is None:
            raise Refused(HTTPStatus.LENGTH_REQUIRED, "the document body needs a Content-Length")
        try:
            size = int(declared)
        except ValueError:
            raise Refused(HTTPStatus.BAD_REQUEST, f"'{declared}' is not a Content-Length") from None
        if size < 0:
            raise Refused(HTTPStatus.BAD_REQUEST, "a negative body length is not a document")

        limit = self.server.settings.max_body
        if size > limit:
            # The rest of the body is still on the wire, so this is the last
            # request on this connection.
            self.close_connection = True
            raise Refused(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"the document is {size} bytes and this service accepts up to {limit}",
            )
        return self.rfile.read(size)

    def _json_body(self, body: bytes) -> Mapping[str, object]:
        try:
            document = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError) as error:
            raise Refused(HTTPStatus.BAD_REQUEST, f"the request body is not JSON: {error}") from None
        if not isinstance(document, dict):
            raise Refused(HTTPStatus.BAD_REQUEST, "a JSON request has to be an object")
        return document

    def _json(self, status: HTTPStatus, payload: Mapping[str, object], allow: Optional[str] = None) -> None:
        self._reply(status, "application/json", (json.dumps(payload) + "\n").encode("utf-8"), allow=allow)

    def _reply(self, status: HTTPStatus, content_type: str, body: bytes, allow: Optional[str] = None) -> None:
        self.send_response(status)
        if allow is not None:
            self.send_header("Allow", allow)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if self.server.settings.verbose:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")


def _split(path: str) -> Tuple[str, str]:
    parsed = urlparse(path)
    return parsed.path.rstrip("/") or "/", parsed.query


class ConversionServer(ThreadingHTTPServer):
    """The HTTP surface around a conversion, on a bounded number of threads."""

    # Not daemon threads: a conversion that is running when the service is told
    # to stop is finished rather than killed, and ``server_close`` waits for it.
    # A client that has stopped talking cannot hold that open for longer than
    # the handler's socket timeout.
    daemon_threads = False
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], settings: Settings) -> None:
        self.settings = settings
        self._slots = threading.BoundedSemaphore(max(settings.max_concurrent, 1))
        self._counting = threading.Lock()
        self.converting = 0
        self.waiting = 0
        super().__init__(address, _Handler)

    def queue_status(self) -> Mapping[str, int]:
        with self._counting:
            return {"converting": self.converting, "waiting": self.waiting}

    def convert(self, markup: bytes, options: Mapping[str, object], cover_html: Optional[bytes]) -> bytes:
        """One conversion; everyone past ``--max-concurrent`` waits their turn.

        A turn is a slot of the semaphore, taken without waiting if one is free
        and from the queue if it is not. Only the second case is counted as
        waiting, which is what /health reports and what an operator watches.
        """
        if not self._slots.acquire(blocking=False):
            with self._counting:
                self.waiting += 1
            try:
                self._slots.acquire()
            finally:
                with self._counting:
                    self.waiting -= 1
        with self._counting:
            self.converting += 1
        try:
            return convert(markup, options, cover_html)
        finally:
            with self._counting:
                self.converting -= 1
            self._slots.release()


def serve(settings: Settings, stop: threading.Event) -> int:
    """Bind the port and convert until ``stop`` is set, then hand it back clean."""
    try:
        httpd = ConversionServer((settings.host, settings.port), settings)
    except OSError as error:
        raise ShimError(f"cannot listen on {settings.host}:{settings.port}: {error.strerror or error}") from None

    host, port = httpd.server_address[0], httpd.server_address[1]
    listening = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": POLL_INTERVAL_SECONDS})
    listening.daemon = True
    listening.start()
    sys.stderr.write(f"pagedrop serve: listening on http://{host}:{port}/ ({ENDPOINTS})\n")
    sys.stderr.flush()
    try:
        stop.wait()
    finally:
        httpd.shutdown()
        listening.join()
        httpd.server_close()
    sys.stderr.write("pagedrop serve: stopped\n")
    return 0


def _integer(value: Optional[str], fallback: int, name: str) -> int:
    if value is None or not value.strip():
        return fallback
    try:
        return int(value)
    except ValueError:
        raise ShimError(f"'{value}' is not a number, and {name} has to be") from None


def _size(value: str) -> int:
    """A byte count with the usual suffixes: ``32``, ``32MB``, ``4k``."""
    text = str(value).strip().lower()
    factor = 1
    for suffix, multiplier in _SIZE_SUFFIXES:
        if text.endswith(suffix):
            text, factor = text[: -len(suffix)].strip(), multiplier
            break
    try:
        number = float(text) * factor
    except ValueError:
        raise ShimError(f"'{value}' is not a size, expected e.g. 32, 4MB, 1GB") from None
    if number < 0:
        raise ShimError(f"'{value}' is not a size, expected e.g. 32, 4MB, 1GB")
    return int(number)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; every pagedrop failure is exit 1."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ShimError(f"{message} - try '{self.prog} --help'")


def parse_args(argv: Sequence[str], prog: str) -> Settings:
    parser = _Parser(prog=f"{prog} serve", add_help=False, description="Run the converter as an HTTP service.")
    parser.add_argument("-h", "--help", action="help", help="show this help page and exit")
    parser.add_argument("--host", default=os.environ.get("PAGEDROP_HOST", DEFAULT_HOST),
                        metavar="<address>", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("-p", "--port", type=int, metavar="<port>",
                        help="port to listen on (default 8080, or $PAGEDROP_PORT)")
    parser.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT, metavar="<n>",
                        help="conversions to render at once, the rest queue (default 4)")
    parser.add_argument("--max-body", type=_size, default=DEFAULT_MAX_BODY, metavar="<bytes>",
                        help="largest document that will be accepted (default 32MB)")
    parser.add_argument("--verbose", action="store_true", help="log every request to stderr")
    arguments = parser.parse_args(list(argv))

    # The environment is only read for the port the command line left to chance,
    # so a stale PAGEDROP_PORT cannot spoil a run that names one.
    port = arguments.port if arguments.port is not None else _default_port()
    if arguments.max_concurrent < 1:
        raise ShimError("option '--max-concurrent' has to be at least 1")
    if arguments.max_body < 1:
        raise ShimError("option '--max-body' has to be at least 1")
    return Settings(
        host=arguments.host,
        port=port,
        max_body=arguments.max_body,
        max_concurrent=arguments.max_concurrent,
        verbose=arguments.verbose,
    )


def _default_port() -> int:
    return _integer(os.environ.get("PAGEDROP_PORT"), DEFAULT_PORT, "PAGEDROP_PORT")


def run(argv: Sequence[str], prog: str) -> int:
    """``pagedrop serve``: run until SIGINT or SIGTERM asks for the port back."""
    settings = parse_args(argv, prog)
    stop = threading.Event()

    def _stop(signum: int, frame: object) -> None:
        stop.set()

    previous = {number: signal.signal(number, _stop) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        return serve(settings, stop)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
