"""The TaskFactory WSGI application: the form page, the status routes and generation."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from taskfactory import __version__
from taskfactory.web.forms import FormError, parse_form
from taskfactory.web.generate import (
    FAILED_MESSAGE,
    GenerationBusy,
    GenerationFailed,
    generate,
)
from taskfactory.web.render_page import render_page
from taskfactory.web.results_summary import render_message, render_results

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

MAX_REQUEST_BYTES = 4096
TOO_LARGE_MESSAGE = (
    "Your request is too large. Reload the form and choose fewer charts."
)

Headers = list[tuple[str, str]]
Response = tuple[str, Headers, bytes]


class _BodyTooLarge(Exception):
    """The request body is over :data:`MAX_REQUEST_BYTES`."""


def _repo_root() -> Path:
    """The folder holding pyproject.toml, found by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _commit_sha() -> str:
    """The commit for /api/version: Vercel's value, then git, then ``unknown``."""
    env_sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = result.stdout.strip().lower()
    if result.returncode == 0 and _SHA_RE.match(sha):
        return sha
    return "unknown"


def _json_response(status: str, payload: dict[str, Any], headers: Headers | None = None) -> Response:
    """Encode ``payload`` as a JSON response with its length."""
    body = json.dumps(payload).encode("utf-8")
    response_headers: Headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        response_headers.extend(headers)
    return status, response_headers, body


def _html_response(status: str, html: str, headers: Headers | None = None) -> Response:
    """Encode an HTML document as a response with its length."""
    body = html.encode("utf-8")
    response_headers: Headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        response_headers.extend(headers)
    return status, response_headers, body


def _index() -> Response:
    """GET /: the form page."""
    return _html_response("200 OK", render_page())


def _health() -> Response:
    """GET /api/health: a plain liveness check."""
    return _json_response("200 OK", {"status": "ok", "python": platform.python_version()})


def _version() -> Response:
    """GET /api/version: the package version and the current commit."""
    return _json_response("200 OK", {"version": __version__, "commit": _commit_sha()})


def _generate_response(environ: dict[str, Any]) -> Response:
    """POST /api/generate: validate one form body, run it and show the result."""
    try:
        body = _read_form_body(environ)
    except _BodyTooLarge:
        return _html_response(
            "413 Request Entity Too Large",
            render_message("Request too large", TOO_LARGE_MESSAGE),
        )
    except OSError:
        traceback.print_exc()
        return _html_response(
            "500 Internal Server Error",
            render_message("Generation failed", FAILED_MESSAGE),
        )

    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    try:
        form = parse_form(values)
    except FormError as exc:
        return _html_response(
            "400 Bad Request",
            render_message("Check the form", str(exc)),
        )

    try:
        result = generate(form)
    except GenerationBusy as exc:
        return _html_response(
            "503 Service Unavailable",
            render_message("Generator busy", str(exc)),
            [("Retry-After", "60")],
        )
    except GenerationFailed as exc:
        return _html_response(
            "500 Internal Server Error",
            render_message("Generation failed", str(exc)),
        )
    except Exception:  # the last line of defence: never show a traceback
        traceback.print_exc()
        return _html_response(
            "500 Internal Server Error",
            render_message("Generation failed", FAILED_MESSAGE),
        )

    return _html_response("200 OK", render_results(result))


def _read_form_body(environ: dict[str, Any]) -> bytes:
    """Read an urlencoded body, refusing anything over the size limit."""
    raw_length = environ.get("CONTENT_LENGTH")
    try:
        length = int(str(raw_length)) if raw_length not in (None, "") else None
    except (TypeError, ValueError):
        length = None
    if length is not None and length < 0:
        length = None
    if length is not None and length > MAX_REQUEST_BYTES:
        raise _BodyTooLarge

    stream = environ.get("wsgi.input")
    if stream is None:
        return b""
    limit = MAX_REQUEST_BYTES + 1
    data = stream.read(limit if length is None else min(length, limit))
    if len(data) > MAX_REQUEST_BYTES:
        raise _BodyTooLarge
    return data


_GET_ROUTES: dict[str, Callable[[], Response]] = {
    "/": _index,
    "/api/health": _health,
    "/api/version": _version,
}
_POST_ROUTES: dict[str, Callable[[dict[str, Any]], Response]] = {
    "/api/generate": _generate_response,
}


def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    """Serve the form, the status routes and generation as a WSGI application."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = environ.get("PATH_INFO") or "/"

    post_handler = _POST_ROUTES.get(path)
    if post_handler is not None:
        if method != "POST":
            status, headers, body = _json_response(
                "405 Method Not Allowed",
                {"error": "method not allowed"},
                [("Allow", "POST")],
            )
        else:
            status, headers, body = post_handler(environ)
    else:
        handler = _GET_ROUTES.get(path)
        if handler is None:
            status, headers, body = _json_response(
                "404 Not Found", {"error": "not found"}
            )
        elif method != "GET":
            status, headers, body = _json_response(
                "405 Method Not Allowed",
                {"error": "method not allowed"},
                [("Allow", "GET")],
            )
        else:
            status, headers, body = handler()

    start_response(status, headers)
    return [body]
