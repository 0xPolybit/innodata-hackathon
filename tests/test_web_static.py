"""Tests for the container's read-only static routes: ``/about`` and ``/sample/...``.

The WSGI app is called directly, so these tests start no server and read the
committed files under ``site/``.
"""

from __future__ import annotations

import json
from typing import Any

from taskfactory.web.app import application


def call(method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    """Call the WSGI app directly and return the status, headers and body."""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ = {"REQUEST_METHOD": method, "PATH_INFO": path}
    body = b"".join(application(environ, start_response))
    return int(captured["status"].split()[0]), dict(captured["headers"]), body


def test_sample_index_is_served() -> None:
    status, headers, body = call("GET", "/sample/")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"Static report" in body


def test_sample_selftest_json_is_served() -> None:
    status, headers, body = call("GET", "/sample/selftest.json")

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["clean_total"] == 20


def test_sample_image_has_its_media_type() -> None:
    status, headers, body = call("GET", "/sample/examples/extremum.png")

    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body.startswith(b"\x89PNG")


def test_sample_redirects_to_slash() -> None:
    status, headers, body = call("GET", "/sample")

    assert status == 301
    assert headers["Location"] == "/sample/"
    assert body == b""


def test_sample_traversal_is_not_found() -> None:
    for path in (
        "/sample/../../pyproject.toml",
        "/sample/../index.html",
        "/sample/%2e%2e/%2e%2e/pyproject.toml",
    ):
        status, headers, body = call("GET", path)

        assert status == 404, path
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body) == {"error": "not found"}


def test_missing_sample_file_is_not_found() -> None:
    status, _, body = call("GET", "/sample/no-such-file.txt")

    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_about_serves_the_landing_page() -> None:
    status, headers, body = call("GET", "/about")
    page = body.decode("utf-8")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "<title>TaskFactory" in page
    assert 'href="sample/index.html"' in page


def test_about_sample_link_target_is_served() -> None:
    """At /about the relative link resolves to /sample/index.html."""
    status, headers, body = call("GET", "/sample/index.html")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"Static report" in body


def test_unknown_static_name_is_not_found() -> None:
    status, _, body = call("GET", "/about/")

    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_post_to_about_is_not_allowed() -> None:
    status, headers, body = call("POST", "/about")

    assert status == 405
    assert headers["Allow"] == "GET"
    assert "error" in json.loads(body)
