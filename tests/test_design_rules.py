"""Design-contract tests for the served TaskFactory pages.

These call the WSGI app directly, so no server is started. The generated
results page uses the same one-chart fast form the web tests use.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import pytest

from taskfactory.web import forms
from taskfactory.web.app import application
from taskfactory.web.theme import STYLESHEET

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "site" / "index.html"

# The patterns a design regression must not bring back. Case is folded before
# the comparison, so a capitalised variant is caught too.
FORBIDDEN = (
    "linear-gradient(",
    "radial-gradient(",
    "text-shadow",
    "box-shadow: 0 0 ",
    "animation: pulse",
    "infinite",
    "text-transform: uppercase",
    "<script",
)

# Emoji and the joiners that compose them. The SVG art and the system icons
# must carry the interface instead.
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\uFE0F\u200D]"
)


def _call(method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
    """Call the WSGI app and return the status and the response body."""
    captured: dict[str, Any] = {}

    def start_response(
        status: str, headers: list[tuple[str, str]], exc_info: Any = None
    ) -> None:
        captured["status"] = status

    parts = urlsplit(path)
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": parts.path,
        "QUERY_STRING": parts.query,
    }
    if body:
        environ["wsgi.input"] = io.BytesIO(body)
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = "application/x-www-form-urlencoded"
    response = b"".join(application(environ, start_response))
    return int(captured["status"].split()[0]), response


def _fast_payload(**overrides: Any) -> dict[str, Any]:
    """A one-chart bar form that generates in about a second."""
    payload = forms.default_form_payload()
    payload.update(
        {
            "seed": "7",
            "charts_per_type": "1",
            "chart_types": ["bar"],
            "topic": "retail",
            "question_types": ["value_lookup"],
            "difficulty": "standard",
            "question_in_image": "on",
        }
    )
    payload.update(overrides)
    return payload


@pytest.fixture(scope="module")
def pages() -> Iterator[dict[str, str]]:
    """The form, results, error and landing pages exactly as served."""
    form_status, form_body = _call("GET", "/")
    assert form_status == 200

    results_body = urlencode(_fast_payload(), doseq=True).encode("utf-8")
    results_status, results_page = _call("POST", "/api/generate", results_body)
    assert results_status == 200

    error_body = urlencode(_fast_payload(seed="abc"), doseq=True).encode("utf-8")
    error_status, error_page = _call("POST", "/api/generate", error_body)
    assert error_status == 400

    about_status, about_page = _call("GET", "/about")
    assert about_status == 200

    yield {
        "form": form_body.decode("utf-8"),
        "results": results_page.decode("utf-8"),
        "error": error_page.decode("utf-8"),
        "about": about_page.decode("utf-8"),
    }


@pytest.mark.parametrize("name", ("form", "results", "error", "about"))
def test_served_pages_have_no_slop_signs(pages: dict[str, str], name: str) -> None:
    page = pages[name]
    lowered = page.lower()

    for pattern in FORBIDDEN:
        assert pattern not in lowered, f"{name} page brought back {pattern!r}"
    match = EMOJI.search(page)
    assert match is None, f"{name} page has emoji {match.group()!r}"


def test_stylesheet_has_no_slop_signs() -> None:
    lowered = STYLESHEET.lower()

    for pattern in FORBIDDEN:
        assert pattern not in lowered, f"stylesheet brought back {pattern!r}"
    assert EMOJI.search(STYLESHEET) is None


def test_landing_mirrors_the_shared_stylesheet() -> None:
    html = LANDING.read_text(encoding="utf-8")
    start = html.index("/* Shared stylesheet")
    start = html.index("\n", start) + 1
    end = html.index("/* Landing-only styles follow. */")

    assert html[start:end].strip() == STYLESHEET.strip()


def test_served_pages_are_the_expected_ones(pages: dict[str, str]) -> None:
    assert "About 15 tasks" in pages["form"]
    assert "TaskFactory results" in pages["results"]
    assert "Check the form" in pages["error"]
    assert 'aria-current="page"' in pages["about"]
    assert 'href="/sample/"' in pages["about"]
