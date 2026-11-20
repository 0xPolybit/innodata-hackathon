"""Tests for form validation, the canonical config and one real web generation."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

import taskfactory.web.app as web_app
from taskfactory.web import forms
from taskfactory.web import generate as generate_module
from taskfactory.web.app import application
from taskfactory.web.build_config import DIFFICULTY_SETTINGS, build_config, canonical_toml
from taskfactory.web.generate import (
    BUSY_MESSAGE,
    FAILED_MESSAGE,
    OUT_OF_MEMORY_MESSAGE,
    QUOTA_MESSAGE,
    TIMEOUT_MESSAGE,
    CheckOutcome,
    GenerationBusy,
    GenerationFailed,
    GenerationQuotaExceeded,
    GenerationResult,
    TaskSummary,
    generate,
)
from taskfactory.web.results_summary import render_results

DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CHECK_NAMES = (
    "1_schema",
    "2_layout",
    "3_ambiguity",
    "7_redraw",
    "4_ocr",
    "5_pixels",
    "6_counterfactual",
)


def _payload(**overrides: Any) -> dict[str, Any]:
    """The default form payload with overrides applied."""
    payload = forms.default_form_payload()
    payload.update(overrides)
    return payload


def _call(
    method: str,
    path: str,
    body: bytes = b"",
    content_type: str = "application/x-www-form-urlencoded",
) -> tuple[int, dict[str, str], bytes]:
    """Call the WSGI app with an optional request body."""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ: dict[str, Any] = {"REQUEST_METHOD": method, "PATH_INFO": path}
    if body:
        environ["wsgi.input"] = io.BytesIO(body)
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = content_type
    response = b"".join(application(environ, start_response))
    return int(captured["status"].split()[0]), dict(captured["headers"]), response


def _form_body(**overrides: Any) -> bytes:
    """An urlencoded default form body with overrides applied."""
    return urlencode(_payload(**overrides), doseq=True).encode("utf-8")


def _fake_checks(*, failed: bool = False, reason: str = "pixels differ") -> tuple[CheckOutcome, ...]:
    """Seven check outcomes, the last one failed when ``failed`` is true."""
    outcomes = []
    for name in CHECK_NAMES:
        passed = not (failed and name == CHECK_NAMES[-1])
        outcomes.append(
            CheckOutcome(name=name, passed=passed, reason="" if passed else reason)
        )
    return tuple(outcomes)


def _fake_result(
    task_id: str = "bar-tourism-000000-value_lookup",
    reason: str = "pixels differ",
) -> GenerationResult:
    """A result with one accepted and one rejected task, for route tests."""
    accepted = TaskSummary(
        task_id=task_id,
        family="bar",
        question_type="value_lookup",
        domain="tourism",
        checks=_fake_checks(),
        spec_sha256="a" * 64,
    )
    rejected = TaskSummary(
        task_id="line-tourism-000000-series_at_x",
        family="line",
        question_type="series_at_x",
        domain="tourism",
        checks=_fake_checks(failed=True, reason=reason),
        spec_sha256="b" * 64,
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
    )


def _tesseract_command() -> str | None:
    """The executable the OCR check would use, or None when there is none."""
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd:
        return env_cmd
    if Path(DEFAULT_TESSERACT_CMD).is_file():
        return DEFAULT_TESSERACT_CMD
    return shutil.which("tesseract")


TESSERACT_CMD = _tesseract_command()


def test_parse_form_defaults() -> None:
    parsed = forms.parse_form(forms.default_form_payload())

    assert parsed.seed == 20261206
    assert parsed.charts_per_type == 3
    assert parsed.chart_types == ("bar", "line")
    assert parsed.question_types == (
        "value_lookup",
        "extremum",
        "rank_k",
        "pair_compare",
        "series_at_x",
    )
    assert parsed.topic == "tourism"
    assert parsed.difficulty == "standard"
    assert parsed.question_in_image is True
    assert parsed.task_count == 15


def test_parse_form_missing_fields_use_defaults() -> None:
    parsed = forms.parse_form({})

    assert parsed.seed == 20261206
    assert parsed.charts_per_type == 3
    assert parsed.task_count == 15
    # A checkbox that is not in the body is off.
    assert parsed.question_in_image is False


@pytest.mark.parametrize("seed", ["abc", "", "0", "-1", "1.5", "2147483648"])
def test_parse_form_bad_seed_message(seed: str) -> None:
    with pytest.raises(forms.FormError) as error:
        forms.parse_form(_payload(seed=seed))

    assert str(error.value) == forms.SEED_MESSAGE
    assert error.value.message == forms.SEED_MESSAGE


@pytest.mark.parametrize("charts", ["abc", "", "0", "7", "-1", "2.5"])
def test_parse_form_bad_charts_message(charts: str) -> None:
    with pytest.raises(forms.FormError) as error:
        forms.parse_form(_payload(charts_per_type=charts))

    assert str(error.value) == forms.CHARTS_MESSAGE


@pytest.mark.parametrize("field", ["chart_types", "question_types"])
def test_parse_form_requires_a_choice(field: str) -> None:
    with pytest.raises(forms.FormError) as error:
        forms.parse_form(_payload(**{field: []}))

    assert str(error.value) == forms.CHOICE_MESSAGE


def test_parse_form_refuses_thirty_tasks() -> None:
    payload = _payload(charts_per_type="6")
    assert forms.planned_task_count(
        payload["chart_types"], payload["question_types"], 6
    ) == 30

    with pytest.raises(forms.FormError) as error:
        forms.parse_form(payload)

    assert str(error.value) == (
        "This choice makes 30 tasks; the limit is 24. "
        "Choose fewer charts or question types."
    )


def test_parse_form_refuses_twenty_five_tasks() -> None:
    with pytest.raises(forms.FormError) as error:
        forms.parse_form(_payload(charts_per_type="5"))

    assert "This choice makes 25 tasks" in str(error.value)


def test_parse_form_allows_exactly_twenty_four_tasks() -> None:
    parsed = forms.parse_form(
        _payload(
            charts_per_type="6",
            question_types=["value_lookup", "extremum", "rank_k", "pair_compare"],
        )
    )

    assert parsed.task_count == 24


def test_parse_form_ignores_types_of_another_chart() -> None:
    bar_only = forms.parse_form(_payload(chart_types=["bar"]))
    line_only = forms.parse_form(_payload(chart_types=["line"]))
    no_bar_types = forms.parse_form(
        _payload(chart_types=["bar"], question_types=["series_at_x"])
    )
    no_line_types = forms.parse_form(
        _payload(
            chart_types=["line"],
            question_types=["value_lookup", "extremum", "rank_k", "pair_compare"],
        )
    )

    assert bar_only.task_count == 12
    assert line_only.task_count == 3
    assert no_bar_types.task_count == 0
    assert no_line_types.task_count == 0


def test_parse_form_unknown_values_fall_back() -> None:
    parsed = forms.parse_form(
        _payload(topic="space", difficulty="extreme", chart_types=["pie"])
    )

    assert parsed.topic == "tourism"
    assert parsed.difficulty == "standard"
    # An unknown-only chart list is not a usable choice.
    assert parsed.chart_types == ("bar", "line")


def test_parse_form_question_in_image() -> None:
    payload = _payload()
    assert forms.parse_form(payload).question_in_image is True

    payload.pop("question_in_image")
    assert forms.parse_form(payload).question_in_image is False


def test_build_config_is_byte_identical() -> None:
    parsed = forms.parse_form(forms.default_form_payload())

    first = build_config(parsed)
    second = build_config(parsed)

    assert first.toml.encode("utf-8") == second.toml.encode("utf-8")
    assert first.run_id == second.run_id
    assert first.run_id.startswith("ui-")
    assert len(first.run_id) == len("ui-") + 8
    assert canonical_toml(parsed) == first.toml


def test_build_config_changes_with_the_seed() -> None:
    first = build_config(forms.parse_form(_payload(seed="20261206")))
    second = build_config(forms.parse_form(_payload(seed="20261207")))

    assert first.toml != second.toml
    assert first.run_id != second.run_id


def test_build_config_harder_uses_the_plan_values() -> None:
    standard = build_config(forms.parse_form(forms.default_form_payload()))
    harder = build_config(forms.parse_form(_payload(difficulty="harder")))

    assert DIFFICULTY_SETTINGS["harder"] == {
        "ambiguity_min_margin": "0.02",
        "min_font_px": "7",
        "near_dup_phash_max": "6",
        "bar_max_categories": "12",
    }
    assert "ambiguity_min_margin = 0.02" in harder.toml
    assert "min_font_px = 7" in harder.toml
    assert "bar_max_categories = 12" in harder.toml
    assert "ambiguity_min_margin = 0.05" in standard.toml
    assert "bar_max_categories = 8" in standard.toml
    assert harder.run_id != standard.run_id


def test_fast_generation_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = forms.parse_form(
        _payload(
            charts_per_type="1",
            chart_types=["bar"],
            question_types=["value_lookup", "extremum", "rank_k", "pair_compare"],
        )
    )
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args: Any, **kwargs: Any) -> str:
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr(generate_module.tempfile, "mkdtemp", recording_mkdtemp)
    before = {name: os.environ.get(name) for name in ("MPLCONFIGDIR", "TMPDIR")}

    first = generate(parsed)
    second = generate(parsed)

    after = {name: os.environ.get(name) for name in ("MPLCONFIGDIR", "TMPDIR")}
    assert after == before

    assert first.run_id == second.run_id
    assert first.attempted == second.attempted == parsed.task_count == 4
    assert first.accepted + first.rejected == first.attempted
    assert [task.task_id for task in first.accepted_tasks] == [
        task.task_id for task in second.accepted_tasks
    ]
    assert [task.spec_sha256 for task in first.accepted_tasks] == [
        task.spec_sha256 for task in second.accepted_tasks
    ]
    assert [task.task_id for task in first.rejected_tasks] == [
        task.task_id for task in second.rejected_tasks
    ]
    if TESSERACT_CMD is not None:
        assert first.accepted_tasks

    create_dirs = [path for path in created if path.name.startswith("tf-")]
    assert len(create_dirs) == 2
    assert all(not path.exists() for path in create_dirs)


def test_generate_passes_the_commit_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = forms.parse_form(forms.default_form_payload())
    captured: dict[str, Any] = {}
    commit = "d" * 40

    def fake_pipeline(
        config_path: Path, out_root: Path, run_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        captured["git_sha"] = kwargs.get("git_sha")
        (out_root / "tasks").mkdir()
        (out_root / "rejected").mkdir()
        return {"generated": 0, "passed": 0, "rejected": 0, "yield": 0.0}

    monkeypatch.setattr(generate_module, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(generate_module, "_commit_sha", lambda: commit)

    result = generate(parsed)

    assert captured["git_sha"] == commit
    assert result.commit == commit


def test_generation_lock_is_exclusive() -> None:
    parsed = forms.parse_form(forms.default_form_payload())
    generate_module.GENERATION_LOCK.acquire()
    try:
        with pytest.raises(GenerationBusy) as error:
            generate(parsed)
    finally:
        generate_module.GENERATION_LOCK.release()

    assert str(error.value) == BUSY_MESSAGE
    assert "minute" in str(error.value)


def test_generation_times_out_and_keeps_the_lock_until_the_worker_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = forms.parse_form(forms.default_form_payload())
    release = threading.Event()

    def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        release.wait(5)
        return {"generated": 0, "passed": 0, "rejected": 0, "yield": 0.0}

    monkeypatch.setattr(generate_module, "run_pipeline", slow)
    monkeypatch.setattr(generate_module, "TIMEOUT_SECONDS", 0.05)

    try:
        with pytest.raises(GenerationFailed) as error:
            generate(parsed)
        assert str(error.value) == TIMEOUT_MESSAGE
        assert "300 second limit" in str(error.value)

        # The worker is still running and cannot be killed, so it still owns
        # the process-wide lock.
        with pytest.raises(GenerationBusy):
            generate(parsed)
    finally:
        release.set()

    deadline = time.monotonic() + 10
    while not generate_module.GENERATION_LOCK.acquire(blocking=False):
        assert time.monotonic() < deadline, "worker never released the lock"
        time.sleep(0.01)
    generate_module.GENERATION_LOCK.release()


def test_generation_out_of_memory_uses_the_section_9_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = forms.parse_form(forms.default_form_payload())

    def out_of_memory(*args: Any, **kwargs: Any) -> None:
        raise MemoryError

    monkeypatch.setattr(generate_module, "run_pipeline", out_of_memory)

    with pytest.raises(GenerationFailed) as error:
        generate(parsed)

    assert str(error.value) == OUT_OF_MEMORY_MESSAGE


def test_forced_failure_prints_only_the_class_and_run_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "env-secret-value-123"
    payload = _payload(seed="123456789")
    parsed = forms.parse_form(payload)
    monkeypatch.setenv("GEMINI_API_KEY", secret)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"used {secret} with seed {payload['seed']}")

    monkeypatch.setattr("taskfactory.pipeline.run_pipeline", fail)

    with pytest.raises(GenerationFailed):
        generate(parsed)

    err = capsys.readouterr().err
    expected = f"taskfactory web: RuntimeError run={build_config(parsed).run_id}"
    assert [line for line in err.splitlines() if line] == [expected]
    assert secret not in err
    assert str(payload["seed"]) not in err


def test_generation_quota_error_shows_the_section_9_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def quota(form: forms.ParsedForm) -> None:
        raise GenerationQuotaExceeded(QUOTA_MESSAGE)

    monkeypatch.setattr(web_app, "generate", quota)
    status, _, body = _call("POST", "/api/generate", _form_body())
    page = body.decode("utf-8")

    assert status == 503
    assert QUOTA_MESSAGE in page
    assert "Traceback" not in page


def test_generation_cleans_up_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parsed = forms.parse_form(forms.default_form_payload())
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args: Any, **kwargs: Any) -> str:
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(generate_module.tempfile, "mkdtemp", recording_mkdtemp)
    monkeypatch.setattr("taskfactory.pipeline.run_pipeline", fail)

    with pytest.raises(GenerationFailed) as error:
        generate(parsed)

    assert str(error.value) == FAILED_MESSAGE
    temp_dirs = [path for path in created if path.name.startswith("tf-")]
    assert temp_dirs and not temp_dirs[0].exists()
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "run=ui-" in err
    assert "Traceback" not in err
    assert "pipeline exploded" not in err


def test_post_bad_seed_returns_400() -> None:
    status, headers, body = _call("POST", "/api/generate", _form_body(seed="abc"))
    page = body.decode("utf-8")

    assert status == 400
    assert headers["Content-Type"].startswith("text/html")
    assert forms.SEED_MESSAGE in page
    assert 'href="/"' in page
    assert "<script" not in page.lower()


def test_post_no_question_type_returns_400() -> None:
    # The form sends an empty value for an unchecked group.
    status, _, body = _call("POST", "/api/generate", _form_body(question_types=[""]))
    page = body.decode("utf-8")

    assert status == 400
    assert forms.CHOICE_MESSAGE in page


def test_post_busy_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(form: Any) -> None:
        raise GenerationBusy(BUSY_MESSAGE)

    monkeypatch.setattr(web_app, "generate", busy)
    status, headers, body = _call("POST", "/api/generate", _form_body())

    assert status == 503
    assert headers["Retry-After"] == "60"
    assert BUSY_MESSAGE in body.decode("utf-8")


def test_post_generation_failure_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(form: Any) -> None:
        raise GenerationFailed(FAILED_MESSAGE)

    monkeypatch.setattr(web_app, "generate", fail)
    status, _, body = _call("POST", "/api/generate", _form_body())
    page = body.decode("utf-8")

    assert status == 500
    assert FAILED_MESSAGE in page
    assert "Traceback" not in page


def test_post_too_large_returns_413() -> None:
    status, headers, body = _call("POST", "/api/generate", b"x" * 4097)
    page = body.decode("utf-8")

    assert status == 413
    assert headers["Content-Type"].startswith("text/html")
    assert web_app.TOO_LARGE_MESSAGE in page
    assert 'href="/"' in page


def test_post_repeated_scalar_field_returns_400() -> None:
    status, _, body = _call(
        "POST", "/api/generate", _form_body() + b"&seed=20261207"
    )
    page = body.decode("utf-8")

    assert status == 400
    assert forms.REPEATED_FIELD_MESSAGE in page
    assert 'href="/"' in page
    assert "Traceback" not in page


def test_post_unknown_field_returns_400() -> None:
    status, _, body = _call("POST", "/api/generate", _form_body(unexpected="1"))
    page = body.decode("utf-8")

    assert status == 400
    assert forms.UNKNOWN_FIELD_MESSAGE in page
    assert "Traceback" not in page


def test_post_long_value_returns_400() -> None:
    status, _, body = _call(
        "POST", "/api/generate", _form_body(topic="x" * 201)
    )
    page = body.decode("utf-8")

    assert status == 400
    assert forms.LONG_VALUE_MESSAGE in page
    assert "Traceback" not in page


def test_parse_form_seed_keeps_accepting_a_leading_plus_and_spaces() -> None:
    # Section 3 of the plan gives a range, not a syntax rule, and says nothing
    # about a leading plus or spaces, so the existing behaviour is kept.
    assert forms.parse_form(_payload(seed=" +20261206 ")).seed == 20261206
    assert forms.parse_form(_payload(seed="+7")).seed == 7


FORBIDDEN_KEY_TEXT = (
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "AIza",
    "sk-or-",
    "api_key",
)


def _assert_no_key_text(body: bytes, label: str) -> None:
    """No response body may carry a key name, a key prefix or ``api_key``."""
    text = body.decode("utf-8", "replace").lower()
    for token in FORBIDDEN_KEY_TEXT:
        assert token.lower() not in text, f"{label} contains {token}"


def test_every_response_body_is_free_of_key_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labelled_bodies: list[tuple[str, bytes]] = []

    for path, expected in (
        ("/", 200),
        ("/about", 200),
        ("/sample/", 200),
        ("/missing", 404),
    ):
        status, _, body = _call("GET", path)
        assert status == expected, path
        labelled_bodies.append((f"GET {path}", body))

    status, _, body = _call("GET", "/api/generate")
    assert status == 405
    labelled_bodies.append(("GET /api/generate 405", body))

    status, _, body = _call("POST", "/api/generate", _form_body(seed="abc"))
    assert status == 400
    labelled_bodies.append(("POST bad input 400", body))

    status, _, body = _call("POST", "/api/generate", b"x" * 4097)
    assert status == 413
    labelled_bodies.append(("POST /api/generate 413", body))

    monkeypatch.setattr(web_app, "generate", lambda form: _fake_result())
    status, _, body = _call("POST", "/api/generate", _form_body())
    assert status == 200
    labelled_bodies.append(("POST /api/generate 200", body))

    def busy(form: forms.ParsedForm) -> None:
        raise GenerationBusy(BUSY_MESSAGE)

    monkeypatch.setattr(web_app, "generate", busy)
    status, _, body = _call("POST", "/api/generate", _form_body())
    assert status == 503
    labelled_bodies.append(("POST /api/generate 503", body))

    def fail(form: forms.ParsedForm) -> None:
        raise GenerationFailed(FAILED_MESSAGE)

    monkeypatch.setattr(web_app, "generate", fail)
    status, _, body = _call("POST", "/api/generate", _form_body())
    assert status == 500
    labelled_bodies.append(("POST /api/generate 500", body))

    for label, page in labelled_bodies:
        _assert_no_key_text(page, label)


def test_get_generate_is_not_allowed() -> None:
    status, headers, body = _call("GET", "/api/generate")

    assert status == 405
    assert headers["Allow"] == "POST"
    assert b"method not allowed" in body


def test_post_success_renders_the_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app, "generate", lambda form: _fake_result())

    status, headers, body = _call("POST", "/api/generate", _form_body())
    page = body.decode("utf-8")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert "TaskFactory results" in page
    assert "ui-1234abcd" in page
    assert "20261206" in page
    assert "7 of 7 checks passed" in page
    assert "6_counterfactual" in page
    assert "pixels differ" in page
    assert "Back to the form" in page
    assert "<script" not in page.lower()


def test_results_html_escapes_text() -> None:
    result = _fake_result(task_id="<script>alert(1)</script>", reason="<b>bad</b>")
    page = render_results(result)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;b&gt;bad&lt;/b&gt;" in page


def test_results_and_config_hold_no_key_text() -> None:
    page = render_results(_fake_result())
    config = build_config(forms.parse_form(forms.default_form_payload())).toml

    for text in (page, config):
        lowered = text.lower()
        assert "gemini" not in lowered
        assert "openrouter" not in lowered
        assert "api_key" not in lowered


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("TF_SLOW_TESTS") != "1",
    reason="set TF_SLOW_TESTS=1 to run the two full default generations",
)
def test_default_generation_is_deterministic() -> None:
    parsed = forms.parse_form(forms.default_form_payload())

    first = generate(parsed)
    second = generate(parsed)

    assert first.run_id == second.run_id
    assert first.attempted == first.accepted + first.rejected
    # The form plans 15 slots. The pipeline attempts a slot only when its
    # question clears the margin: at this seed bar spec 1's rank_k question is
    # skipped, so the real run attempts 14. The cap still uses the planned 15.
    assert first.attempted <= parsed.task_count
    assert [task.task_id for task in first.accepted_tasks] == [
        task.task_id for task in second.accepted_tasks
    ]
    assert [task.spec_sha256 for task in first.accepted_tasks] == [
        task.spec_sha256 for task in second.accepted_tasks
    ]
    assert [task.spec_sha256 for task in first.rejected_tasks] == [
        task.spec_sha256 for task in second.rejected_tasks
    ]
