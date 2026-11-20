"""Tests for the WSGI form app, the form defaults and the serve command."""

from __future__ import annotations

import io
import json
import re
import socket
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

import taskfactory.cli as cli
from taskfactory import __version__
from taskfactory.web import forms
from taskfactory.web.app import application
from taskfactory.web.generate import GenerationResult
from taskfactory.web.render_page import COLD_START_MESSAGE
from taskfactory.web.results_page import render_results_page

INPUT_NAMES = (
    "seed",
    "charts_per_type",
    "chart_types",
    "topic",
    "question_types",
    "difficulty",
    "question_in_image",
)


def call(
    method: str, path: str, body: bytes = b""
) -> tuple[int, dict[str, str], bytes]:
    """Call the WSGI app directly and return the status, headers and body."""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = status
        captured["headers"] = headers

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
    return int(captured["status"].split()[0]), dict(captured["headers"]), response


def _fast_payload() -> dict[str, Any]:
    """A one-chart, bar-only form with a retail topic."""
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
    return payload


def _quiet_result(seed: int) -> GenerationResult:
    """A run with no tasks, enough to render the results page."""
    return GenerationResult(
        run_id="ui-test0001",
        commit="c" * 40,
        seed=seed,
        attempted=0,
        accepted=0,
        rejected=0,
        yield_=0.0,
        elapsed_seconds=0.1,
        accepted_tasks=(),
        rejected_tasks=(),
        artifacts={},
    )


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


def test_index_prefills_the_form_from_the_query_string() -> None:
    status, _, body = call(
        "GET",
        "/?seed=7&charts_per_type=2&chart_types=bar&topic=retail&difficulty=harder",
    )
    page = body.decode("utf-8")

    assert status == 200
    assert re.search(r'<input[^>]*name="seed"[^>]*value="7"', page)
    assert re.search(r'<input[^>]*name="charts_per_type"[^>]*value="2"', page)
    assert 'name="chart_types" value="bar" checked' in page
    assert 'name="chart_types" value="line" checked' not in page
    assert 'name="topic" value="retail" checked' in page
    assert 'name="difficulty" value="harder" checked' in page


def test_index_falls_back_from_an_invalid_seed() -> None:
    status, _, body = call("GET", "/?seed=abc")
    page = body.decode("utf-8")

    assert status == 200
    assert 'value="20261206"' in page
    assert forms.SEED_MESSAGE not in page
    assert "Check the form" not in page


def test_index_falls_back_from_an_unknown_topic() -> None:
    status, _, body = call("GET", "/?topic=mars")
    page = body.decode("utf-8")

    assert status == 200
    assert 'name="topic" value="tourism" checked' in page
    assert 'name="topic" value="mars"' not in page


def test_index_prefills_question_types_and_the_image_toggle() -> None:
    status, _, body = call(
        "GET", "/?chart_types=bar&question_types=value_lookup&question_in_image=off"
    )
    page = body.decode("utf-8")

    assert status == 200
    assert 'name="question_types" value="value_lookup" checked' in page
    assert 'name="question_types" value="extremum" checked' not in page
    assert 'name="question_in_image" value="on" checked' not in page


def test_results_back_link_carries_the_submitted_settings() -> None:
    form = forms.parse_form(_fast_payload())
    page = render_results_page(_quiet_result(form.seed), form)

    match = re.search(r'<a class="btn btn-outline" href="([^"]*)">', page)
    assert match is not None
    parts = urlsplit(match.group(1))

    assert parts.path == "/"
    assert forms.parse_form(parse_qs(parts.query, keep_blank_values=True)) == form


def test_bad_form_back_link_is_plain_root() -> None:
    request = urlencode({**_fast_payload(), "seed": "abc"}, doseq=True).encode("utf-8")
    status, _, body = call("POST", "/api/generate", request)
    page = body.decode("utf-8")

    assert status == 400
    match = re.search(r'<a class="btn btn-outline" href="([^"]*)">', page)
    assert match is not None
    assert match.group(1) == "/"


def test_results_page_explains_that_the_zip_reruns_the_settings() -> None:
    form = forms.parse_form(_fast_payload())
    page = render_results_page(_quiet_result(form.seed), form)

    assert (
        "This re-runs the same settings to build the ZIP, so it takes about as "
        "long as the first run."
    ) in page


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


def test_serve_reports_a_port_in_use(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import waitress

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("waitress.serve must not be called")

    monkeypatch.setattr(waitress, "serve", fail)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        port = busy.getsockname()[1]
        assert cli.main(["serve", "--port", str(port)]) == 2

    err = capsys.readouterr().err
    assert "already in use" in err
    assert str(port) in err


def test_serve_binds_a_free_port(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import waitress

    calls: list[dict[str, Any]] = []

    def noop(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(waitress, "serve", noop)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    assert cli.main(["serve", "--port", str(port)]) == 0
    assert calls == [{"host": "127.0.0.1", "port": port}]
    assert "TaskFactory is running" in capsys.readouterr().out
