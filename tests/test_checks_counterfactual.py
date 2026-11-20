"""Tests for taskfactory.checks_counterfactual.check_6_counterfactual.

Each package is drawn with render.render_bar, as a run draws it. The redraw and
the pixel reader are the real ones unless a test swaps the reader on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from taskfactory import checks_counterfactual
from taskfactory.checks_counterfactual import check_6_counterfactual
from taskfactory.checks_pixels import check_5_pixels
from taskfactory.render import render_bar

CATEGORIES = ["Spain", "Mexico", "France", "Germany"]
VALUES = [40_600_000, 81_100_000, 67_600_000, 30_800_000]
FIVE_CATEGORIES = [*CATEGORIES, "Italy"]
FIVE_VALUES = [*VALUES, 52_400_000]
TITLE = "International tourist arrivals (2022)"
EXTREMUM = "extremum"
VALUE_LOOKUP = "value_lookup"
RANK_K = "rank_k"
PAIR_COMPARE = "pair_compare"


def make_spec(
    orientation: str = "vertical",
    categories: list[str] = CATEGORIES,
    values: list[int] = VALUES,
    rotation: int = 0,
) -> dict[str, Any]:
    """Hand-made bar spec whose labels are the values printed as "{:.1f}M"."""
    return {
        "spec_version": 1,
        "family": "bar",
        "domain": "tourism",
        "index": 0,
        "seed": 1,
        "title": TITLE,
        "x_labels": list(categories),
        "series": [
            {
                "name": "",
                "values": list(values),
                "labels": [f"{v / 1_000_000:.1f}M" for v in values],
            }
        ],
        "orientation": orientation,
        "x_label_rotation": rotation,
        "question_in_image": True,
    }


def make_task(spec: dict[str, Any], task_type: str, index: int = 2) -> dict[str, Any]:
    """Task worked out from the spec, with the same question wording as questions.py.

    An extremum asks for the largest category. A value lookup asks for the
    category at ``index`` and expects its printed label. A rank_k asks for the
    second-largest category, and a pair_compare asks which of categories 0 and 2
    is higher.
    """
    categories = spec["x_labels"]
    series = spec["series"][0]
    if task_type == EXTREMUM:
        top = max(range(len(categories)), key=lambda i: series["values"][i])
        answer_category = categories[top]
        answer = answer_category
        answer_value = series["values"][top]
        question = "Which category has the highest value?"
    elif task_type == RANK_K:
        ranked = sorted(range(len(categories)), key=lambda i: series["values"][i], reverse=True)
        top = ranked[1]
        answer_category = categories[top]
        answer = answer_category
        answer_value = series["values"][top]
        question = "Which category ranks second by value?"
    elif task_type == PAIR_COMPARE:
        a, b = 0, 2
        top = a if series["values"][a] > series["values"][b] else b
        answer_category = categories[top]
        answer = answer_category
        answer_value = series["values"][top]
        question = f"Which is higher, {categories[a]} or {categories[b]}?"
    else:
        answer_category = categories[index]
        answer = series["labels"][index]
        answer_value = series["values"][index]
        question = f"What value is shown for {answer_category}?"
    return {
        "task_type": task_type,
        "family": spec["family"],
        "domain": spec["domain"],
        "spec_index": spec["index"],
        "question": question,
        "answer": answer,
        "answer_value": answer_value,
        "answer_category": answer_category,
        "reasoning_steps": 1,
        "answer_printed_in_image": True,
        "question_in_image": True,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def build_package(pkg_dir: Path, spec: dict[str, Any], task: dict[str, Any]) -> Path:
    """Write a package the way a run does: the picture, the text boxes, the spec and the task."""
    pkg_dir.mkdir(parents=True, exist_ok=True)
    boxes = render_bar(spec, pkg_dir / "image.png", question=task["question"])
    write_json(pkg_dir / "spec.json", spec)
    write_json(pkg_dir / "text_boxes.json", boxes)
    write_json(pkg_dir / "task.json", task)
    return pkg_dir


def edit_json(path: Path, key: str, value: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = value
    write_json(path, data)


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("task_type", [EXTREMUM, VALUE_LOOKUP])
@pytest.mark.parametrize("n_categories", [4, 5])
def test_good_package_passes_when_the_answer_follows_the_data(
    tmp_path, orientation, task_type, n_categories
):
    if n_categories == 4:
        categories, values = CATEGORIES, VALUES
    else:
        categories, values = FIVE_CATEGORIES, FIVE_VALUES
    spec = make_spec(orientation, categories, values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, task_type))

    result = check_6_counterfactual(pkg)

    details = result["details"]
    assert result["check"] == "6_counterfactual"
    assert result["passed"] is True
    assert details["reasons"] == []
    assert details["changed"] is True
    assert details["reader_passed"] is True
    assert details["altered_answer"] != details["original_answer"]
    assert details["pixel_answer_after_redraw"] == details["altered_answer"]
    json.dumps(result)  # the result is plain JSON


def test_extremum_answer_moves_to_the_new_top_category(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))

    details = check_6_counterfactual(pkg)["details"]

    # Mexico (81.1M) is the answer. Sinking it to 30.8M - 1 makes France (67.6M) the top.
    assert details["original_answer"] == "Mexico"
    assert details["altered_values"] == [40_600_000, 30_799_999, 67_600_000, 30_800_000]
    assert details["altered_answer"] == "France"
    assert details["pixel_answer_after_redraw"] == "France"


def test_value_lookup_answer_becomes_the_new_printed_label(tmp_path):
    spec = make_spec("horizontal")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    details = check_6_counterfactual(pkg)["details"]

    # France is 67.6M. Its new value is 67.6M * 1.5 = 101.4M.
    assert details["original_answer"] == "67.6M"
    assert details["altered_values"] == [40_600_000, 81_100_000, 101_400_000, 30_800_000]
    assert details["altered_answer"] == "101.4M"
    assert details["pixel_answer_after_redraw"] == "101.4M"


def test_value_lookup_doubles_when_the_scaled_value_is_already_used(tmp_path):
    values = [45_000_000, 60_000_000, 20_000_000, 30_000_000]
    spec = make_spec("vertical", values=values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    result = check_6_counterfactual(pkg)

    # France is 20M. 20M * 1.5 = 30M is Germany's value, so France takes 20M * 2 = 40M.
    assert result["details"]["altered_values"] == [45_000_000, 60_000_000, 40_000_000, 30_000_000]
    assert result["details"]["altered_answer"] == "40.0M"
    assert result["passed"] is True


def test_format_is_inferred_as_thousands_separators_for_plain_labels(tmp_path):
    spec = make_spec("vertical")
    spec["series"][0]["labels"] = [f"{v:,}" for v in VALUES]
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    result = check_6_counterfactual(pkg)

    assert result["details"]["original_answer"] == "67,600,000"
    assert result["details"]["altered_answer"] == "101,400,000"
    assert result["passed"] is True


def test_explicit_value_format_is_used_for_the_new_label(tmp_path):
    spec = make_spec("horizontal")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    result = check_6_counterfactual(pkg, value_format="{:.1f}M")

    assert result["details"]["altered_answer"] == "101.4M"
    assert result["passed"] is True


def test_rotated_category_labels_pass(tmp_path):
    spec = make_spec("vertical", rotation=30)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    assert check_6_counterfactual(pkg)["passed"] is True


def test_value_lookup_with_a_zero_value_cannot_change_its_label(tmp_path):
    values = [40_600_000, 81_100_000, 0, 30_800_000]
    spec = make_spec("vertical", values=values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))

    result = check_6_counterfactual(pkg)

    details = result["details"]
    # 0 * 1.5 and 0 * 2 are both 0, so the label stays "0.0M" and the answer does not change.
    assert result["passed"] is False
    assert details["changed"] is False
    assert details["altered_answer"] == "0.0M"
    assert any("still gives the original answer" in reason for reason in details["reasons"])


def test_extremum_with_a_zero_minimum_cannot_sink_the_top_bar(tmp_path):
    values = [40_600_000, 81_100_000, 67_600_000, 0]
    spec = make_spec("vertical", values=values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))

    result = check_6_counterfactual(pkg)

    details = result["details"]
    # The smallest value is 0, so Mexico cannot go to -1. It is lifted instead and stays on top.
    assert result["passed"] is False
    assert details["changed"] is False
    assert details["altered_answer"] == "Mexico"
    assert details["altered_values"] == [40_600_000, 81_100_001, 67_600_000, 0]


@pytest.mark.parametrize("name", ["spec.json", "task.json"])
def test_missing_spec_or_task_raises(tmp_path, name):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / name).unlink()

    with pytest.raises(FileNotFoundError, match=name.replace(".", r"\.")):
        check_6_counterfactual(pkg)


@pytest.mark.parametrize("name", ["image.png", "text_boxes.json"])
def test_image_and_text_boxes_are_not_needed(tmp_path, name):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / name).unlink()

    assert check_6_counterfactual(pkg)["passed"] is True


@pytest.mark.parametrize(
    ("name", "key", "value", "phrase"),
    [
        ("task.json", "task_type", "line_point", "unsupported task_type"),
        ("task.json", "answer_category", "Italy", "not one of the spec's categories"),
        ("task.json", "answer", 67.6, "task.answer must be a string"),
        ("spec.json", "x_label_rotation", 45, "failed validate_spec"),
    ],
)
def test_bad_content_fails_without_raising(tmp_path, name, key, value, phrase):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    edit_json(pkg / name, key, value)

    result = check_6_counterfactual(pkg)

    assert result["passed"] is False
    assert any(phrase in reason for reason in result["details"]["reasons"])


def test_unreadable_task_json_fails_without_raising(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / "task.json").write_text("{not json", encoding="utf-8")

    result = check_6_counterfactual(pkg)

    assert result["passed"] is False
    assert "could not read the package" in result["details"]["reasons"][0]


def test_value_format_that_cannot_print_the_values_fails_without_raising(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))

    result = check_6_counterfactual(pkg, value_format="{:d}M")

    assert result["passed"] is False
    assert any("value_format" in reason for reason in result["details"]["reasons"])


@pytest.mark.parametrize("task_type", [EXTREMUM, VALUE_LOOKUP, RANK_K, PAIR_COMPARE])
@pytest.mark.parametrize("reader_says_passed", [False, True])
def test_reader_that_copies_the_original_answer_fails(
    tmp_path, monkeypatch, task_type, reader_says_passed
):
    spec = make_spec("horizontal")
    task = make_task(spec, task_type)
    pkg = build_package(tmp_path / "pkg", spec, task)
    original = task["answer"]

    def copying_reader(_pkg_dir: Path) -> dict[str, Any]:
        # A reader that memorised the picture or copied the old label: it answers the original.
        return {
            "check": "5_pixels",
            "passed": reader_says_passed,
            "details": {"pixel_answer": original, "reasons": []},
        }

    monkeypatch.setattr(checks_counterfactual, "check_5_pixels", copying_reader)

    result = check_6_counterfactual(pkg)

    details = result["details"]
    assert result["passed"] is False
    assert details["changed"] is True
    assert details["pixel_answer_after_redraw"] == original
    assert details["reader_passed"] is reader_says_passed
    assert any("not the altered answer" in reason for reason in details["reasons"])


def test_reader_is_given_a_redrawn_package_with_the_new_answer(tmp_path, monkeypatch):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, VALUE_LOOKUP, index=2))
    seen: dict[str, Any] = {}

    def recording_reader(folder: Path) -> dict[str, Any]:
        seen["folder"] = Path(folder)
        seen["files"] = sorted(p.name for p in Path(folder).iterdir())
        seen["task"] = json.loads((Path(folder) / "task.json").read_text(encoding="utf-8"))
        return check_5_pixels(Path(folder))

    monkeypatch.setattr(checks_counterfactual, "check_5_pixels", recording_reader)

    result = check_6_counterfactual(pkg)

    assert result["passed"] is True
    assert seen["folder"] != pkg
    assert seen["files"] == ["image.png", "spec.json", "task.json", "text_boxes.json"]
    assert seen["task"]["answer"] == "101.4M"
    assert seen["task"]["answer_category"] == "France"
    assert seen["task"]["answer_value"] == 101_400_000


def test_original_package_is_left_unchanged(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    before = {path.name: path.read_bytes() for path in pkg.iterdir()}

    check_6_counterfactual(pkg)

    assert {path.name: path.read_bytes() for path in pkg.iterdir()} == before


# --- rank_k and pair_compare -------------------------------------------------------


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("task_type", [RANK_K, PAIR_COMPARE])
@pytest.mark.parametrize("n_categories", [4, 5])
def test_good_rank_k_and_pair_compare_packages_pass(
    tmp_path, orientation, task_type, n_categories
):
    if n_categories == 4:
        categories, values = CATEGORIES, VALUES
    else:
        categories, values = FIVE_CATEGORIES, FIVE_VALUES
    spec = make_spec(orientation, categories, values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, task_type))

    result = check_6_counterfactual(pkg)

    details = result["details"]
    assert result["check"] == "6_counterfactual"
    assert result["passed"] is True
    assert details["reasons"] == []
    assert details["changed"] is True
    assert details["reader_passed"] is True
    assert details["altered_answer"] != details["original_answer"]
    assert details["pixel_answer_after_redraw"] == details["altered_answer"]
    json.dumps(result)  # the result is plain JSON


def test_rank_k_answer_moves_to_the_category_that_was_one_rank_up(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, RANK_K))

    details = check_6_counterfactual(pkg)["details"]

    # France (67.6M) is second. It swaps values with Mexico (81.1M), the category above it.
    assert details["original_answer"] == "France"
    assert details["altered_values"] == [40_600_000, 67_600_000, 81_100_000, 30_800_000]
    assert details["altered_answer"] == "Mexico"
    assert details["pixel_answer_after_redraw"] == "Mexico"


def test_pair_compare_answer_flips_to_the_other_name(tmp_path):
    spec = make_spec("horizontal")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, PAIR_COMPARE))

    details = check_6_counterfactual(pkg)["details"]

    # France (67.6M) is higher than Spain (40.6M). Their values swap, so Spain becomes higher.
    assert details["original_answer"] == "France"
    assert details["altered_values"] == [67_600_000, 81_100_000, 40_600_000, 30_800_000]
    assert details["altered_answer"] == "Spain"
    assert details["pixel_answer_after_redraw"] == "Spain"


def test_rank_k_answer_not_at_the_asked_rank_cannot_be_altered(tmp_path):
    spec = make_spec("vertical")
    task = make_task(spec, RANK_K)
    task["answer"] = task["answer_category"] = "Mexico"  # Mexico is first, not second
    pkg = build_package(tmp_path / "pkg", spec, task)

    result = check_6_counterfactual(pkg)

    assert result["passed"] is False
    assert any("is not the category at rank 2" in reason for reason in result["details"]["reasons"])


def test_rank_k_question_without_a_rank_cannot_be_altered(tmp_path):
    spec = make_spec("vertical")
    task = make_task(spec, RANK_K)
    task["question"] = "Which category is best?"
    pkg = build_package(tmp_path / "pkg", spec, task)

    result = check_6_counterfactual(pkg)

    assert result["passed"] is False
    assert any("does not ask for a rank" in reason for reason in result["details"]["reasons"])


def test_pair_compare_answer_that_is_the_smaller_name_cannot_be_altered(tmp_path):
    spec = make_spec("vertical")
    task = make_task(spec, PAIR_COMPARE)  # France (67.6M) is the larger of the pair
    task["answer"] = task["answer_category"] = "Spain"
    pkg = build_package(tmp_path / "pkg", spec, task)

    result = check_6_counterfactual(pkg)

    assert result["passed"] is False
    assert any("is not the larger of" in reason for reason in result["details"]["reasons"])


def test_pair_compare_with_equal_values_is_rejected_before_any_alteration(tmp_path):
    values = [40_600_000, 81_100_000, 40_600_000, 30_800_000]  # Spain and France are equal
    spec = make_spec("vertical", values=values)
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, PAIR_COMPARE))

    result = check_6_counterfactual(pkg)

    # validate_spec refuses duplicate values, so no pair without a larger name is altered.
    assert result["passed"] is False
    assert any("duplicate values" in reason for reason in result["details"]["reasons"])
