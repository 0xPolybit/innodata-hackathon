"""Tests for schema, layout, ambiguity and redraw checks on task packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from taskfactory.checks_layout import (
    check_1_schema,
    check_2_layout,
    check_3_ambiguity,
    check_7_redraw,
    run_layout_checks,
)
from taskfactory.render import render_bar
from taskfactory.render_line import render_line

DOMAIN = "retail"
CATEGORIES = ["North", "South", "East", "West"]
VALUES = [120, 85, 143, 97]
LABELS = ["120", "85", "143", "97"]
TITLE = "Units sold by region"


def make_spec(**overrides: Any) -> dict[str, Any]:
    """Hand-made bar spec with four categories and distinct values."""
    spec: dict[str, Any] = {
        "spec_version": 1,
        "family": "bar",
        "domain": DOMAIN,
        "index": 0,
        "seed": 7,
        "title": TITLE,
        "x_labels": list(CATEGORIES),
        "series": [
            {
                "name": "",
                "values": list(VALUES),
                "labels": list(LABELS),
            }
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }
    spec.update(overrides)
    return spec


def make_task(spec: dict[str, Any], task_type: str = "extremum") -> dict[str, Any]:
    """Ground-truth task derived from ``spec``, matching questions.make_questions."""
    values = spec["series"][0]["values"]
    labels = spec["series"][0]["labels"]
    categories = spec["x_labels"]
    if task_type == "extremum":
        position = values.index(max(values))
        question = "Which category has the highest value?"
        answer = categories[position]
        answer_category = categories[position]
        answer_value = max(values)
        reasoning_steps = len(categories)
    elif task_type == "rank_k":
        # The second-largest value, ranked largest first as questions.py ranks bars.
        ranked = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
        position = ranked[1]
        question = "Which category ranks second by value?"
        answer = categories[position]
        answer_category = categories[position]
        answer_value = values[position]
        reasoning_steps = len(categories)
    elif task_type == "pair_compare":
        # Compare the categories at positions 1 and 2; the larger one is the answer.
        position = max((1, 2), key=lambda i: values[i])
        question = f"Which is higher, {categories[1]} or {categories[2]}?"
        answer = categories[position]
        answer_category = categories[position]
        answer_value = values[position]
        reasoning_steps = 2
    else:
        position = 1
        question = f"What value is shown for {categories[position]}?"
        answer = labels[position]
        answer_category = categories[position]
        answer_value = values[position]
        reasoning_steps = 1
    return {
        "task_type": task_type,
        "family": spec["family"],
        "domain": spec["domain"],
        "spec_index": spec["index"],
        "question": question,
        "answer": answer,
        "answer_value": answer_value,
        "answer_category": answer_category,
        "reasoning_steps": reasoning_steps,
        "answer_printed_in_image": True,
        "question_in_image": spec["question_in_image"],
    }


def write_package(
    tmp_path: Path,
    *,
    spec: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    text_boxes: list[dict[str, Any]] | None = None,
) -> Path:
    """Render and write one package folder in ``tmp_path``."""
    spec = make_spec() if spec is None else spec
    task = make_task(spec) if task is None else task
    package_dir = tmp_path / "package"
    package_dir.mkdir(parents=True, exist_ok=True)

    question = task["question"] if spec["question_in_image"] else None
    rendered = render_bar(spec, package_dir / "image.png", question=question)
    boxes = rendered if text_boxes is None else text_boxes

    (package_dir / "spec.json").write_text(
        json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8"
    )
    (package_dir / "task.json").write_text(
        json.dumps(task, indent=2, sort_keys=True), encoding="utf-8"
    )
    (package_dir / "text_boxes.json").write_text(
        json.dumps(boxes, indent=2, sort_keys=True), encoding="utf-8"
    )
    return package_dir


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("task_type", ["extremum", "value_lookup"])
def test_good_package_passes_all_four_checks(
    tmp_path: Path, task_type: str
) -> None:
    spec = make_spec()
    package_dir = write_package(
        tmp_path, spec=spec, task=make_task(spec, task_type=task_type)
    )

    results = run_layout_checks(package_dir)

    assert [result["check"] for result in results] == [
        "1_schema",
        "2_layout",
        "3_ambiguity",
        "7_redraw",
    ]
    for result in results:
        assert result["passed"] is True, result
        json.dumps(result["details"])  # details stay JSON-serialisable

    assert results[2]["details"]["margin"] == pytest.approx((143 - 120) / 143)
    assert results[3]["details"]["image_sha256"] == results[3]["details"]["redraw_sha256"]
    assert results[3]["details"]["caption_matches"] is True


def test_value_box_outside_canvas_fails_layout(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    boxes = read_json(package_dir / "text_boxes.json")
    value_box = next(box for box in boxes if box["role"] == "value")
    value_box["bbox"] = [value_box["bbox"][0], -5, value_box["bbox"][2], value_box["bbox"][3]]
    write_json(package_dir / "text_boxes.json", boxes)

    result = check_2_layout(package_dir)

    assert result["passed"] is False
    assert result["details"]["outside_canvas"]
    assert result["details"]["outside_canvas"][0]["role"] == "value"


def test_two_overlapping_value_boxes_fail_layout(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    boxes = read_json(package_dir / "text_boxes.json")
    value_boxes = [box for box in boxes if box["role"] == "value"]
    value_boxes[1]["bbox"] = list(value_boxes[0]["bbox"])
    write_json(package_dir / "text_boxes.json", boxes)

    result = check_2_layout(package_dir)

    assert result["passed"] is False
    assert any(
        pair["kind"] == "value-value"
        for pair in result["details"]["overlapping_pairs"]
    )


def test_top_values_with_margin_0_01_fail_ambiguity(tmp_path: Path) -> None:
    spec = make_spec(
        series=[
            {
                "name": "",
                "values": [100, 99, 60, 10],
                "labels": ["100", "99", "60", "10"],
            }
        ]
    )
    package_dir = write_package(tmp_path, spec=spec)

    result = check_3_ambiguity(package_dir)

    assert result["passed"] is False
    assert result["details"]["margin"] == pytest.approx(0.01)
    assert "small_margin" in result["details"]["failed_rules"]


def test_changed_image_byte_fails_redraw(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    image_path = package_dir / "image.png"
    data = bytearray(image_path.read_bytes())
    data[-1] ^= 0xFF
    image_path.write_bytes(data)

    result = check_7_redraw(package_dir)

    assert result["passed"] is False
    assert result["details"]["hashes_match"] is False
    assert result["details"]["image_sha256"] != result["details"]["redraw_sha256"]


def test_missing_text_boxes_raises_file_not_found(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    (package_dir / "text_boxes.json").unlink()

    with pytest.raises(FileNotFoundError):
        check_2_layout(package_dir)


@pytest.mark.parametrize("task_type", ["extremum", "value_lookup"])
def test_wrong_answer_fails_schema(tmp_path: Path, task_type: str) -> None:
    spec = make_spec()
    task = make_task(spec, task_type=task_type)
    package_dir = write_package(tmp_path, spec=spec, task=task)
    written_task = read_json(package_dir / "task.json")
    written_task["answer"] = "not the right answer"
    write_json(package_dir / "task.json", written_task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"]
    assert any(
        failure["rule"].startswith("value_lookup")
        or failure["rule"].startswith("extremum")
        for failure in result["details"]["failures"]
    )


def test_package_without_question_in_image_passes_redraw(tmp_path: Path) -> None:
    spec = make_spec(question_in_image=False)
    package_dir = write_package(tmp_path, spec=spec)

    result = check_7_redraw(package_dir)

    assert result["passed"] is True
    assert result["details"]["caption_required"] is False
    assert result["details"]["hashes_match"] is True


def test_missing_caption_fails_redraw_even_when_bytes_match(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    boxes = read_json(package_dir / "text_boxes.json")
    write_json(
        package_dir / "text_boxes.json",
        [box for box in boxes if box["role"] != "caption"],
    )

    result = check_7_redraw(package_dir)

    assert result["passed"] is False
    assert result["details"]["hashes_match"] is True
    assert result["details"]["caption_matches"] is False
    assert "caption_missing" in result["details"]["failed_rules"]


def test_duplicate_labels_fail_ambiguity(tmp_path: Path) -> None:
    spec = make_spec(
        series=[
            {
                "name": "",
                "values": [143, 120, 85, 97],
                "labels": ["143", "143", "85", "97"],
            }
        ]
    )
    package_dir = write_package(tmp_path, spec=spec)

    result = check_3_ambiguity(package_dir)

    assert result["passed"] is False
    assert result["details"]["duplicate_labels"] == ["143"]


def test_font_below_minimum_fails_layout(tmp_path: Path) -> None:
    package_dir = write_package(tmp_path)
    boxes = read_json(package_dir / "text_boxes.json")
    next(box for box in boxes if box["role"] == "footer")["font_px"] = 8
    write_json(package_dir / "text_boxes.json", boxes)

    result = check_2_layout(package_dir)

    assert result["passed"] is False
    assert result["details"]["small_font_boxes"]


# --- bar packages of the rank_k and pair_compare types ------------------------------


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
@pytest.mark.parametrize("task_type", ["rank_k", "pair_compare"])
def test_good_rank_k_and_pair_compare_packages_pass_schema(
    tmp_path: Path, orientation: str, task_type: str
) -> None:
    spec = make_spec(orientation=orientation)
    package_dir = write_package(tmp_path, spec=spec, task=make_task(spec, task_type=task_type))

    result = check_1_schema(package_dir)

    assert result["check"] == "1_schema"
    assert result["passed"] is True, result["details"]["failures"]
    assert result["details"]["task_type"] == task_type


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_rank_k_answer_at_another_rank_fails_schema(tmp_path: Path, orientation: str) -> None:
    spec = make_spec(orientation=orientation)
    task = make_task(spec, task_type="rank_k")
    task["answer"] = task["answer_category"] = "East"  # East is first by value, not second
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["rank_k_answer"]


def test_rank_k_wrong_answer_value_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="rank_k")
    task["answer_value"] = 143  # North, at rank two, is worth 120
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["rank_k_answer_value"]


def test_rank_k_question_without_a_rank_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="rank_k")
    task["question"] = "Which category ranks highest?"
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["rank_k_question"]


def test_rank_k_beyond_the_last_category_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()  # four categories
    task = make_task(spec, task_type="rank_k")
    task["question"] = "Which category ranks eighth by value?"
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["rank_k_rank"]


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_pair_compare_answer_that_is_the_smaller_name_fails_schema(
    tmp_path: Path, orientation: str
) -> None:
    spec = make_spec(orientation=orientation)
    task = make_task(spec, task_type="pair_compare")  # East (143) is higher than South (85)
    task["answer"] = task["answer_category"] = "South"
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["pair_compare_answer"]


def test_pair_compare_name_missing_from_the_spec_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="pair_compare")
    task["question"] = "Which is higher, South or Atlantis?"
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    # The pair is not read (pair_compare_names), and the name the spec lacks is also reported.
    assert result["passed"] is False
    assert result["details"]["failed_rules"] == [
        "pair_compare_names",
        "question_entity_not_in_chart",
    ]


def test_pair_compare_wrong_answer_value_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="pair_compare")
    task["answer_value"] = 85  # East, the answer, is worth 143
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["pair_compare_answer_value"]


# --- line packages: series_at_x schema and legend boxes ---------------------------

LINE_YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]
LINE_SERIES = [
    ("Alpha", [1_200_000, 1_350_000, 1_500_000, 1_420_000, 1_610_000, 1_780_000]),
    ("Beta", [900_000, 1_050_000, 1_100_000, 1_300_000, 1_400_000, 1_250_000]),
    ("Gamma", [700_000, 800_000, 950_000, 1_000_000, 1_150_000, 1_300_000]),
]


def make_line_spec() -> dict[str, Any]:
    """A three-series line spec. In 2024 Alpha is on top (1.61M), then Beta (1.40M)."""
    return {
        "spec_version": 1,
        "family": "line",
        "domain": DOMAIN,
        "index": 0,
        "seed": 11,
        "title": "Units sold by product line",
        "x_labels": list(LINE_YEARS),
        "series": [
            {
                "name": name,
                "values": list(values),
                "labels": [f"{value / 1_000_000:.1f}M" for value in values],
            }
            for name, values in LINE_SERIES
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }


def make_series_task(spec: dict[str, Any], year: str = "2024") -> dict[str, Any]:
    """The series_at_x task for the series highest at ``year``, with the keys questions.py writes."""
    position = spec["x_labels"].index(year)
    at_year = {entry["name"]: entry["values"][position] for entry in spec["series"]}
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
        "answer_printed_in_image": True,
        "question_in_image": spec["question_in_image"],
    }


def write_line_package(tmp_path: Path, spec: dict[str, Any], task: dict[str, Any]) -> Path:
    """Draw ``spec`` and write the files a run writes: picture, spec, task and text boxes."""
    package_dir = tmp_path / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    question = task["question"] if spec["question_in_image"] else None
    boxes = render_line(spec, package_dir / "image.png", question=question)
    write_json(package_dir / "spec.json", spec)
    write_json(package_dir / "task.json", task)
    write_json(package_dir / "text_boxes.json", boxes)
    return package_dir


def test_good_series_at_x_package_passes_schema(tmp_path: Path) -> None:
    spec = make_line_spec()
    package_dir = write_line_package(tmp_path, spec, make_series_task(spec))

    result = check_1_schema(package_dir)

    assert result["check"] == "1_schema"
    assert result["passed"] is True, result["details"]["failures"]
    assert result["details"]["task_type"] == "series_at_x"


def test_series_at_x_answer_that_is_no_series_fails_schema(tmp_path: Path) -> None:
    spec = make_line_spec()
    task = make_series_task(spec)
    task["answer"] = task["answer_category"] = "Atlantis"
    package_dir = write_line_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert "series_at_x_answer_series" in result["details"]["failed_rules"]


def test_series_at_x_wrong_answer_value_fails_schema(tmp_path: Path) -> None:
    spec = make_line_spec()
    task = make_series_task(spec)
    task["answer_value"] = 1_000_000  # Alpha's value in 2024 is 1_610_000
    package_dir = write_line_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["series_at_x_answer_value"]


def test_series_at_x_on_a_bar_spec_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec)
    task["task_type"] = "series_at_x"
    package_dir = write_package(tmp_path, spec=spec, task=task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert "series_at_x_spec_family" in result["details"]["failed_rules"]


def test_line_package_with_legend_boxes_passes_layout(tmp_path: Path) -> None:
    spec = make_line_spec()
    package_dir = write_line_package(tmp_path, spec, make_series_task(spec))
    boxes = read_json(package_dir / "text_boxes.json")
    assert [box["text"] for box in boxes if box["role"] == "legend"] == ["Alpha", "Beta", "Gamma"]

    result = check_2_layout(package_dir)

    assert result["passed"] is True, result["details"]


def test_legend_box_over_a_category_label_fails_layout(tmp_path: Path) -> None:
    spec = make_line_spec()
    package_dir = write_line_package(tmp_path, spec, make_series_task(spec))
    boxes = read_json(package_dir / "text_boxes.json")
    legend = next(box for box in boxes if box["role"] == "legend")
    category = next(box for box in boxes if box["role"] == "category")
    legend["bbox"] = list(category["bbox"])
    write_json(package_dir / "text_boxes.json", boxes)

    result = check_2_layout(package_dir)

    assert result["passed"] is False
    assert any(
        pair["kind"] == "legend-category" for pair in result["details"]["overlapping_pairs"]
    )


# --- question entities: the category or year a question names ----------------------
# Check 1 reads spec.json and task.json only, so these packages are written without a picture.


def write_schema_package(tmp_path: Path, spec: dict[str, Any], task: dict[str, Any]) -> Path:
    """Write spec.json and task.json, the two files check 1 reads."""
    package_dir = tmp_path / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    write_json(package_dir / "spec.json", spec)
    write_json(package_dir / "task.json", task)
    return package_dir


def test_value_lookup_question_naming_a_category_of_the_chart_passes_schema(
    tmp_path: Path,
) -> None:
    spec = make_spec()
    package_dir = write_schema_package(tmp_path, spec, make_task(spec, task_type="value_lookup"))

    result = check_1_schema(package_dir)

    assert result["passed"] is True, result["details"]["failures"]
    assert result["details"]["failed_rules"] == []


def test_value_lookup_question_naming_a_category_not_in_the_chart_fails_schema(
    tmp_path: Path,
) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="value_lookup")
    task["question"] = "What value is shown for Atlantis?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["question_entity_not_in_chart"]
    assert "Atlantis" in result["details"]["failures"][0]["message"]


def test_value_lookup_question_naming_another_category_fails_schema(tmp_path: Path) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="value_lookup")  # answers South, whose label is 85
    task["question"] = "What value is shown for North?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["question_entity_mismatch"]


def test_series_at_x_question_naming_a_year_outside_the_spec_fails_schema(
    tmp_path: Path,
) -> None:
    spec = make_line_spec()
    task = make_series_task(spec)  # the task's year is 2024
    task["question"] = "Which series is highest in 2099?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["question_entity_not_in_chart"]


def test_series_at_x_question_naming_another_year_fails_schema(tmp_path: Path) -> None:
    spec = make_line_spec()
    task = make_series_task(spec)  # the task's year is 2024
    task["question"] = "Which series is highest in 2023?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is False
    assert result["details"]["failed_rules"] == ["question_entity_mismatch"]


def test_pair_compare_question_naming_two_names_outside_the_spec_reports_both(
    tmp_path: Path,
) -> None:
    spec = make_spec()
    task = make_task(spec, task_type="pair_compare")
    task["question"] = "Which is higher, Atlantis or Lemuria?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["details"]["failed_rules"] == [
        "pair_compare_names",
        "question_entity_not_in_chart",
    ]
    message = next(
        failure["message"]
        for failure in result["details"]["failures"]
        if failure["rule"] == "question_entity_not_in_chart"
    )
    assert "'Atlantis'" in message and "'Lemuria'" in message


def test_pair_compare_question_with_a_category_name_containing_or_passes_schema(
    tmp_path: Path,
) -> None:
    # "Trinidad or Tobago" is one category. The question names it and East, and East (143)
    # is the larger of the two values, 120 and 143.
    spec = make_spec(x_labels=["Trinidad or Tobago", "South", "East", "West"])
    task = make_task(spec, task_type="pair_compare")  # East, the larger of South and East
    task["question"] = "Which is higher, Trinidad or Tobago or East?"
    package_dir = write_schema_package(tmp_path, spec, task)

    result = check_1_schema(package_dir)

    assert result["passed"] is True, result["details"]["failures"]
    assert result["details"]["failed_rules"] == []
