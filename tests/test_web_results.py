"""Tests for the results page, the ZIP bundle and their HTTP routes."""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

import taskfactory.web.app as web_app
import taskfactory.web.results_page as results_page
from taskfactory.web import forms
from taskfactory.web import generate as generate_module
from taskfactory.web.app import application
from taskfactory.web.generate import (
    RESULT_TOO_LARGE_MESSAGE,
    CheckOutcome,
    GenerationFailed,
    GenerationResult,
    TaskSummary,
    generate,
)
from taskfactory.web.results_page import render_results_page
from taskfactory.web.zip_bundle import build_zip

CHECK_NAMES = (
    "1_schema",
    "2_layout",
    "3_ambiguity",
    "7_redraw",
    "4_ocr",
    "5_pixels",
    "6_counterfactual",
)
PACKAGE_FILES = (
    "image.png",
    "spec.json",
    "task.json",
    "text_boxes.json",
    "validation.json",
    "manifest.json",
)
ROOT_FILES = (
    "tasks.jsonl",
    "validation.jsonl",
    "metrics.json",
    "run.json",
    "README.txt",
)


def _fast_payload(**overrides: Any) -> dict[str, Any]:
    """A one-chart, bar-only payload the fast tests can afford to generate."""
    payload = forms.default_form_payload()
    payload.update(
        {
            "charts_per_type": "1",
            "chart_types": ["bar"],
            "question_types": [
                "value_lookup",
                "extremum",
                "rank_k",
                "pair_compare",
            ],
        }
    )
    payload.update(overrides)
    return payload


def _fast_form() -> forms.ParsedForm:
    """The parsed fast payload: four planned bar tasks."""
    return forms.parse_form(_fast_payload())


def _form_body(**overrides: Any) -> bytes:
    """An urlencoded fast form body with overrides applied."""
    return urlencode(_fast_payload(**overrides), doseq=True).encode("utf-8")


def _call(
    method: str,
    path: str,
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    """Call the WSGI app with an optional request body."""
    captured: dict[str, Any] = {}

    def start_response(
        status: str, headers: list[tuple[str, str]], exc_info: Any = None
    ) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ: dict[str, Any] = {"REQUEST_METHOD": method, "PATH_INFO": path}
    if body:
        environ["wsgi.input"] = io.BytesIO(body)
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = "application/x-www-form-urlencoded"
    response = b"".join(application(environ, start_response))
    return int(captured["status"].split()[0]), dict(captured["headers"]), response


def _checks(*, failed: bool = False, reason: str = "pixels differ") -> tuple[CheckOutcome, ...]:
    """Seven outcomes, the last failed when ``failed`` is true."""
    return tuple(
        CheckOutcome(
            name=name,
            passed=not (failed and name == CHECK_NAMES[-1]),
            reason="" if not (failed and name == CHECK_NAMES[-1]) else reason,
        )
        for name in CHECK_NAMES
    )


def _fake_result(artifacts: dict[str, bytes] | None = None) -> GenerationResult:
    """One accepted task and one rejected task, for page and route tests."""
    accepted = TaskSummary(
        task_id="bar-tourism-000000-value_lookup",
        family="bar",
        question_type="value_lookup",
        domain="tourism",
        checks=_checks(),
    )
    rejected = TaskSummary(
        task_id="bar-tourism-000000-rank_k",
        family="bar",
        question_type="rank_k",
        domain="tourism",
        checks=_checks(failed=True),
    )
    return GenerationResult(
        run_id="ui-1234abcd",
        commit="c" * 40,
        seed=20261206,
        attempted=2,
        accepted=1,
        rejected=1,
        yield_=0.5,
        elapsed_seconds=1.25,
        accepted_tasks=(accepted,),
        rejected_tasks=(rejected,),
        artifacts=artifacts or {},
    )


@pytest.fixture(scope="module")
def fast_run() -> GenerationResult:
    """One real fast generation with its artifacts kept."""
    return generate(_fast_form(), keep_artifacts=True)


def test_results_page_shows_every_image_and_the_run_details(
    fast_run: GenerationResult,
) -> None:
    page = render_results_page(fast_run, _fast_form())

    expected_images = len(fast_run.accepted_tasks) + len(fast_run.rejected_tasks)
    assert page.count('<img src="data:image/png;base64,') == expected_images
    assert fast_run.run_id in page
    assert fast_run.commit in page
    assert "Seven checks" in page
    assert "Download ZIP" in page
    assert 'action="/api/zip"' in page
    assert "Back to the form" in page
    assert "<script" not in page.lower()
    for name in CHECK_NAMES:
        assert name in page


def test_results_page_escapes_a_crafted_question() -> None:
    accepted = TaskSummary(
        task_id="bar-tourism-000000-value_lookup",
        family="bar",
        question_type="value_lookup",
        domain="tourism",
        checks=_checks(),
    )
    artifacts = {
        "tasks/bar-tourism-000000-value_lookup/image.png": b"png",
        "tasks/bar-tourism-000000-value_lookup/task.json": json.dumps(
            {"question": "<b>x</b>", "answer": "<i>y</i>"}
        ).encode("utf-8"),
    }
    result = GenerationResult(
        run_id="ui-1234abcd",
        commit="c" * 40,
        seed=20261206,
        attempted=1,
        accepted=1,
        rejected=0,
        yield_=1.0,
        elapsed_seconds=0.5,
        accepted_tasks=(accepted,),
        rejected_tasks=(),
        artifacts=artifacts,
    )

    page = render_results_page(result, _fast_form())

    assert "<b>x</b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert "<i>y</i>" not in page
    assert "&lt;i&gt;y&lt;/i&gt;" in page


def test_results_page_hidden_fields_round_trip(fast_run: GenerationResult) -> None:
    page = render_results_page(fast_run, _fast_form())
    values: dict[str, list[str]] = {}
    for name, value in re.findall(
        r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page
    ):
        values.setdefault(name, []).append(value)

    assert forms.parse_form(values) == _fast_form()


def test_page_over_the_size_guard_shows_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(results_page, "MAX_PAGE_BYTES", 1)

    page = render_results_page(_fake_result(), _fast_form())

    assert RESULT_TOO_LARGE_MESSAGE in page
    assert "<script" not in page.lower()


def test_zip_contains_packages_indices_and_run_files(fast_run: GenerationResult) -> None:
    data = build_zip(fast_run.artifacts)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        for task in fast_run.accepted_tasks:
            for name in PACKAGE_FILES:
                assert f"tasks/{task.task_id}/{name}" in names
        for task in fast_run.rejected_tasks:
            for name in PACKAGE_FILES:
                assert f"rejected/{task.task_id}/{name}" in names
        for name in ROOT_FILES:
            assert name in names

        assert len(names) == 6 * fast_run.attempted + len(ROOT_FILES)

        info = json.loads(archive.read("run.json"))
        assert info["seed"] == fast_run.seed
        assert info["commit"] == fast_run.commit
        assert len(info["config_hash"]) == 64
        assert "versions" in info
        assert "tf diff" in archive.read("README.txt").decode("utf-8")

        for name in names:
            payload = archive.read(name).lower()
            assert b"gemini" not in payload
            assert b"openrouter" not in payload
            assert b"api_key" not in payload


def test_zip_keeps_a_rejected_folder() -> None:
    package = "rejected/bar-tourism-000000-rank_k"
    artifacts = {f"{package}/{name}": b"{}" for name in PACKAGE_FILES}
    artifacts[f"{package}/image.png"] = b"png"

    with zipfile.ZipFile(io.BytesIO(build_zip(artifacts))) as archive:
        names = set(archive.namelist())

    assert {f"{package}/{name}" for name in PACKAGE_FILES} == names


def test_zip_is_deterministic() -> None:
    first = generate(_fast_form(), keep_artifacts=True)
    second = generate(_fast_form(), keep_artifacts=True)

    assert build_zip(first.artifacts) == build_zip(second.artifacts)
    assert first.artifacts == second.artifacts


def test_size_budget_raises_and_keeps_cleaning_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args: Any, **kwargs: Any) -> str:
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr(generate_module.tempfile, "mkdtemp", recording_mkdtemp)
    monkeypatch.setattr(generate_module, "MAX_ARTIFACT_BYTES", 1)

    with pytest.raises(GenerationFailed) as error:
        generate(_fast_form(), keep_artifacts=True)

    assert str(error.value) == (
        "The result is too large to send. Choose fewer charts, or open the sample report."
    )
    assert str(error.value) == RESULT_TOO_LARGE_MESSAGE
    temp_dirs = [path for path in created if path.name.startswith("tf-")]
    assert temp_dirs
    assert all(not path.exists() for path in temp_dirs)


def test_post_zip_bad_seed_returns_400() -> None:
    status, headers, body = _call("POST", "/api/zip", _form_body(seed="abc"))
    page = body.decode("utf-8")

    assert status == 400
    assert headers["Content-Type"].startswith("text/html")
    assert forms.SEED_MESSAGE in page


def test_post_zip_too_large_returns_413() -> None:
    status, _, body = _call("POST", "/api/zip", b"x" * 4097)

    assert status == 413
    assert web_app.TOO_LARGE_MESSAGE in body.decode("utf-8")


def test_get_zip_is_405_json() -> None:
    status, headers, body = _call("GET", "/api/zip")

    assert status == 405
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Allow"] == "POST"
    assert json.loads(body) == {"error": "method not allowed"}


def test_post_zip_success_returns_the_attachment(
    monkeypatch: pytest.MonkeyPatch,
    fast_run: GenerationResult,
) -> None:
    def fake(form: forms.ParsedForm, keep_artifacts: bool = False) -> GenerationResult:
        return fast_run

    monkeypatch.setattr(web_app, "generate", fake)
    status, headers, body = _call("POST", "/api/zip", _form_body())

    assert status == 200
    assert headers["Content-Type"] == "application/zip"
    assert headers["Content-Disposition"] == (
        f'attachment; filename="taskfactory-{fast_run.run_id}.zip"'
    )
    assert headers["Content-Length"] == str(len(body))
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert "run.json" in archive.namelist()


def test_post_generate_fast_form_shows_the_download() -> None:
    status, headers, body = _call("POST", "/api/generate", _form_body())
    page = body.decode("utf-8")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "TaskFactory results" in page
    assert "Download ZIP" in page
    assert "data:image/png;base64," in page
    assert "<script" not in page.lower()


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("TF_SLOW_TESTS") != "1",
    reason="set TF_SLOW_TESTS=1 to run the full default generation",
)
def test_default_generation_has_a_page_and_a_zip() -> None:
    form = forms.parse_form(forms.default_form_payload())
    result = generate(form, keep_artifacts=True)

    assert result.attempted == result.accepted + result.rejected
    assert result.attempted <= form.task_count
    page = render_results_page(result, form)
    data = build_zip(result.artifacts)

    assert "Download ZIP" in page
    assert page.count('<img src="data:image/png;base64,') == (
        len(result.accepted_tasks) + len(result.rejected_tasks)
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "run.json" in names
        assert "README.txt" in names
        assert "metrics.json" in names

        expected = set(ROOT_FILES)
        for task in result.accepted_tasks:
            expected.update(f"tasks/{task.task_id}/{name}" for name in PACKAGE_FILES)
        for task in result.rejected_tasks:
            expected.update(
                f"rejected/{task.task_id}/{name}" for name in PACKAGE_FILES
            )
        assert set(names) == expected

    print(
        f"defaults run_id={result.run_id} attempted={result.attempted} "
        f"accepted={result.accepted} rejected={result.rejected} "
        f"yield={result.yield_} seconds={result.elapsed_seconds:.2f} "
        f"html_bytes={len(page.encode('utf-8'))} zip_bytes={len(data)} "
        f"images={page.count('<img src=')} zip_files={len(names)}"
    )
