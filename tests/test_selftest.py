"""Tests for taskfactory.selftest: injected defects are caught and clean packages pass.

The two packages are drawn with render.render_bar and render_line from hand-made
specs, as a run draws them, and their spec.json, text_boxes.json and task.json are
written beside the picture. Check 4 needs Tesseract, so every test that needs a clean
pass or a catch is marked ``needs_tesseract``, as in test_pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from taskfactory import selftest
from taskfactory.checks_ocr import check_4_ocr
from taskfactory.pipeline import CHECK_NAMES, LINE_CHECK_NAMES
from taskfactory.questions import make_questions
from taskfactory.render import render_bar
from taskfactory.render_line import render_line
from taskfactory.selftest import APPLIES_TO, DEFECT_CLASSES, check_package, run_selftest

DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MISSING_TESSERACT = r"C:\no-such-folder\tesseract.exe"
BAR_NAME = "bar-tourism-000000-value_lookup"
LINE_NAME = "line-tourism-000000-series_at_x"


def _tesseract_command() -> str | None:
    """The executable the OCR check would use, or None when there is none."""
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd:
        return env_cmd
    if Path(DEFAULT_TESSERACT_CMD).is_file():
        return DEFAULT_TESSERACT_CMD
    return shutil.which("tesseract")


TESSERACT_CMD = _tesseract_command()
needs_tesseract = pytest.mark.skipif(
    TESSERACT_CMD is None,
    reason=(
        "Tesseract executable not found; set TESSERACT_CMD or install it at "
        f"{DEFAULT_TESSERACT_CMD}"
    ),
)


def bar_spec() -> dict[str, Any]:
    """A bar spec with distinct values; the top two differ by about 17 per cent."""
    return {
        "spec_version": 1,
        "family": "bar",
        "domain": "tourism",
        "index": 0,
        "seed": 11,
        "title": "International tourist arrivals (2022)",
        "x_labels": ["France", "Spain", "Italy", "Japan"],
        "series": [
            {
                "name": "",
                "values": [45_200_000, 81_100_000, 67_600_000, 30_800_000],
                "labels": ["45.2M", "81.1M", "67.6M", "30.8M"],
            }
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }


def bar_task() -> dict[str, Any]:
    """A value lookup for Italy, whose printed label is 67.6M."""
    return {
        "task_type": "value_lookup",
        "family": "bar",
        "domain": "tourism",
        "spec_index": 0,
        "question": "What value is shown for Italy?",
        "answer": "67.6M",
        "answer_value": 67_600_000,
        "answer_category": "Italy",
        "reasoning_steps": 1,
        "answer_printed_in_image": True,
        "question_in_image": True,
    }


def line_spec() -> dict[str, Any]:
    """A three-series line spec whose 2024 top value is Alpha, 13 per cent above Beta."""
    years = ["2020", "2021", "2022", "2023", "2024", "2025"]
    series = [
        ("Alpha", [1_200_000, 1_350_000, 1_500_000, 1_420_000, 1_610_000, 1_780_000]),
        ("Beta", [900_000, 1_050_000, 1_100_000, 1_300_000, 1_400_000, 1_250_000]),
        ("Gamma", [700_000, 800_000, 950_000, 1_000_000, 1_150_000, 1_300_000]),
    ]
    return {
        "spec_version": 1,
        "family": "line",
        "domain": "tourism",
        "index": 0,
        "seed": 12,
        "title": "Three series over six years",
        "x_labels": years,
        "series": [
            {
                "name": name,
                "values": values,
                "labels": [f"{value / 1_000_000:.1f}M" for value in values],
            }
            for name, values in series
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }


def line_task() -> dict[str, Any]:
    """A series_at_x task asking for the highest series in 2024, which is Alpha."""
    return {
        "task_type": "series_at_x",
        "family": "line",
        "domain": "tourism",
        "spec_index": 0,
        "question": "Which series is highest in 2024?",
        "answer": "Alpha",
        "answer_value": 1_610_000,
        "answer_category": "Alpha",
        "year": "2024",
        "reasoning_steps": 3,
        "answer_printed_in_image": True,
        "question_in_image": True,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def write_bar_package(folder: Path, task: dict[str, Any] | None = None) -> Path:
    """A bar package for ``task``, by default the value lookup of bar_task()."""
    spec = bar_spec()
    task = bar_task() if task is None else task
    folder.mkdir(parents=True)
    boxes = render_bar(spec, folder / "image.png", question=task["question"])
    _write_json(folder / "spec.json", spec)
    _write_json(folder / "text_boxes.json", boxes)
    _write_json(folder / "task.json", task)
    return folder


def write_line_package(folder: Path) -> Path:
    spec, task = line_spec(), line_task()
    folder.mkdir(parents=True)
    boxes = render_line(spec, folder / "image.png", question=task["question"])
    _write_json(folder / "spec.json", spec)
    _write_json(folder / "text_boxes.json", boxes)
    _write_json(folder / "task.json", task)
    return folder


def folder_hashes(folder: Path) -> dict[str, str]:
    """SHA-256 of every file directly in a package folder, keyed by file name."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.iterdir())
        if path.is_file()
    }


@pytest.fixture(scope="module")
def packages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("packages")
    return {
        "bar": write_bar_package(root / BAR_NAME),
        "line": write_line_package(root / LINE_NAME),
    }


@pytest.fixture(scope="module")
def selftest_run(
    packages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """One self-test over both packages, with the originals' hashes before and after."""
    sources = [packages["bar"], packages["line"]]
    before = {source.name: folder_hashes(source) for source in sources}
    result = run_selftest(sources, tmp_path_factory.mktemp("selftest-work"), tesseract_cmd=TESSERACT_CMD)
    after = {source.name: folder_hashes(source) for source in sources}
    return {"result": result, "before": before, "after": after}


@needs_tesseract
def test_clean_packages_pass_every_check_of_their_family(packages: dict[str, Path]) -> None:
    bar_results = check_package(packages["bar"], "bar", TESSERACT_CMD)
    line_results = check_package(packages["line"], "line", TESSERACT_CMD)

    assert [result["check"] for result in bar_results] == list(CHECK_NAMES)
    assert [result["check"] for result in line_results] == list(LINE_CHECK_NAMES)
    for results in (bar_results, line_results):
        assert [result["check"] for result in results if not result["passed"]] == []


@needs_tesseract
def test_run_selftest_reports_both_clean_packages_as_passing(selftest_run: dict[str, Any]) -> None:
    result = selftest_run["result"]

    assert result["clean_total"] == 2
    assert result["clean_passed"] == 2
    assert set(result["per_class"]) == set(DEFECT_CLASSES)


@needs_tesseract
def test_each_defect_class_is_caught_on_at_least_one_package(selftest_run: dict[str, Any]) -> None:
    per_class = selftest_run["result"]["per_class"]

    for name in DEFECT_CLASSES:
        assert per_class[name]["injected"] >= 1, f"{name} was never injected"
        assert per_class[name]["caught"] >= 1, f"{name} was never caught: {per_class[name]}"


@needs_tesseract
def test_catch_rates_are_caught_over_injected(selftest_run: dict[str, Any]) -> None:
    for counts in selftest_run["result"]["per_class"].values():
        if counts["injected"]:
            assert counts["catch_rate"] == round(counts["caught"] / counts["injected"], 4)
        else:
            assert counts["catch_rate"] is None


@needs_tesseract
def test_every_injection_is_recorded_with_its_failed_checks(selftest_run: dict[str, Any]) -> None:
    result = selftest_run["result"]

    assert len(result["details"]) == sum(c["injected"] for c in result["per_class"].values())
    for item in result["details"]:
        assert set(item) == {"class", "package", "caught", "failed_checks", "description"}
        assert item["caught"] == bool(item["failed_checks"])
        assert item["description"]


@needs_tesseract
def test_defect_classes_apply_only_to_the_task_types_they_are_defined_for(
    selftest_run: dict[str, Any],
) -> None:
    details = selftest_run["result"]["details"]

    line_classes = {item["class"] for item in details if item["package"] == LINE_NAME}
    assert line_classes == {"wrong_answer", "hidden_label"}
    # A value lookup is named by every class, so all five are injected into it.
    bar_classes = {item["class"] for item in details if item["package"] == BAR_NAME}
    assert bar_classes == set(DEFECT_CLASSES)


@needs_tesseract
def test_original_folders_are_unchanged(selftest_run: dict[str, Any]) -> None:
    assert selftest_run["after"] == selftest_run["before"]


def test_packages_that_fail_a_check_are_not_injected_into(
    packages: dict[str, Path], tmp_path: Path
) -> None:
    """With no working Tesseract, check 4 fails on every clean package, so nothing is injected."""
    result = run_selftest(
        [packages["bar"], packages["line"]], tmp_path / "work", tesseract_cmd=MISSING_TESSERACT
    )

    assert result["clean_total"] == 2
    assert result["clean_passed"] == 0
    assert result["details"] == []
    assert result["per_class"] == {
        name: {"injected": 0, "caught": 0, "catch_rate": None} for name in DEFECT_CLASSES
    }


def test_defect_functions_change_only_the_copy(packages: dict[str, Path], tmp_path: Path) -> None:
    cases = {
        "bar": (packages["bar"], list(DEFECT_CLASSES)),
        "line": (packages["line"], ["wrong_answer", "hidden_label"]),
    }
    for family, (source, defects) in cases.items():
        before = folder_hashes(source)
        for defect in defects:
            copy = tmp_path / f"{defect}-{family}"
            shutil.copytree(source, copy)
            description = selftest.DEFECTS[defect](copy)
            assert description
            assert folder_hashes(copy) != before, f"{defect} changed nothing in the {family} copy"
        assert folder_hashes(source) == before


def test_work_dir_must_not_overlap_a_package(packages: dict[str, Path]) -> None:
    with pytest.raises(ValueError, match="overlap"):
        run_selftest([packages["bar"]], packages["bar"] / "work")


def test_packages_of_other_families_are_refused(tmp_path: Path) -> None:
    folder = tmp_path / "floorplan-tourism-000000-spatial"
    folder.mkdir()
    _write_json(folder / "spec.json", {"family": "floorplan"})
    _write_json(folder / "task.json", {"task_type": "spatial"})

    with pytest.raises(ValueError, match="floorplan"):
        run_selftest([folder], tmp_path / "work")


# --- the content checks alone (content_only) -----------------------------------------

REDRAW_CHECKS = ("7_redraw", "7_line_redraw")


@pytest.fixture(scope="module")
def content_only_run(
    packages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """One content-only self-test over both packages, with the originals' hashes before and after."""
    sources = [packages["bar"], packages["line"]]
    before = {source.name: folder_hashes(source) for source in sources}
    result = run_selftest(
        sources,
        tmp_path_factory.mktemp("selftest-content-work"),
        tesseract_cmd=TESSERACT_CMD,
        content_only=True,
    )
    after = {source.name: folder_hashes(source) for source in sources}
    return {"result": result, "before": before, "after": after}


def test_content_only_check_lists_leave_out_the_redraw_checks(packages: dict[str, Path]) -> None:
    bar_results = check_package(packages["bar"], "bar", TESSERACT_CMD, content_only=True)
    line_results = check_package(packages["line"], "line", TESSERACT_CMD, content_only=True)

    assert [result["check"] for result in bar_results] == [
        name for name in CHECK_NAMES if name not in REDRAW_CHECKS
    ]
    assert [result["check"] for result in line_results] == [
        name for name in LINE_CHECK_NAMES if name not in REDRAW_CHECKS
    ]


@needs_tesseract
def test_default_run_reports_the_full_block_and_the_content_only_block(
    selftest_run: dict[str, Any],
) -> None:
    result = selftest_run["result"]

    assert result["content_only"] is False
    assert set(result["per_class"]) == set(DEFECT_CLASSES)
    assert set(result["content_only_per_class"]) == set(DEFECT_CLASSES)
    for name in DEFECT_CLASSES:
        full = result["per_class"][name]
        content = result["content_only_per_class"][name]
        # The content block runs on the same injections, so the counts of injections match.
        # The content checks are part of the full list, so they catch no more than it does.
        assert content["injected"] == full["injected"]
        assert content["caught"] <= full["caught"]
        if content["injected"]:
            assert content["catch_rate"] == round(content["caught"] / content["injected"], 4)
        else:
            assert content["catch_rate"] is None


@needs_tesseract
def test_full_run_fails_the_hidden_label_injections_on_the_redraw_check(
    selftest_run: dict[str, Any],
) -> None:
    # hidden_label paints over the picture, so the picture no longer redraws from its spec.
    failed = {
        check
        for item in selftest_run["result"]["details"]
        if item["class"] == "hidden_label"
        for check in item["failed_checks"]
    }

    assert {"7_redraw", "7_line_redraw"} <= failed


@needs_tesseract
def test_content_only_run_keeps_the_redraw_checks_out_of_every_result(
    content_only_run: dict[str, Any],
) -> None:
    result = content_only_run["result"]

    assert result["content_only"] is True
    assert set(result["per_class"]) == set(DEFECT_CLASSES)
    assert set(result["content_only_per_class"]) == set(DEFECT_CLASSES)
    assert result["content_only_per_class"] == result["per_class"]
    assert result["details"]
    for item in result["details"]:
        assert not set(item["failed_checks"]) & set(REDRAW_CHECKS), item
    assert content_only_run["after"] == content_only_run["before"]


@needs_tesseract
def test_absent_entity_is_caught_by_check_1_alone_in_content_only_mode(
    content_only_run: dict[str, Any],
) -> None:
    records = [
        item for item in content_only_run["result"]["details"] if item["class"] == "absent_entity"
    ]

    assert [item["package"] for item in records] == [BAR_NAME]
    assert records[0]["failed_checks"] == ["1_schema"]


@needs_tesseract
def test_absent_entity_is_also_caught_by_the_redraw_check_in_the_full_run(
    selftest_run: dict[str, Any],
) -> None:
    records = [
        item for item in selftest_run["result"]["details"] if item["class"] == "absent_entity"
    ]

    assert len(records) == 1
    assert {"1_schema", "7_redraw"} <= set(records[0]["failed_checks"])


# --- hidden_label covers the text that each task type's answer depends on -------------


def bar_task_of(task_type: str) -> dict[str, Any]:
    """The task of ``task_type`` that make_questions builds for bar_spec()."""
    return next(task for task in make_questions(bar_spec()) if task["task_type"] == task_type)


def package_for(task_type: str, folder: Path) -> Path:
    """A clean package whose answer is of ``task_type``: the line package for series_at_x."""
    if task_type == "series_at_x":
        return write_line_package(folder)
    return write_bar_package(folder, bar_task_of(task_type))


def _pixels(png: Path) -> np.ndarray:
    """The picture as an RGB array."""
    with Image.open(png) as picture:
        return np.asarray(picture.convert("RGB"))


# Each task type with the text box role hidden_label covers for it, and the text of that box.
# bar_spec() at seed 11 asks for Japan's value label, names Spain as the extremum, France as
# the third-ranked category, and Spain as the higher of Spain and Japan.
HIDDEN_TEXT_CASES = [
    ("value_lookup", "value", "30.8M"),
    ("extremum", "category", "Spain"),
    ("pair_compare", "category", "Spain"),
    ("rank_k", "category", "France"),
    ("series_at_x", "legend", "Alpha"),
]


def test_hidden_label_applies_to_every_task_type_with_an_answer_text() -> None:
    assert APPLIES_TO["hidden_label"] == frozenset(
        {
            ("bar", "value_lookup"),
            ("bar", "extremum"),
            ("bar", "pair_compare"),
            ("bar", "rank_k"),
            ("line", "series_at_x"),
        }
    )


@pytest.mark.parametrize(("task_type", "role", "text"), HIDDEN_TEXT_CASES)
def test_hidden_label_covers_the_text_the_answer_depends_on(
    tmp_path: Path, task_type: str, role: str, text: str
) -> None:
    source = package_for(task_type, tmp_path / "source")
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    before = _pixels(source / "image.png")

    description = selftest.hidden_label(copy)

    after = _pixels(copy / "image.png")
    boxes = json.loads((source / "text_boxes.json").read_text(encoding="utf-8"))
    x0, y0, x1, y1 = next(
        box["bbox"] for box in boxes if box["role"] == role and box["text"] == text
    )
    assert f"the {role} box {text!r}" in description
    assert np.all(after[y0:y1, x0:x1] == 255), "the box's text is not covered"
    # Every pixel that changed lies inside that box with the paint margin, so no other box moved.
    rows, cols = np.nonzero(np.any(before != after, axis=2))
    assert cols.size, "hidden_label changed no pixel"
    margin = selftest.PAINT_MARGIN_PX
    assert x0 - margin <= cols.min() and cols.max() < x1 + margin
    assert y0 - margin <= rows.min() and rows.max() < y1 + margin


@needs_tesseract
@pytest.mark.parametrize("task_type", [case[0] for case in HIDDEN_TEXT_CASES])
def test_hidden_label_fails_check_4_for_every_task_type(tmp_path: Path, task_type: str) -> None:
    source = package_for(task_type, tmp_path / "source")
    assert check_4_ocr(source, TESSERACT_CMD)["passed"] is True
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    selftest.hidden_label(copy)

    assert check_4_ocr(copy, TESSERACT_CMD)["passed"] is False


@needs_tesseract
def test_hidden_label_on_extremum_is_caught_by_check_4_in_content_only_mode(
    tmp_path: Path,
) -> None:
    source = write_bar_package(
        tmp_path / "packages" / "bar-tourism-000000-extremum", bar_task_of("extremum")
    )

    result = run_selftest(
        [source], tmp_path / "work", tesseract_cmd=TESSERACT_CMD, content_only=True
    )

    assert result["clean_passed"] == 1, result["details"]
    records = [item for item in result["details"] if item["class"] == "hidden_label"]
    assert len(records) == 1, result["details"]
    assert "category box 'Spain'" in records[0]["description"]
    assert "4_ocr" in records[0]["failed_checks"]
    assert not set(records[0]["failed_checks"]) & set(REDRAW_CHECKS)


@needs_tesseract
def test_hidden_label_on_value_lookup_is_still_caught_by_check_4(
    content_only_run: dict[str, Any],
) -> None:
    records = [
        item
        for item in content_only_run["result"]["details"]
        if item["class"] == "hidden_label" and item["package"] == BAR_NAME
    ]

    assert len(records) == 1
    assert records[0]["caught"] is True
    assert "4_ocr" in records[0]["failed_checks"]
