"""Tests for taskfactory.report: the static page, its escaping, its examples and its placeholders.

The pool and eval folders are small fakes written into tmp_path, in the layout ``tf run`` and
``tf eval`` leave behind. Nothing here runs a check or calls a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from taskfactory.cli import main
from taskfactory.report import HEADINGS, TITLE, _pct, _share_pct, build_report

HOSTILE_MODEL = "evil<model>&x"  # a model id with markup characters; its results file is not written


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _package(
    tasks: Path,
    name: str,
    task_type: str,
    question: str,
    answer: str,
    colour: tuple[int, int, int],
    checks: tuple[str, ...] = ("1_schema", "2_layout"),
) -> bytes:
    """Write one package folder with a picture of one colour, and return the picture's bytes."""
    folder = tasks / name
    folder.mkdir(parents=True)
    _write_json(
        folder / "task.json",
        {"answer": answer, "answer_category": answer, "question": question, "task_type": task_type},
    )
    _write_json(
        folder / "validation.json",
        {"checks": [{"check": check, "details": {}, "passed": True} for check in checks]},
    )
    Image.new("RGB", (48, 32), colour).save(folder / "image.png", format="PNG")
    return (folder / "image.png").read_bytes()


def _model(accuracy: float, provider: str, n_attempted: int, n_correct: int, stopped: str | None) -> dict[str, Any]:
    return {
        "accuracy": accuracy,
        "accuracy_by_family": {
            "bar": {"accuracy": accuracy, "n_correct": n_correct, "n_items_attempted": n_attempted},
        },
        "accuracy_by_task_type": {
            "extremum": {"accuracy": 0.9, "n_correct": 9, "n_items_attempted": 10},
            "value_lookup": {"accuracy": 1.0, "n_correct": 10, "n_items_attempted": 10},
        },
        "error_label_counts": {
            "empty": 0,
            "other": 0,
            "refusal_or_long": 0,
            "wrong_entity": n_attempted - n_correct,
            "wrong_value": 0,
        },
        "model_id": "",
        "n_correct": n_correct,
        "n_items_attempted": n_attempted,
        "n_items_in_run": 4,
        "n_items_not_attempted": 4 - n_attempted,
        "provider": provider,
        "provider_error_count": 0,
        "stopped_reason": stopped,
    }


@pytest.fixture()
def run_dirs(tmp_path: Path) -> dict[str, Any]:
    pool = tmp_path / "pool"
    evals = tmp_path / "eval"
    tasks = pool / "tasks"

    pictures = {
        # bar-a sorts first but failed its checks: the extremum example must skip it.
        "bar-a-000000-extremum": _package(
            tasks, "bar-a-000000-extremum", "extremum", "Which category has the highest value?", "Coal", (200, 0, 0)
        ),
        "bar-b-000000-extremum": _package(
            tasks, "bar-b-000000-extremum", "extremum", "Which category has the highest value?", "Wind", (0, 200, 0),
            checks=("1_schema", "2_layout", "3_ambiguity"),
        ),
        "bar-b-000001-value_lookup": _package(
            tasks,
            "bar-b-000001-value_lookup",
            "value_lookup",
            "What value is shown for <script>Tea</script>?",
            "433,332",
            (0, 0, 200),
        ),
        "line-c-000000-series_at_x": _package(
            tasks, "line-c-000000-series_at_x", "series_at_x", "Which series is higher in 2024?", "Milk", (200, 200, 0)
        ),
    }
    _write_jsonl(
        pool / "validation.jsonl",
        [
            {"package_id": "bar-a-000000-extremum", "passed": False, "failed_checks": ["6_counterfactual"]},
            {"package_id": "bar-b-000000-extremum", "passed": True, "failed_checks": []},
            {"package_id": "bar-b-000001-value_lookup", "passed": True, "failed_checks": []},
            {"package_id": "line-c-000000-series_at_x", "passed": True, "failed_checks": []},
            {"package_id": "bar-d-000004-pair_compare", "passed": False, "failed_checks": ["6_counterfactual"]},
        ],
    )
    _write_json(
        pool / "metrics.json",
        {
            "config_hash": "deadbeef",
            "generated": 5,
            "git_sha": "abc123",
            "near_duplicates_removed": 2,
            "passed": 4,
            "per_check": {
                "1_schema": {"fail": 0, "pass": 5},
                "3_ambiguity": {"fail": 1, "pass": 3},
                "3_line_ambiguity": {"fail": 0, "pass": 1},
                "6_counterfactual": {"fail": 1, "pass": 2},
            },
            "rejected": 1,
            "run_id": "pool&1",
            "skipped": ["family <line> not implemented yet"],
            "variation": {
                "cell_coverage": 0.9,
                "near_duplicates_removed": 2,
                "question_type_entropy": 0.95,
                "reasoning_depth_histogram": {"1": 40, "2": 40, "3": 10, "4": 10},
                "structural_difference": 0.96,
            },
            "yield": 0.8,
        },
    )

    items = evals / "items.jsonl"
    items.parent.mkdir(parents=True, exist_ok=True)
    items.write_text('{"item_id": "one"}\n{"item_id": "two"}\n', encoding="utf-8")
    digest = hashlib.sha256(items.read_bytes()).hexdigest()
    _write_json(
        evals / "items.summary.json",
        {"n": 2, "pool_packages": 5, "seed": 7, "sha256": digest, "strata": {"bar/extremum": {"available": 3, "selected": 1}}},
    )
    hostile = _model(0.75, "open<router>", 4, 3, None)
    hostile["model_id"] = HOSTILE_MODEL
    gemini = _model(0.5, "gemini", 2, 1, "rate_limited")
    gemini["model_id"] = "gemini-3.1-flash-lite"
    _write_json(
        evals / "benchmark_metrics.json",
        {
            "eval_set_items": 2,
            "eval_set_sha256": digest,
            "max_tokens": 1024,
            "models": {HOSTILE_MODEL: hostile, "gemini-3.1-flash-lite": gemini},
        },
    )
    _write_jsonl(
        evals / "results" / "gemini-3.1-flash-lite.jsonl",
        [
            {"item_id": "one", "correct": True, "created_at": "2026-11-19T21:18:21+00:00"},
            {"item_id": "two", "correct": False, "created_at": "2026-11-20T09:00:00+00:00"},
        ],
    )
    return {"pool": pool, "eval": evals, "out": tmp_path / "report", "pictures": pictures}


def _page(run_dirs: dict[str, Any], selftest: Path | None = None) -> str:
    index = build_report(run_dirs["pool"], run_dirs["eval"], run_dirs["out"], selftest_json=selftest)
    return index.read_text(encoding="utf-8")


def _section(page: str, key: str) -> str:
    """The inner HTML of one section of the page."""
    match = re.search(rf'<section id="{key}">(.*?)</section>', page, flags=re.DOTALL)
    assert match is not None, f"no section {key!r}"
    return match.group(1)


def test_build_report_writes_index_with_every_section_heading(run_dirs: dict[str, Any]) -> None:
    index = build_report(run_dirs["pool"], run_dirs["eval"], run_dirs["out"])
    assert index == run_dirs["out"] / "index.html"
    page = index.read_text(encoding="utf-8")
    assert f"<title>{TITLE}</title>" in page
    assert f"<h1>{TITLE}</h1>" in page
    assert list(HEADINGS.values()) == [
        "1. Run and scope",
        "2. Pool funnel",
        "3. Checks",
        "4. Variation",
        "5. Self-test",
        "6. Benchmark",
        "7. Examples",
        "8. Limits",
    ]
    for heading in HEADINGS.values():
        assert f"<h2>{heading}</h2>" in page


def test_interpolated_values_are_escaped(run_dirs: dict[str, Any]) -> None:
    page = _page(run_dirs)
    # the model id with markup characters, shown as text
    assert "evil&lt;model&gt;&amp;x" in page
    assert "evil<model>" not in page
    # provider, run id, skipped reason and a question that holds a script tag
    assert "open&lt;router&gt;" in page
    assert "pool&amp;1" in page
    assert "family &lt;line&gt; not implemented yet" in page
    assert "&lt;script&gt;Tea&lt;/script&gt;" in page


def test_page_has_no_script_and_no_http_links(run_dirs: dict[str, Any]) -> None:
    page = _page(run_dirs)
    assert "<script" not in page.lower()
    assert "http://" not in page
    assert "https://" not in page
    assert "<link" not in page.lower()
    assert "@import" not in page
    assert "prefers-color-scheme: dark" in page


def test_examples_hold_one_png_per_task_type_present(run_dirs: dict[str, Any]) -> None:
    _page(run_dirs)
    names = sorted(path.name for path in (run_dirs["out"] / "examples").glob("*.png"))
    # pair_compare has no passing package in the fake pool, so it gets no picture
    assert names == ["extremum.png", "series_at_x.png", "value_lookup.png"]


def test_example_is_the_first_passing_package_by_name(run_dirs: dict[str, Any]) -> None:
    _page(run_dirs)
    copied = (run_dirs["out"] / "examples" / "extremum.png").read_bytes()
    assert copied == run_dirs["pictures"]["bar-b-000000-extremum"]
    assert copied != run_dirs["pictures"]["bar-a-000000-extremum"]


def test_examples_section_links_each_picture_with_its_question_and_checks(run_dirs: dict[str, Any]) -> None:
    page = _page(run_dirs)
    section = _section(page, "examples")
    assert 'href="examples/extremum.png"' in section
    assert 'src="examples/value_lookup.png"' in section
    assert "Question: Which category has the highest value?" in section
    assert "Answer: Wind" in section
    assert "Checks: 3 of 3 checks passed (1_schema, 2_layout, 3_ambiguity)" in section


def test_no_selftest_shows_only_the_placeholder_line(run_dirs: dict[str, Any]) -> None:
    page = _page(run_dirs)
    assert _section(page, "selftest") == f"<h2>{HEADINGS['selftest']}</h2><p>Self-test not run yet</p>"


def test_selftest_json_fills_the_catch_rate_table(run_dirs: dict[str, Any], tmp_path: Path) -> None:
    selftest = tmp_path / "selftest.json"
    _write_json(
        selftest,
        {
            "clean_passed": 2,
            "clean_total": 2,
            "content_only": False,
            "details": [
                {
                    "class": "wrong_answer",
                    "package": "bar-b-000000-extremum",
                    "caught": False,
                    "failed_checks": [],
                    "description": "answer 'Wind' changed to 'Coal'",
                }
            ],
            "per_class": {"wrong_answer": {"caught": 3, "catch_rate": 0.75, "injected": 4}},
            "content_only_per_class": {"wrong_answer": {"caught": 2, "catch_rate": 0.5, "injected": 4}},
        },
    )
    page = _page(run_dirs, selftest=selftest)
    section = _section(page, "selftest")
    assert "Self-test not run yet" not in section
    assert "Clean packages: 2 of 2" in section
    assert "wrong_answer" in section
    assert "75.0%" in section
    assert "50.0%" in section
    assert "answer &#x27;Wind&#x27; changed to &#x27;Coal&#x27;" in section


def test_percentages_round_to_four_places_then_one_decimal() -> None:
    assert _pct(0.9563) == "95.6%"
    assert _pct(0.975) == "97.5%"
    assert _pct(0.9125) == "91.3%"
    assert _pct(1.0) == "100.0%"
    assert _pct(None) == "n/a"


def test_histogram_shares_are_rounded_once_from_the_counts() -> None:
    # 42 / 564 is 7.4468...%, which is 7.4%; rounding to four places first would give 7.5%
    assert _share_pct(42, 564) == "7.4%"
    assert _share_pct(119, 564) == "21.1%"
    assert _share_pct(0, 0) == "n/a"


def test_results_date_is_the_range_the_results_file_records(run_dirs: dict[str, Any]) -> None:
    page = _page(run_dirs)
    assert "2026-11-19 to 2026-11-20" in page
    # the model with no results file keeps a blank date cell rather than an invented date
    assert '<td data-label="Results dated"></td>' in page


def test_model_table_shows_stopped_reason_and_attempted_counts(run_dirs: dict[str, Any]) -> None:
    section = _section(_page(run_dirs), "benchmark")
    assert "rate_limited" in section
    assert "Accuracy (attempted items)" in section
    assert "75.0%" in section  # hostile model: 3 of 4 attempted
    assert "50.0%" in section  # gemini: 1 of 2 attempted


def test_variation_prints_targets_and_actual_status(run_dirs: dict[str, Any]) -> None:
    section = _section(_page(run_dirs), "variation")
    assert "2 of 4 bins" in section  # only the 40% bins reach 15%, and the target asks for three
    assert "10.0 points" in section  # widest gap across task types: 1.0 - 0.9
    assert "0.9500" in section
    assert "not met" in section
    assert "met" in section


def test_eval_set_digest_is_shown_with_item_count_and_disk_check(run_dirs: dict[str, Any]) -> None:
    section = _section(_page(run_dirs), "benchmark")
    digest = hashlib.sha256((run_dirs["eval"] / "items.jsonl").read_bytes()).hexdigest()
    assert digest in section
    assert "matches the recorded SHA-256" in section


def test_limits_are_listed_verbatim(run_dirs: dict[str, Any]) -> None:
    section = _section(_page(run_dirs), "limits")
    assert section.count("<li>") == 6
    assert "Floor plans are out of the MVP." in section
    assert "The human audit has not been done." in section


def test_missing_required_file_raises(run_dirs: dict[str, Any]) -> None:
    (run_dirs["eval"] / "benchmark_metrics.json").unlink()
    with pytest.raises(FileNotFoundError):
        build_report(run_dirs["pool"], run_dirs["eval"], run_dirs["out"])


def test_cli_report_writes_the_page(run_dirs: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "report",
            "--pool",
            str(run_dirs["pool"]),
            "--eval",
            str(run_dirs["eval"]),
            "--out",
            str(run_dirs["out"]),
        ]
    )
    assert code == 0
    assert (run_dirs["out"] / "index.html").is_file()
    assert "report written:" in capsys.readouterr().out


def test_cli_report_reports_a_missing_input_with_exit_code_two(
    run_dirs: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "report",
            "--pool",
            str(tmp_path / "no-such-pool"),
            "--eval",
            str(run_dirs["eval"]),
            "--out",
            str(run_dirs["out"]),
        ]
    )
    assert code == 2
    assert "tf report: error:" in capsys.readouterr().err
