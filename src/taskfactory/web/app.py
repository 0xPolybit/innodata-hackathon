"""The TaskFactory WSGI application: the form page and the status routes."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from taskfactory import __version__
from taskfactory.web.render_page import render_page

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

Headers = list[tuple[str, str]]
Response = tuple[str, Headers, bytes]


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


def _html_response(status: str, html: str) -> Response:
    """Encode an HTML document as a response with its length."""
    body = html.encode("utf-8")
    return status, [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ], body


def _index() -> Response:
    """GET /: the form page."""
    return _html_response("200 OK", render_page())


def _health() -> Response:
    """GET /api/health: a plain liveness check."""
    return _json_response("200 OK", {"status": "ok", "python": platform.python_version()})


def _version() -> Response:
    """GET /api/version: the package version and the current commit."""
    return _json_response("200 OK", {"version": __version__, "commit": _commit_sha()})


_ROUTES: dict[str, Callable[[], Response]] = {
    "/": _index,
    "/api/health": _health,
    "/api/version": _version,
}


def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    """Serve the form page and the status routes as a WSGI application."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = environ.get("PATH_INFO") or "/"
    handler = _ROUTES.get(path)

    if handler is None:
        status, headers, body = _json_response("404 Not Found", {"error": "not found"})
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
