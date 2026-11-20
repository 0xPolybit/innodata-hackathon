"""Tests for the WSGI form app, the form defaults and the serve command."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import taskfactory.cli as cli
from taskfactory import __version__
from taskfactory.web import forms
from taskfactory.web.app import application
from taskfactory.web.render_page import COLD_START_MESSAGE

INPUT_NAMES = (
    "seed",
    "charts_per_type",
    "chart_types",
    "topic",
    "question_types",
    "difficulty",
    "question_in_image",
)


def call(method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    """Call the WSGI app directly and return the status, headers and body."""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ = {"REQUEST_METHOD": method, "PATH_INFO": path}
    body = b"".join(application(environ, start_response))
    return int(captured["status"].split()[0]), dict(captured["headers"]), body


def test_index_page() -> None:
    status, headers, body = call("GET", "/")
    page = body.decode("utf-8")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "<title>TaskFactory</title>" in page
    for name in INPUT_NAMES:
        assert f'name="{name}"' in page

    assert 'value="20261206"' in page
    assert 'name="chart_types" value="bar" checked' in page
    assert 'name="chart_types" value="line" checked' in page
    assert 'name="topic" value="tourism" checked' in page
    assert 'name="difficulty" value="standard" checked' in page

    lowered = page.lower()
    assert "<script" not in lowered
    assert "api_key" not in lowered
    assert "api key" not in lowered
    assert "gemini" not in lowered
    assert "openrouter" not in lowered


def test_index_shows_the_default_task_count() -> None:
    status, _, body = call("GET", "/")
    page = body.decode("utf-8")

    assert status == 200
    assert "About 15 tasks" in page
    assert forms.default_task_count() == 15


def test_index_task_count_comes_from_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(forms.FORM_DEFAULTS, "charts_per_type", 2)

    status, _, body = call("GET", "/")
    page = body.decode("utf-8")

    assert status == 200
    assert "About 10 tasks" in page
    assert "About 15 tasks" not in page


def test_index_shows_the_cold_start_note() -> None:
    status, _, body = call("GET", "/")
    page = body.decode("utf-8")

    assert status == 200
    assert COLD_START_MESSAGE in page
    assert "Starting the demo." in page


def test_health() -> None:
    status, headers, body = call("GET", "/api/health")
    payload = json.loads(body)

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert payload["status"] == "ok"
    assert "python" in payload


def test_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    status, _, body = call("GET", "/api/version")
    payload = json.loads(body)

    assert status == 200
    assert payload["version"] == __version__
    assert "commit" in payload
    assert payload["commit"] == "unknown" or re.fullmatch(r"[0-9a-f]{40}", payload["commit"])


def test_version_uses_vercel_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "a" * 40
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", sha)
    status, _, body = call("GET", "/api/version")

    assert status == 200
    assert json.loads(body)["commit"] == sha


def test_unknown_path() -> None:
    status, headers, body = call("GET", "/not-a-route")

    assert status == 404
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body) == {"error": "not found"}


def test_post_to_index_is_not_allowed() -> None:
    status, headers, body = call("POST", "/")

    assert status == 405
    assert headers["Content-Type"].startswith("application/json")
    assert "error" in json.loads(body)


def test_form_defaults() -> None:
    assert forms.FORM_DEFAULTS == {
        "seed": 20261206,
        "charts_per_type": 3,
        "chart_types": ["bar", "line"],
        "topic": "tourism",
        "question_types": [
            "value_lookup",
            "extremum",
            "rank_k",
            "pair_compare",
            "series_at_x",
        ],
        "difficulty": "standard",
        "question_in_image": True,
    }


def test_serve_defaults() -> None:
    args = cli.build_parser().parse_args(["serve"])

    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_serve_refuses_remote_host_without_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import waitress

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("waitress.serve must not be called")

    monkeypatch.setattr(waitress, "serve", fail)

    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "--allow-remote" in capsys.readouterr().err
