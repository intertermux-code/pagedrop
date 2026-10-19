"""Reading the document and the side files it points at."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request

from .errors import ShimError

TIMEOUT_SECONDS = 30


def read_resource(uri: str, base_dir: str = ".") -> bytes:
    """Local path, ``file://`` URL or ``http(s)://`` URL, as bytes."""
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme in ("http", "https"):
        return _fetch(uri)
    if parsed.scheme == "file":
        path = urllib.parse.unquote(parsed.path)
    elif parsed.scheme in ("", ".") or (len(parsed.scheme) == 1 and os.name == "nt"):
        path = uri if os.path.isabs(uri) else os.path.join(base_dir, uri)
    else:
        raise ShimError(f"cannot read '{uri}': unsupported scheme '{parsed.scheme}'")

    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as error:
        raise ShimError(f"cannot read '{uri}': {error.strerror or error}") from None


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pagedrop"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise ShimError(f"cannot read '{url}': server returned {error.code}") from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise ShimError(f"cannot read '{url}': {reason}") from None
