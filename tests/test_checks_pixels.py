"""Tests for taskfactory.checks_pixels.check_5_pixels.

Charts come from render.render_bar. The reader is only given the package
folder, so it sees image.png, text_boxes.json and task.json. A spec is used
here only to work out the expected answer, and it is written into the package
as a real run does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from PIL import Image

from taskfactory.checks_pixels import check_5_pixels
from taskfactory.render import render_bar

BAR_RGB = np.array([76, 114, 176], dtype=np.uint8)  # #4C72B0
COVER_RGB = (200, 60, 60)  # a colour that is not the bar colour
TITLE = "International tourist arrivals (2022)"
CATEGORIES = ["Spain", "Mexico", "France", "Germany", "Italy"]
VALUES = [40_600_000, 81_100_000, 67_600_000, 30_800_000, 52_400_000]
EXTREMUM = "extremum"
VALUE_LOOKUP = "value_lookup"
RANK_K = "rank_k"
PAIR_COMPARE = "pair_compare"


def make_spec(
    orientation: str,
    categories: list[str] = CATEGORIES[:4],
    values: list[int] = VALUES[:4],
    rotation: int = 0,
) -> dict[str, Any]:
    """Hand-made bar spec. Labels are the values printed to one decimal place of millions."""
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
    """Task dict with the expected answer worked out from the spec.

    An extremum asks for the largest category. A value lookup asks for the
    category at ``index`` and expects its printed value label. A rank_k asks for
    the second-largest category, and a pair_compare asks which of categories 0
    and 2 is higher.
    """
    categories = spec["x_labels"]
    series = spec["series"][0]
    if task_type == EXTREMUM:
        top = max(range(len(categories)), key=lambda i: series["values"][i])
        answer_category = categories[top]
        answer = answer_category
        question = "Which category has the highest value?"
    elif task_type == RANK_K:
        ranked = sorted(range(len(categories)), key=lambda i: series["values"][i], reverse=True)
        answer_category = categories[ranked[1]]
        answer = answer_category
        question = "Which category ranks second by value?"
    elif task_type == PAIR_COMPARE:
        a, b = 0, 2
        winner = a if series["values"][a] > series["values"][b] else b
        answer_category = categories[winner]
        answer = answer_category
        question = f"Which is higher, {categories[a]} or {categories[b]}?"
    else:
        answer_category = categories[index]
        answer = series["labels"][index]
        question = f"What value is shown for {answer_category}?"
    return {
        "answer": answer,
        "answer_category": answer_category,
        "answer_printed_in_image": True,
        "domain": spec["domain"],
        "family": spec["family"],
        "question": question,
        "question_in_image": True,
        "spec_index": spec["index"],
        "task_type": task_type,
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


def paint_over_largest_bar(png_path: Path, mode: str) -> None:
    """Cover the largest bar with another colour: all of it, or a strip across its middle."""
    image = np.array(Image.open(png_path).convert("RGB"))
    bar_mask = np.all(image == BAR_RGB, axis=2).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(bar_mask, connectivity=4)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # label 0 is background
    x, y, w, h, _ = (int(v) for v in stats[largest])
    if mode == "covered":
        image[y : y + h, x : x + w] = COVER_RGB
    elif w >= h:  # a horizontal bar becomes a left piece and a right piece
        image[y : y + h, x + w // 2 - 10 : x + w // 2 + 10] = COVER_RGB
    else:  # a vertical bar becomes a top piece and a bottom piece
        image[y + h // 2 - 10 : y + h // 2 + 10, x : x + w] = COVER_RGB
    Image.fromarray(image).save(png_path)


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("task_type", [EXTREMUM, VALUE_LOOKUP])
@pytest.mark.parametrize("n_categories", [4, 5])
def test_clean_chart_passes(tmp_path, orientation, task_type, n_categories):
    spec = make_spec(orientation, CATEGORIES[:n_categories], VALUES[:n_categories])
    task = make_task(spec, task_type)
    pkg = build_package(tmp_path / "pkg", spec, task)

    result = check_5_pixels(pkg)

    assert result["check"] == "5_pixels"
    assert result["passed"] is True
    details = result["details"]
    assert details["reasons"] == []
    assert details["orientation"] == orientation
    assert details["orientation_confirmed"] is True
    assert details["bar_count"] == n_categories
    assert details["category_count"] == n_categories
    assert details["pixel_answer"] == task["answer"]
    assert details["expected_answer"] == task["answer"]
    assert details["match"] is True
    json.dumps(result)  # the result is plain JSON


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_bars_pair_with_their_labels_and_lengths_track_values(tmp_path, orientation):
    spec = make_spec(orientation)
    task = make_task(spec, EXTREMUM)
    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    bars = result["details"]["bars"]
    assert [bar["category_label"] for bar in bars] == spec["x_labels"]
    assert [bar["value_label"] for bar in bars] == spec["series"][0]["labels"]
    lengths = np.array([bar["length_px"] for bar in bars], dtype=float)
    values = np.array(spec["series"][0]["values"], dtype=float)
    pixels_per_unit = lengths / values
    assert np.allclose(pixels_per_unit, pixels_per_unit[0], rtol=0.02)
    for bar in bars:
        x, y, w, h = bar["rect"]
        assert all(isinstance(v, int) for v in bar["rect"])
        assert bar["length_px"] == (h if orientation == "vertical" else w)


def test_rotated_category_labels_pair_correctly(tmp_path):
    categories = ["Spain", "Mexico", "United Kingdom", "Germany"]
    spec = make_spec("vertical", categories, VALUES[:4], rotation=30)
    task = make_task(spec, VALUE_LOOKUP, index=2)

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is True
    assert [bar["category_label"] for bar in result["details"]["bars"]] == categories
    assert result["details"]["pixel_answer"] == "67.6M"


def test_value_lookup_ignores_spaces_in_the_expected_answer(tmp_path):
    spec = make_spec("horizontal")
    task = make_task(spec, VALUE_LOOKUP, index=2)
    task["answer"] = "67.6 M"

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is True
    assert result["details"]["expected_answer"] == "67.6 M"


@pytest.mark.parametrize("task_type", [EXTREMUM, VALUE_LOOKUP])
def test_wrong_expected_answer_fails(tmp_path, task_type):
    spec = make_spec("vertical")
    task = make_task(spec, task_type)
    correct = task["answer"]
    wrong = "France" if task_type == EXTREMUM else "40.6M"
    task["answer"] = wrong

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    details = result["details"]
    assert result["passed"] is False
    assert details["match"] is False
    assert details["pixel_answer"] == correct
    assert details["expected_answer"] == wrong
    assert any("does not match" in reason for reason in details["reasons"])


@pytest.mark.parametrize("mode", ["covered", "split"])
@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_bar_covered_by_another_colour_fails_count_check(tmp_path, orientation, mode):
    spec = make_spec(orientation)
    task = make_task(spec, EXTREMUM)
    pkg = build_package(tmp_path / "pkg", spec, task)
    paint_over_largest_bar(pkg / "image.png", mode)

    result = check_5_pixels(pkg)

    details = result["details"]
    # A fully covered bar disappears; a bar cut in two leaves two pieces.
    assert result["passed"] is False
    assert details["category_count"] == 4
    assert details["bar_count"] == (3 if mode == "covered" else 5)
    assert any(reason.startswith("bar count") for reason in details["reasons"])


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_category_labels_on_the_wrong_side_fail_orientation(tmp_path, orientation):
    spec = make_spec(orientation)
    task = make_task(spec, EXTREMUM)
    pkg = build_package(tmp_path / "pkg", spec, task)
    boxes = json.loads((pkg / "text_boxes.json").read_text(encoding="utf-8"))
    # Vertical bars need labels below them, so move the labels up into the plot.
    # Horizontal bars need labels to their left, so move the labels right, beside the bars.
    dx, dy = (0, -500) if orientation == "vertical" else (900, 0)
    for box in boxes:
        if box["role"] == "category":
            x0, y0, x1, y1 = box["bbox"]
            box["bbox"] = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
    write_json(pkg / "text_boxes.json", boxes)

    result = check_5_pixels(pkg)

    details = result["details"]
    assert result["passed"] is False
    assert details["orientation"] == orientation
    assert details["orientation_confirmed"] is False
    assert any("do not sit" in reason for reason in details["reasons"])


def test_tied_longest_bars_fail_with_no_answer(tmp_path):
    values = [40_600_000, 81_100_000, 81_100_000, 30_800_000]
    spec = make_spec("vertical", values=values)
    task = make_task(spec, EXTREMUM)  # the first of the tied maxima

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is False
    assert result["details"]["pixel_answer"] is None
    assert any("tie" in reason for reason in result["details"]["reasons"])


def test_generator_spec_is_never_read(tmp_path):
    spec = make_spec("horizontal")
    task = make_task(spec, VALUE_LOOKUP)
    pkg = build_package(tmp_path / "pkg", spec, task)
    before = check_5_pixels(pkg)

    # A spec.json that contradicts the picture must change nothing.
    write_json(pkg / "spec.json", make_spec("horizontal", values=list(reversed(VALUES[:4]))))
    after = check_5_pixels(pkg)

    assert after == before
    assert after["passed"] is True


def test_spec_json_is_not_required(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / "spec.json").unlink()

    assert check_5_pixels(pkg)["passed"] is True


@pytest.mark.parametrize("name", ["image.png", "text_boxes.json", "task.json"])
def test_missing_required_file_raises(tmp_path, name):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / name).unlink()

    with pytest.raises(FileNotFoundError, match=name.replace(".", r"\.")):
        check_5_pixels(pkg)


def test_corrupt_image_fails_without_raising(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    (pkg / "image.png").write_bytes(b"not a png")

    result = check_5_pixels(pkg)

    assert result["passed"] is False
    assert "could not read the package" in result["details"]["reasons"][0]


def test_unknown_task_type_fails(tmp_path):
    spec = make_spec("vertical")
    task = make_task(spec, EXTREMUM)
    task["task_type"] = "line_point"

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is False
    assert any("unsupported task_type" in reason for reason in result["details"]["reasons"])


def test_blank_picture_fails_with_no_bars(tmp_path):
    spec = make_spec("vertical")
    pkg = build_package(tmp_path / "pkg", spec, make_task(spec, EXTREMUM))
    Image.new("RGB", (1200, 800), "white").save(pkg / "image.png")

    result = check_5_pixels(pkg)

    assert result["passed"] is False
    assert result["details"]["bar_count"] == 0
    assert any("no bar-coloured" in reason for reason in result["details"]["reasons"])


# --- rank_k and pair_compare charts ------------------------------------------------


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("task_type", [RANK_K, PAIR_COMPARE])
@pytest.mark.parametrize("n_categories", [4, 5])
def test_clean_rank_k_and_pair_compare_charts_pass(
    tmp_path, orientation, task_type, n_categories
):
    spec = make_spec(orientation, CATEGORIES[:n_categories], VALUES[:n_categories])
    task = make_task(spec, task_type)

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    details = result["details"]
    assert result["check"] == "5_pixels"
    assert result["passed"] is True
    assert details["reasons"] == []
    assert details["orientation"] == orientation
    assert details["bar_count"] == n_categories
    assert details["pixel_answer"] == task["answer"]
    assert details["expected_answer"] == task["answer"]
    assert details["match"] is True
    json.dumps(result)  # the result is plain JSON


@pytest.mark.parametrize("task_type", [RANK_K, PAIR_COMPARE])
def test_wrong_rank_k_or_pair_compare_answer_fails(tmp_path, task_type):
    spec = make_spec("vertical")
    task = make_task(spec, task_type)
    correct = task["answer"]
    wrong = next(name for name in spec["x_labels"] if name != correct)
    task["answer"] = wrong

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    details = result["details"]
    assert result["passed"] is False
    assert details["match"] is False
    assert details["pixel_answer"] == correct
    assert details["expected_answer"] == wrong
    assert any("does not match" in reason for reason in details["reasons"])


@pytest.mark.parametrize("task_type", [RANK_K, PAIR_COMPARE])
def test_question_that_names_no_rank_or_pair_fails(tmp_path, task_type):
    spec = make_spec("horizontal")
    task = make_task(spec, task_type)
    task["question"] = "Which category is best?"

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    reasons = result["details"]["reasons"]
    assert result["passed"] is False
    assert result["details"]["pixel_answer"] is None
    expected = "does not ask for a rank" if task_type == RANK_K else "does not name two categories"
    assert any(expected in reason for reason in reasons)


def test_rank_k_tie_at_the_asked_rank_fails_with_no_answer(tmp_path):
    values = [40_600_000, 67_600_000, 67_600_000, 30_800_000]
    spec = make_spec("vertical", values=values)
    task = make_task(spec, RANK_K)

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is False
    assert result["details"]["pixel_answer"] is None
    assert any("tie" in reason for reason in result["details"]["reasons"])


def test_pair_compare_tie_fails_with_no_answer(tmp_path):
    values = [40_600_000, 81_100_000, 81_100_000, 30_800_000]
    spec = make_spec("vertical", values=values)
    task = make_task(spec, PAIR_COMPARE)
    task["question"] = "Which is higher, Mexico or France?"  # both are 81.1M
    task["answer"] = task["answer_category"] = "Mexico"

    result = check_5_pixels(build_package(tmp_path / "pkg", spec, task))

    assert result["passed"] is False
    assert result["details"]["pixel_answer"] is None
    assert any("tie" in reason for reason in result["details"]["reasons"])
