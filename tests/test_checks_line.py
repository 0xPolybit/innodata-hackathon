"""Tests for taskfactory.checks_line: checks 3, 5, 6 and 7 on line packages.

Each package is drawn with render_line, as a run draws it. The pixel reader and the
redraw are the real ones unless a test swaps the reader on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from taskfactory import checks_line
from taskfactory.checks_line import (
    check_3_line_ambiguity,
    check_5_line_pixels,
    check_6_line_counterfactual,
    check_7_line_redraw,
    run_line_checks,
)
from taskfactory.render_line import render_line

YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]
SERIES = [
    ("Alpha", [1_200_000, 1_350_000, 1_500_000, 1_420_000, 1_610_000, 1_780_000]),
    ("Beta", [900_000, 1_050_000, 1_100_000, 1_300_000, 1_400_000, 1_250_000]),
    ("Gamma", [700_000, 800_000, 950_000, 1_000_000, 1_150_000, 1_300_000]),
]
YEAR = "2024"  # Alpha is highest here (1.61M), then Beta (1.40M), then Gamma (1.15M)
CHECK_NAMES = ["3_line_ambiguity", "5_line_pixels", "6_line_counterfactual", "7_line_redraw"]
ALPHA_RGB = [76, 114, 176]
BETA_RGB = [221, 132, 82]
GAMMA_RGB = [85, 168, 104]


def make_spec(series: list[tuple[str, list[int]]] = SERIES, rotation: int = 0) -> dict[str, Any]:
    """A hand-made three-series line spec. Each label prints its value as "1.2M"."""
    return {
        "spec_version": 1,
        "family": "line",
        "domain": "test",
        "index": 0,
        "seed": 1,
        "title": "Three series over six years",
        "x_labels": list(YEARS),
        "series": [
            {
                "name": name,
                "values": list(values),
                "labels": [f"{value / 1_000_000:.1f}M" for value in values],
            }
            for name, values in series
        ],
        "orientation": "vertical",
        "x_label_rotation": rotation,
        "question_in_image": True,
    }


def make_task(spec: dict[str, Any], year: str = YEAR) -> dict[str, Any]:
    """The task for the series highest at ``year``, with the keys the sampler writes."""
    j = spec["x_labels"].index(year)
    at_year = {entry["name"]: entry["values"][j] for entry in spec["series"]}
    top = max(at_year, key=at_year.get)
    return {
        "task_type": "series_at_x",
        "family": "line",
        "domain": spec["domain"],
        "spec_index": spec["index"],
        "question": f"Which series is highest in {year}?",
        "answer": top,
        "answer_value": at_year[top],
        "answer_category": top,
        "year": year,
        "reasoning_steps": len(spec["series"]),
        "answer_printed_in_image": False,
        "question_in_image": spec["question_in_image"],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_package(pkg: Path, spec: dict[str, Any], task: dict[str, Any] | None = None) -> Path:
    """Draw ``spec`` into ``pkg`` as a run does, and write its text boxes, spec and task."""
    task = make_task(spec) if task is None else task
    pkg.mkdir(parents=True, exist_ok=True)
    question = task["question"] if spec["question_in_image"] else None
    boxes = render_line(spec, pkg / "image.png", question=question)
    write_json(pkg / "text_boxes.json", boxes)
    write_json(pkg / "spec.json", spec)
    write_json(pkg / "task.json", task)
    return pkg


@pytest.fixture
def good_pkg(tmp_path: Path) -> Path:
    """A correct package: the picture, the spec and the task all agree."""
    return write_package(tmp_path / "pkg", make_spec())


def test_good_package_passes_all_four_checks(good_pkg):
    results = run_line_checks(good_pkg)
    assert [result["check"] for result in results] == CHECK_NAMES
    assert all(result["passed"] for result in results), [
        (result["check"], result["details"]["reasons"]) for result in results
    ]


def test_pixel_reader_finds_each_colour_and_the_highest_line(good_pkg):
    details = check_5_line_pixels(good_pkg)["details"]
    assert details["colours"] == {"Alpha": ALPHA_RGB, "Beta": BETA_RGB, "Gamma": GAMMA_RGB}
    assert details["pixel_answer"] == "Alpha"
    assert details["expected_answer"] == "Alpha"
    assert details["y_positions"]["Alpha"] < details["y_positions"]["Beta"]
    assert details["y_positions"]["Beta"] < details["y_positions"]["Gamma"]
    assert details["gap_fraction"] > 0.1  # Alpha and Beta sit about 90 px apart
    assert details["reasons"] == []


def test_wrong_answer_fails_the_pixel_check_and_the_ambiguity_check(good_pkg):
    task = read_json(good_pkg / "task.json")
    task["answer"] = "Gamma"
    write_json(good_pkg / "task.json", task)

    pixel = check_5_line_pixels(good_pkg)
    assert pixel["passed"] is False
    assert pixel["details"]["pixel_answer"] == "Alpha"

    ambiguity = check_3_line_ambiguity(good_pkg)
    assert ambiguity["passed"] is False
    assert "answer_not_top" in ambiguity["details"]["failed_rules"]


def test_lowered_gap_at_the_year_fails_the_ambiguity_check(tmp_path):
    beta_close = [900_000, 1_050_000, 1_100_000, 1_300_000, 1_600_000, 1_250_000]
    close = [("Alpha", SERIES[0][1]), ("Beta", beta_close), ("Gamma", SERIES[2][1])]
    pkg = write_package(tmp_path / "pkg", make_spec(series=close))

    ambiguity = check_3_line_ambiguity(pkg)
    assert ambiguity["passed"] is False
    assert ambiguity["details"]["failed_rules"] == ["small_margin"]
    assert ambiguity["details"]["margin"] < 0.05
    # The picture shows the same closeness: Alpha and Beta are a few pixels apart.
    assert check_5_line_pixels(pkg)["details"]["gap_fraction"] < 0.05


def test_reader_that_copies_the_old_answer_fails_the_counterfactual(good_pkg, monkeypatch):
    original = read_json(good_pkg / "task.json")["answer"]

    def copying_reader(pkg_dir):
        return {
            "check": "5_line_pixels",
            "passed": True,
            "details": {"pixel_answer": original, "reasons": []},
        }

    monkeypatch.setattr(checks_line, "check_5_line_pixels", copying_reader)
    result = check_6_line_counterfactual(good_pkg)
    assert result["passed"] is False
    assert result["details"]["altered_answer"] == "Beta"
    assert (
        "the pixel reader answered 'Alpha', not the altered answer 'Beta'"
        in result["details"]["reasons"]
    )


def test_counterfactual_sinks_the_answer_and_the_reader_follows(good_pkg):
    result = check_6_line_counterfactual(good_pkg)
    assert result["passed"] is True, result["details"]["reasons"]
    assert result["details"]["original_answer"] == "Alpha"
    assert result["details"]["altered_answer"] == "Beta"
    assert result["details"]["pixel_answer_after_redraw"] == "Beta"


def test_missing_spec_raises_file_not_found(good_pkg):
    (good_pkg / "spec.json").unlink()
    for check in (check_3_line_ambiguity, check_6_line_counterfactual, check_7_line_redraw):
        with pytest.raises(FileNotFoundError):
            check(good_pkg)
    with pytest.raises(FileNotFoundError):
        run_line_checks(good_pkg)


def test_redraw_fails_when_one_byte_of_the_image_changes(good_pkg):
    assert check_7_line_redraw(good_pkg)["passed"] is True
    image = good_pkg / "image.png"
    data = bytearray(image.read_bytes())
    data[len(data) // 2] ^= 0x01
    image.write_bytes(bytes(data))
    result = check_7_line_redraw(good_pkg)
    assert result["passed"] is False
    assert result["details"]["hashes_match"] is False


def test_year_missing_from_the_picture_fails_the_pixel_check(good_pkg):
    task = read_json(good_pkg / "task.json")
    task["year"] = "2030"
    write_json(good_pkg / "task.json", task)
    result = check_5_line_pixels(good_pkg)
    assert result["passed"] is False
    assert "no category label reads '2030' in the picture" in result["details"]["reasons"]


def test_unreadable_spec_fails_without_raising(good_pkg):
    (good_pkg / "spec.json").write_text("{not json", encoding="utf-8")
    for check in (check_3_line_ambiguity, check_6_line_counterfactual, check_7_line_redraw):
        result = check(good_pkg)
        assert result["passed"] is False
        assert result["details"]["reasons"]


def test_spec_that_cannot_be_drawn_fails_without_raising(good_pkg):
    spec = read_json(good_pkg / "spec.json")
    spec["series"] = spec["series"][:1]  # a line chart needs two or three series
    write_json(good_pkg / "spec.json", spec)

    redraw = check_7_line_redraw(good_pkg)
    assert redraw["passed"] is False
    assert any("cannot be drawn" in reason for reason in redraw["details"]["reasons"])
    assert check_6_line_counterfactual(good_pkg)["passed"] is False


def test_repeated_series_names_fail_the_ambiguity_check(good_pkg):
    spec = read_json(good_pkg / "spec.json")
    spec["series"][2]["name"] = "Alpha"
    write_json(good_pkg / "spec.json", spec)
    result = check_3_line_ambiguity(good_pkg)
    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["duplicate_series_names"]


def test_min_margin_is_passed_to_the_ambiguity_check(good_pkg):
    results = run_line_checks(good_pkg, min_margin=0.5)
    assert results[0]["check"] == "3_line_ambiguity"
    assert results[0]["passed"] is False
    assert results[0]["details"]["failed_rules"] == ["small_margin"]
    assert [result["passed"] for result in results[1:]] == [True, True, True]


def test_results_are_json_serialisable(good_pkg):
    for result in run_line_checks(good_pkg):
        json.dumps(result)


# --- anchors and rotated category labels -----------------------------------------

# Alpha is top in 2024 (1.6M, then Beta at 1.5M). Alpha rises steeply into 2024, so
# at the centre of a rotated label, about 16 px left of the point, Beta is the higher line.
CROSSING = [
    ("Alpha", [700_000, 900_000, 1_000_000, 100_000, 1_600_000, 1_700_000]),
    ("Beta", [900_000, 1_100_000, 1_200_000, 1_500_000, 1_500_000, 1_300_000]),
    ("Gamma", [600_000, 700_000, 800_000, 900_000, 1_100_000, 1_200_000]),
]


def test_30_degree_package_passes_check_5_by_the_anchor(tmp_path):
    pkg = write_package(tmp_path / "pkg", make_spec(rotation=30))
    categories = [box for box in read_json(pkg / "text_boxes.json") if box["role"] == "category"]
    assert len(categories) == len(YEARS)
    assert all(isinstance(box.get("anchor"), list) and len(box["anchor"]) == 2 for box in categories)
    year_box = next(box for box in categories if box["text"] == YEAR)

    result = check_5_line_pixels(pkg)
    assert result["passed"] is True, result["details"]["reasons"]
    assert result["details"]["x_source"] == "anchor"
    assert result["details"]["year_column"] == year_box["anchor"][0]
    assert result["details"]["pixel_answer"] == "Alpha"


def test_box_centre_reads_the_wrong_series_for_a_rotated_label(tmp_path):
    pkg = write_package(tmp_path / "pkg", make_spec(series=CROSSING, rotation=30))
    assert check_5_line_pixels(pkg)["passed"] is True

    boxes = read_json(pkg / "text_boxes.json")
    for box in boxes:
        box.pop("anchor", None)
    write_json(pkg / "text_boxes.json", boxes)
    result = check_5_line_pixels(pkg)
    assert result["details"]["x_source"] == "box_centre"
    assert result["details"]["pixel_answer"] == "Beta"
    assert result["passed"] is False


def test_package_without_anchors_still_passes_by_the_box_centre(good_pkg):
    boxes = read_json(good_pkg / "text_boxes.json")
    for box in boxes:
        box.pop("anchor", None)
    write_json(good_pkg / "text_boxes.json", boxes)
    result = check_5_line_pixels(good_pkg)
    assert result["passed"] is True, result["details"]["reasons"]
    assert result["details"]["x_source"] == "box_centre"


def test_malformed_anchor_makes_the_package_unreadable_without_raising(good_pkg):
    boxes = read_json(good_pkg / "text_boxes.json")
    next(box for box in boxes if box["role"] == "category")["anchor"] = "2024"
    write_json(good_pkg / "text_boxes.json", boxes)
    result = check_5_line_pixels(good_pkg)
    assert result["passed"] is False
    assert any("could not read the package" in reason for reason in result["details"]["reasons"])
