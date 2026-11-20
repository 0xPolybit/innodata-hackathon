"""The TaskFactory WSGI application: the form page, the status routes and generation."""

from __future__ import annotations

import inspect
import json
import mimetypes
import os
import platform
import re
import subprocess
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from taskfactory import __version__
from taskfactory.web.forms import FormError, ParsedForm, parse_form
from taskfactory.web.generate import (
    FAILED_MESSAGE,
    GenerationBusy,
    GenerationFailed,
    GenerationResult,
    generate,
)
from taskfactory.web.render_page import render_page
from taskfactory.web.results_page import render_results_page
from taskfactory.web.results_summary import render_message
from taskfactory.web.zip_bundle import build_zip

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


def _not_found() -> Response:
    """The JSON 404 every missing route and missing static file returns."""
    return _json_response("404 Not Found", {"error": "not found"})


def _site_dir() -> Path:
    """The committed static site folder beside the package."""
    return _repo_root() / "site"


def _sample_dir() -> Path:
    """The sample report folder the container serves under ``/sample/``."""
    return _site_dir() / "sample"


def _static_path(path: str) -> bool:
    """True for the two static namespaces: ``/about`` and ``/sample/...``."""
    return path == "/about" or path == "/sample" or path.startswith("/sample/")


def _content_type(path: Path) -> str:
    """A file's media type from its name, with a charset for text formats."""
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in {
        "application/json",
        "application/javascript",
    }:
        return f"{guessed}; charset=utf-8"
    return guessed


def _file_response(path: Path, root: Path) -> Response:
    """Serve one file's exact bytes, or 404 when it is missing or outside ``root``.

    The path is resolved before it is compared with the root, so ``..`` and a
    symlink that points out of the folder both become a 404.
    """
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return _not_found()
    if not resolved.is_file():
        return _not_found()
    try:
        body = resolved.read_bytes()
    except OSError:
        return _not_found()
    return (
        "200 OK",
        [
            ("Content-Type", _content_type(resolved)),
            ("Content-Length", str(len(body))),
        ],
        body,
    )


def _sample_response(path: str) -> Response:
    """GET /sample/...: a file under ``site/sample/``, never one outside it."""
    root = _sample_dir()
    relative = unquote(path[len("/sample/") :]).replace("\x00", "")
    if not relative or relative.endswith("/"):
        relative += "index.html"
    candidate = root / relative
    try:
        if candidate.is_dir():
            candidate = candidate / "index.html"
    except OSError:
        return _not_found()
    return _file_response(candidate, root)


def _static_response(path: str) -> Response:
    """The static route response for ``/about`` and ``/sample/...``."""
    if path == "/about":
        return _file_response(_site_dir() / "index.html", _site_dir())
    if path == "/sample":
        return (
            "301 Moved Permanently",
            [
                ("Location", "/sample/"),
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", "0"),
            ],
            b"",
        )
    return _sample_response(path)


class _Respond(Exception):
    """Stop a route and return the error response this carries."""

    def __init__(self, response: Response) -> None:
        super().__init__("response ready")
        self.response = response


def _generate_response(environ: dict[str, Any]) -> Response:
    """POST /api/generate: validate one form body, run it and show the result."""
    try:
        form, result = _run_form(environ)
    except _Respond as stop:
        return stop.response
    return _html_response("200 OK", render_results_page(result, form))


def _zip_response(environ: dict[str, Any]) -> Response:
    """POST /api/zip: run the same form again and return the run as a ZIP."""
    try:
        form, result = _run_form(environ)
    except _Respond as stop:
        return stop.response

    try:
        data = build_zip(result.artifacts)
    except Exception:  # never show a traceback
        traceback.print_exc()
        return _html_response(
            "500 Internal Server Error",
            render_message("Generation failed", FAILED_MESSAGE),
        )

    filename = _zip_filename(result.run_id)
    return (
        "200 OK",
        [
            ("Content-Type", "application/zip"),
            ("Content-Length", str(len(data))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
        ],
        data,
    )


def _run_form(environ: dict[str, Any]) -> tuple[ParsedForm, GenerationResult]:
    """Read, validate and generate one request, or raise :class:`_Respond`.

    The section 9 status codes and messages live here once, so
    ``/api/generate`` and ``/api/zip`` cannot drift apart.
    """
    try:
        body = _read_form_body(environ)
    except _BodyTooLarge as exc:
        raise _Respond(
            _html_response(
                "413 Request Entity Too Large",
                render_message("Request too large", TOO_LARGE_MESSAGE),
            )
        ) from exc
    except OSError as exc:
        traceback.print_exc()
        raise _Respond(
            _html_response(
                "500 Internal Server Error",
                render_message("Generation failed", FAILED_MESSAGE),
            )
        ) from exc

    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    try:
        form = parse_form(values)
    except FormError as exc:
        raise _Respond(
            _html_response(
                "400 Bad Request",
                render_message("Check the form", str(exc)),
            )
        ) from exc

    try:
        result = _generate_with_artifacts(form)
    except GenerationBusy as exc:
        raise _Respond(
            _html_response(
                "503 Service Unavailable",
                render_message("Generator busy", str(exc)),
                [("Retry-After", "60")],
            )
        ) from exc
    except GenerationFailed as exc:
        raise _Respond(
            _html_response(
                "500 Internal Server Error",
                render_message("Generation failed", str(exc)),
            )
        ) from exc
    except Exception:  # the last line of defence: never show a traceback
        traceback.print_exc()
        raise _Respond(
            _html_response(
                "500 Internal Server Error",
                render_message("Generation failed", FAILED_MESSAGE),
            )
        ) from None
    return form, result


def _generate_with_artifacts(form: ParsedForm) -> GenerationResult:
    """Call :func:`generate` with ``keep_artifacts`` and return its result.

    A replacement that takes only the form is still called with only the form;
    the real generator always receives the option.
    """
    try:
        parameters = inspect.signature(generate).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    accepts_keep_artifacts = any(
        parameter.name == "keep_artifacts"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_keep_artifacts:
        return generate(form, keep_artifacts=True)
    return generate(form)


def _zip_filename(run_id: str) -> str:
    """A safe ``taskfactory-<run_id>.zip`` name for the download."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id).strip("._") or "run"
    return f"taskfactory-{safe}.zip"


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
    "/api/zip": _zip_response,
}


def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    """Serve the form, the status routes and generation as a WSGI application."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = environ.get("PATH_INFO") or "/"

    if _static_path(path):
        if method != "GET":
            status, headers, body = _json_response(
                "405 Method Not Allowed",
                {"error": "method not allowed"},
                [("Allow", "GET")],
            )
        else:
            status, headers, body = _static_response(path)
    else:
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
                status, headers, body = _not_found()
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
