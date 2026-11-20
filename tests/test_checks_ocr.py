"""Tests for taskfactory.checks_ocr. Charts are hand-written specs."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytesseract
import pytest
from PIL import Image

from taskfactory import checks_ocr
from taskfactory.checks_ocr import check_4_ocr, run_ocr_check
from taskfactory.questions import make_questions
from taskfactory.render import render_bar
from taskfactory.render_line import render_line

DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

SPEC = {
    "spec_version": 1,
    "family": "bar",
    "domain": "retail",
    "index": 0,
    "seed": 3,
    "title": "Arrivals by region",
    "x_labels": ["North", "South", "East", "West"],
    "series": [
        {
            "name": "",
            "values": [40616457, 81143094, 67612874, 30777817],
            "labels": ["40.6M", "81.1M", "67.6M", "30.8M"],
        }
    ],
    "orientation": "vertical",
    "x_label_rotation": 0,
    "question_in_image": False,
}

ROTATED_SPEC = {
    "spec_version": 1,
    "family": "bar",
    "domain": "retail",
    "index": 0,
    "seed": 3,
    "title": "Arrivals by country",
    "x_labels": ["Netherlands", "Switzerland", "Portugal", "Denmark"],
    "series": [
        {
            "name": "",
            "values": [40616457, 81143094, 67612874, 30777817],
            "labels": ["40.6M", "81.1M", "67.6M", "30.8M"],
        }
    ],
    "orientation": "vertical",
    "x_label_rotation": 30,
    "question_in_image": False,
}

# The horizontal chart of the rejected bar-tourism-000003-value_lookup package.
HORIZONTAL_SPEC = {
    "spec_version": 1,
    "family": "bar",
    "domain": "tourism",
    "index": 3,
    "seed": 2130098123,
    "title": "International tourist arrivals (2016)",
    "x_labels": ["France", "Japan", "Turkey", "Mexico", "Spain"],
    "series": [
        {
            "name": "",
            "values": [51197900, 54604771, 3828490, 6683830, 65430990],
            "labels": ["51.2M", "54.6M", "3.8M", "6.7M", "65.4M"],
        }
    ],
    "orientation": "horizontal",
    "x_label_rotation": 30,
    "question_in_image": True,
}

HORIZONTAL_QUESTION = "What value is shown for Mexico?"


def _tesseract_command() -> str | None:
    """The executable the check would use, or None when it is absent."""
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


@pytest.fixture(scope="module")
def chart_png(tmp_path_factory):
    """Render the reference chart once; each test copies it into its package."""
    path = tmp_path_factory.mktemp("ocr-chart") / "image.png"
    render_bar(SPEC, path)
    return path


@pytest.fixture(scope="module")
def rotated_chart(tmp_path_factory):
    """A chart with 30-degree category labels, plus the boxes for its labels."""
    path = tmp_path_factory.mktemp("ocr-chart-rotated") / "image.png"
    boxes = render_bar(ROTATED_SPEC, path)
    return path, boxes


@pytest.fixture(scope="module")
def horizontal_chart(tmp_path_factory):
    """The horizontal chart from the rejected package, plus its text boxes."""
    path = tmp_path_factory.mktemp("ocr-chart-horizontal") / "image.png"
    boxes = render_bar(HORIZONTAL_SPEC, path, question=HORIZONTAL_QUESTION)
    return path, boxes


def make_package(tmp_path: Path, chart_png: Path) -> Path:
    """A package folder holding the chart and nothing else."""
    shutil.copyfile(chart_png, tmp_path / "image.png")
    return tmp_path


def write_task(pkg_dir: Path, **overrides) -> None:
    """Write task.json, defaulting to a value_lookup for the first bar."""
    task = {
        "task_type": "value_lookup",
        "question": "What value is shown for North?",
        "answer": "40.6M",
        "answer_category": "North",
        "question_in_image": False,
    }
    task.update(overrides)
    (pkg_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")


@needs_tesseract
def test_correct_answer_passes(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir)

    result = check_4_ocr(pkg_dir)

    assert result["check"] == "4_ocr"
    assert result["passed"] is True, result
    details = result["details"]
    assert details["required"] == ["40.6m", "north"]
    assert details["found"] == {"40.6m": True, "north": True}
    assert "40.6m" in details["ocr_text"]
    assert "north" in details["ocr_text"]
    assert details["tesseract_version"] != "unknown"
    json.dumps(details)  # details must be JSON-serialisable


@needs_tesseract
def test_answer_not_on_chart_fails(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir, answer="999.9M")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert result["details"]["found"]["999.9m"] is False


@needs_tesseract
def test_missing_answer_category_fails(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir, answer="40.6M", answer_category="Atlantis")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert result["details"]["found"] == {"40.6m": True, "atlantis": False}


@needs_tesseract
def test_extremum_does_not_require_a_category(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(
        pkg_dir,
        task_type="extremum",
        question="Which category has the highest value?",
        answer="South",
        answer_category="Atlantis",
    )

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    assert result["details"]["required"] == ["south"]


@needs_tesseract
def test_rotated_category_label_found_by_crop_pass(tmp_path, rotated_chart):
    chart_png, boxes = rotated_chart
    pkg_dir = make_package(tmp_path, chart_png)
    (pkg_dir / "text_boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
    write_task(
        pkg_dir,
        question="What value is shown for Switzerland?",
        answer="81.1M",
        answer_category="Switzerland",
    )

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    details = result["details"]
    assert details["required"] == ["81.1m", "switzerland"]
    assert details["found"] == {"81.1m": True, "switzerland": True}
    assert details["found_via"]["81.1m"] == "full"
    assert details["found_via"]["switzerland"] in {
        "crop_rot_0",
        "crop_rot_30",
        "crop_rot_-30",
    }
    json.dumps(details)  # details must be JSON-serialisable


@needs_tesseract
def test_value_label_found_by_upscaled_crop(tmp_path, horizontal_chart):
    chart_png, boxes = horizontal_chart
    pkg_dir = make_package(tmp_path, chart_png)
    (pkg_dir / "text_boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
    write_task(
        pkg_dir,
        question=HORIZONTAL_QUESTION,
        answer="6.7M",
        answer_category="Mexico",
    )

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    details = result["details"]
    assert details["required"] == ["6.7m", "mexico"]
    assert details["found"] == {"6.7m": True, "mexico": True}
    assert details["found_via"]["6.7m"] == "crop_value_x3"
    # The caption names Mexico but is masked, so Mexico is read from its category label.
    assert details["found_via"]["mexico"] == "crop_rot_0"
    json.dumps(details)  # details must be JSON-serialisable


@needs_tesseract
def test_run_ocr_check_matches_check_4_ocr(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir)

    assert run_ocr_check(pkg_dir) == check_4_ocr(pkg_dir)


def test_missing_task_json_raises(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)

    with pytest.raises(FileNotFoundError):
        check_4_ocr(pkg_dir)


def test_missing_image_raises(tmp_path):
    write_task(tmp_path)

    with pytest.raises(FileNotFoundError):
        check_4_ocr(tmp_path)


# A line chart with three series. The answer is a legend name.
LINE_SPEC = {
    "spec_version": 1,
    "family": "line",
    "domain": "tourism",
    "index": 0,
    "seed": 9,
    "title": "Units sold by product line",
    "x_labels": ["2020", "2021", "2022", "2023", "2024", "2025"],
    "series": [
        {
            "name": name,
            "values": values,
            "labels": [f"{value / 1_000_000:.1f}M" for value in values],
        }
        for name, values in (
            ("Alpha", [1_200_000, 1_350_000, 1_500_000, 1_420_000, 1_610_000, 1_780_000]),
            ("Beta", [900_000, 1_050_000, 1_100_000, 1_300_000, 1_400_000, 1_250_000]),
            ("Gamma", [700_000, 800_000, 950_000, 1_000_000, 1_150_000, 1_300_000]),
        )
    ],
    "orientation": "vertical",
    "x_label_rotation": 0,
    "question_in_image": False,
}


@pytest.fixture(scope="module")
def line_chart(tmp_path_factory):
    """The line chart above, plus the text boxes it drew (including the legend)."""
    path = tmp_path_factory.mktemp("ocr-line-chart") / "image.png"
    boxes = render_line(LINE_SPEC, path)
    return path, boxes


def _line_package(tmp_path, line_chart, answer):
    """A package holding the line chart, its text boxes, and a series_at_x task for ``answer``."""
    chart_png, boxes = line_chart
    pkg_dir = make_package(tmp_path, chart_png)
    (pkg_dir / "text_boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
    write_task(
        pkg_dir,
        task_type="series_at_x",
        question="Which series is highest in 2024?",
        answer=answer,
        answer_category=answer,
    )
    return pkg_dir


@needs_tesseract
def test_legend_name_found_by_legend_crop_when_the_full_read_misses_it(
    tmp_path, line_chart, monkeypatch
):
    pkg_dir = _line_package(tmp_path, line_chart, answer="Alpha")
    real_image_to_data = pytesseract.image_to_data

    def blind_full_page(image, *args, **kwargs):
        if isinstance(image, str):  # the full-page read sees nothing
            return {"text": [], "left": [], "top": [], "width": [], "height": []}
        return real_image_to_data(image, *args, **kwargs)

    monkeypatch.setattr(pytesseract, "image_to_data", blind_full_page)

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    details = result["details"]
    assert details["required"] == ["alpha"]
    assert details["found"] == {"alpha": True}
    assert details["found_via"] == {"alpha": "crop_legend_x3"}
    json.dumps(details)  # details must be JSON-serialisable


@needs_tesseract
def test_series_name_absent_from_the_legend_fails_ocr(tmp_path, line_chart):
    pkg_dir = _line_package(tmp_path, line_chart, answer="Zeta")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert result["details"]["found"] == {"zeta": False}
    assert "zeta" not in result["details"]["found_via"]


# --- the caption mask -----------------------------------------------------------------

# SPEC with its question printed as a caption. Its pair_compare question names South and
# West, and the answer is South, the side with the larger gap. Its value lookup asks for West.
CAPTIONED_SPEC = {**SPEC, "question_in_image": True}


def _captioned_package(tmp_path: Path, task_type: str) -> Path:
    """A package with CAPTIONED_SPEC drawn with its question, and the task of ``task_type``."""
    task = next(
        item for item in make_questions(CAPTIONED_SPEC) if item["task_type"] == task_type
    )
    boxes = render_bar(CAPTIONED_SPEC, tmp_path / "image.png", question=task["question"])
    (tmp_path / "text_boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
    (tmp_path / "task.json").write_text(json.dumps(task), encoding="utf-8")
    return tmp_path


def _paint_over(pkg_dir: Path, role: str, text: str) -> None:
    """Paint the ``role`` box that reads ``text`` white in image.png, with a 2 px margin."""
    boxes = json.loads((pkg_dir / "text_boxes.json").read_text(encoding="utf-8"))
    box = next(item for item in boxes if item["role"] == role and item["text"] == text)
    x0, y0, x1, y1 = box["bbox"]
    with Image.open(pkg_dir / "image.png") as source:
        picture = source.convert("RGB")
    picture.paste((255, 255, 255), (x0 - 2, y0 - 2, x1 + 2, y1 + 2))
    picture.save(pkg_dir / "image.png", format="PNG")


@needs_tesseract
@pytest.mark.parametrize("task_type", ["value_lookup", "extremum", "rank_k", "pair_compare"])
def test_captioned_package_passes_with_the_caption_masked(tmp_path, task_type):
    pkg_dir = _captioned_package(tmp_path, task_type)

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    assert result["details"]["caption_masked"] is True


@needs_tesseract
def test_answer_printed_only_in_the_caption_fails_ocr(tmp_path):
    pkg_dir = _captioned_package(tmp_path, "pair_compare")
    _paint_over(pkg_dir, "category", "South")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert result["details"]["caption_masked"] is True
    assert result["details"]["found"] == {"south": False}
    assert "south" not in result["details"]["found_via"]


@needs_tesseract
def test_category_named_only_in_the_caption_fails_ocr(tmp_path):
    pkg_dir = _captioned_package(tmp_path, "value_lookup")
    _paint_over(pkg_dir, "category", "West")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert result["details"]["found"] == {"30.8m": True, "west": False}


@needs_tesseract
def test_package_without_a_caption_is_not_masked(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir)

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is True, result
    assert result["details"]["caption_masked"] is False


def test_caption_box_without_a_usable_bbox_fails_the_check(tmp_path, chart_png):
    pkg_dir = make_package(tmp_path, chart_png)
    write_task(pkg_dir)
    caption = {"role": "caption", "text": "Which is higher, South or West?", "bbox": [1, 2, 3]}
    (pkg_dir / "text_boxes.json").write_text(json.dumps([caption]), encoding="utf-8")

    result = check_4_ocr(pkg_dir)

    assert result["passed"] is False, result
    assert "caption" in result["details"]["error"]
    assert result["details"]["caption_masked"] is False


def test_unreadable_image_with_a_caption_fails_the_check(tmp_path):
    (tmp_path / "image.png").write_bytes(b"not a png")
    write_task(tmp_path)
    caption = {"role": "caption", "text": "What value is shown for North?", "bbox": [0, 0, 10, 10]}
    (tmp_path / "text_boxes.json").write_text(json.dumps([caption]), encoding="utf-8")

    result = check_4_ocr(tmp_path)

    assert result["passed"] is False, result
    assert "caption" in result["details"]["error"]


def test_caption_mask_paints_each_box_plus_four_pixels():
    picture = Image.new("RGB", (30, 30), (0, 0, 0))

    painted = checks_ocr._paint_boxes(picture, [(10, 10, 14, 14)], 4)

    assert painted.getpixel((6, 6)) == (255, 255, 255)  # 4 px up and left of the box
    assert painted.getpixel((17, 17)) == (255, 255, 255)  # 4 px down and right of the box
    assert painted.getpixel((5, 5)) == (0, 0, 0)
    assert painted.getpixel((18, 18)) == (0, 0, 0)
    assert picture.getpixel((6, 6)) == (0, 0, 0)  # the source picture is not changed
