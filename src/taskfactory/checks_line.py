"""Line-chart checks 3, 5, 6 and 7: the line counterparts of the bar checks.

Each check reads one package folder for a ``series_at_x`` task and returns a
result dict::

    {"check": "<name>", "passed": bool, "details": {...}}

``details`` is always JSON-serialisable. Bad content never raises: an unreadable
or inconsistent file is reported as ``passed`` False with the reasons listed in
``details``. Only a required file that is missing raises FileNotFoundError.

- Check 3 (``3_line_ambiguity``) reads spec.json and task.json. At the task's year
  the top two values must differ by at least ``min_margin`` of the largest value,
  no two series may share a name, and the answer must be the one series with the
  largest value there.
- Check 5 (``5_line_pixels``) reads image.png, text_boxes.json and task.json only.
  The year's column is x-3 .. x+3 around the year's data point: the ``anchor`` x of
  its category box, which the renderer records exactly. A package with no anchor
  falls back to the centre of its label box, and ``details["x_source"]`` says which
  was used. Each series colour is the most frequent saturated colour in the strip
  just left of its legend text, which holds the legend handle. The mean row of pixels
  in that colour at the year column is the series' height, and the series nearest the
  top of the plot is the answer. Rows 80 to 689 bound the reading. The legend sits in
  a strip above the plot, and its zone (its text box widened to take in the handle and
  frame edge) is never read.
- Check 6 (``6_line_counterfactual``) sinks the answer series at the year in a copy
  of the spec, redraws that copy with ``render_line``, and requires check 5 to read
  the new answer from the new picture.
- Check 7 (``7_line_redraw``) redraws the spec and requires the PNG bytes to equal
  ``image.png``.

``run_line_checks`` returns checks 3, 5, 6 and 7 in that order.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from PIL import Image

from taskfactory.render_line import render_line
from taskfactory.sampler import format_value, validate_spec

__all__ = [
    "check_3_line_ambiguity",
    "check_5_line_pixels",
    "check_6_line_counterfactual",
    "check_7_line_redraw",
    "run_line_checks",
]

CHECK_3 = "3_line_ambiguity"
CHECK_5 = "5_line_pixels"
CHECK_6 = "6_line_counterfactual"
CHECK_7 = "7_line_redraw"

SPEC_NAME = "spec.json"
TASK_NAME = "task.json"
TEXT_BOXES_NAME = "text_boxes.json"
IMAGE_NAME = "image.png"

CANVAS_W = 1200
CANVAS_H = 800
CATEGORY_ROLE = "category"
LEGEND_ROLE = "legend"

COLOUR_TOLERANCE = 24  # per channel, when a pixel is matched to a series colour
STRIP_NEAR_PX = 40  # the colour strip starts this far left of the legend text ...
STRIP_FAR_PX = 6  # ... and stops this far left of it
MIN_SATURATION = 40  # max channel minus min channel, for a series colour
NEAR_WHITE_MIN = 235  # a pixel whose channels are all at least this is near-white
YEAR_HALF_WIDTH = 3  # the year column is x-3 .. x+3
MIN_COLUMN_PIXELS = 3
PLOT_TOP = 80  # first row read; the legend strip sits above the plot, inside these rows
PLOT_BOTTOM = 690  # first row below the plot area; the x axis and labels sit there
PLOT_HEIGHT_PX = PLOT_BOTTOM - PLOT_TOP  # 610, the denominator of gap_fraction
LEGEND_LEFT_PAD = 60  # legend zone: this far left of the text (frame edge and handle) ...
LEGEND_PAD = 6  # ... and this far past the text on the other sides

LIFT = 1000  # check 6: the answer is lifted this far above the year's top value when it cannot sink
MILLIONS_FORMAT = "{:.1f}M"  # the label format when every label ends with "M"
PLAIN_FORMAT = "{:,}"  # the label format otherwise


class _Malformed(Exception):
    """The spec cannot be read as a line spec. The message is the reason."""


class _CannotAlter(Exception):
    """The package cannot be altered and redrawn. The message is the reason."""


class _Box(NamedTuple):
    """A text box from text_boxes.json in pixels, origin top-left; x1 and y1 are exclusive.

    ``anchor_x`` is the pixel column of the box's data point when the box has an
    ``anchor``, and None when it has none.
    """

    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    anchor_x: int | None = None


class _Alteration(NamedTuple):
    """The altered spec, and the series that is highest at the year after the change."""

    spec: dict[str, Any]
    answer: str
    value: int


def check_3_line_ambiguity(pkg_dir: Path, min_margin: float = 0.05) -> dict[str, Any]:
    """Check that the top two values at the year are distinct enough and the answer is the top.

    The relative margin at the year is ``(largest - second) / largest``; it must be at
    least ``min_margin``. Repeated series names fail, and so does an answer that is not
    the single largest series at the year.

    Raises FileNotFoundError when spec.json or task.json is missing.
    """
    pkg = Path(pkg_dir)
    _require(pkg, SPEC_NAME, TASK_NAME)
    details: dict[str, Any] = {
        "year": None,
        "answer": None,
        "top_series": None,
        "values_at_year": {},
        "largest": None,
        "second_largest": None,
        "margin": None,
        "min_margin": min_margin,
        "failed_rules": [],
        "reasons": [],
    }
    try:
        spec = _read_json(pkg / SPEC_NAME)
        task = _read_json(pkg / TASK_NAME)
    except (OSError, ValueError) as exc:
        _flag(details, "readable_files", f"could not read the package: {exc}")
        return _result(CHECK_3, False, details)
    if not isinstance(task, dict):
        _flag(details, "task_object", "task.json must hold a JSON object")
        return _result(CHECK_3, False, details)
    try:
        x_labels, series = _spec_series(spec)
    except _Malformed as exc:
        _flag(details, "spec_structure", str(exc))
        return _result(CHECK_3, False, details)

    year = _text_or_none(task.get("year"))
    answer = _text_or_none(task.get("answer"))
    details["year"] = year
    details["answer"] = answer
    names = [name for name, _ in series]
    if len(set(names)) != len(names):
        repeated = sorted({name for name in names if names.count(name) > 1})
        _flag(details, "duplicate_series_names", f"series names repeat: {repeated}")
    if year not in x_labels:
        _flag(details, "year_in_labels", f"task.year {year!r} is not one of the spec's years")
        return _result(CHECK_3, False, details)

    j = x_labels.index(year)
    at_year = [(name, values[j]) for name, values in series]
    details["values_at_year"] = dict(at_year)
    ranked = sorted((value for _, value in at_year), reverse=True)
    largest, second = ranked[0], ranked[1]  # _spec_series guarantees two or three series
    details["largest"] = largest
    details["second_largest"] = second
    if largest <= 0:
        _flag(details, "margin_undefined", f"the largest value at {year} is {largest}")
    else:
        margin = (largest - second) / largest
        details["margin"] = margin
        if margin < min_margin:
            _flag(
                details,
                "small_margin",
                f"the top two values at {year} differ by {margin:.4f} of the largest, "
                f"below {min_margin}",
            )
    tops = [name for name, value in at_year if value == largest]
    if len(tops) != 1:
        _flag(details, "tied_top", f"{len(tops)} series share the largest value at {year}")
    else:
        details["top_series"] = tops[0]
        if answer != tops[0]:
            _flag(
                details,
                "answer_not_top",
                f"task.answer {answer!r} is not the series with the largest value at {year}, "
                f"which is {tops[0]!r}",
            )
    return _result(CHECK_3, not details["failed_rules"], details)


def check_5_line_pixels(pkg_dir: Path) -> dict[str, Any]:
    """Recompute a line chart's answer from its picture alone and compare it with task.json.

    The year's column is centred on its category box's ``anchor``, the data point's x.
    Without an anchor the centre of the label box is used, and ``details["x_source"]``
    records which of the two was read.

    Raises FileNotFoundError when image.png, text_boxes.json or task.json is missing.
    Unreadable files and every failed rule return ``passed`` False.
    """
    pkg = Path(pkg_dir)
    _require(pkg, IMAGE_NAME, TEXT_BOXES_NAME, TASK_NAME)
    details = _pixel_details()
    reasons: list[str] = details["reasons"]
    try:
        image = _read_rgb(pkg / IMAGE_NAME)
        task = _read_json(pkg / TASK_NAME)
        raw_boxes = _read_json(pkg / TEXT_BOXES_NAME)
        legend = _text_boxes(raw_boxes, LEGEND_ROLE)
        categories = _text_boxes(raw_boxes, CATEGORY_ROLE)
    except (OSError, ValueError) as exc:
        reasons.append(f"could not read the package: {exc}")
        return _result(CHECK_5, False, details)
    if not isinstance(task, dict):
        reasons.append("task.json must hold a JSON object")
        return _result(CHECK_5, False, details)

    year = _text_or_none(task.get("year"))
    expected = _text_or_none(task.get("answer"))
    details["year"] = year
    details["expected_answer"] = expected

    height, width = image.shape[:2]
    if (width, height) != (CANVAS_W, CANVAS_H):
        reasons.append(
            f"the picture is {width} x {height}; the line reader expects {CANVAS_W} x {CANVAS_H}"
        )
        return _result(CHECK_5, False, details)
    year_box = _find_year_box(categories, year, reasons)
    if year_box is None:
        return _result(CHECK_5, False, details)
    if year_box.anchor_x is not None:
        column = year_box.anchor_x
        details["x_source"] = "anchor"
    else:
        column = math.floor((year_box.x0 + year_box.x1) / 2)
        details["x_source"] = "box_centre"
    details["year_column"] = column
    if not 2 <= len(legend) <= 3:
        reasons.append(f"found {len(legend)} legend entries; a line chart has 2 or 3")
        return _result(CHECK_5, False, details)
    names = [box.text for box in legend]
    if len(set(names)) != len(names):
        reasons.append(f"two legend entries share a name: {names}")

    colours: dict[str, tuple[int, int, int]] = {}
    for box in legend:
        colour = _series_colour(image, box)
        if colour is None:
            reasons.append(f"no series colour beside the legend entry {box.text!r}")
        else:
            colours[box.text] = colour
    details["colours"] = {name: list(colour) for name, colour in colours.items()}
    for (name_a, colour_a), (name_b, colour_b) in combinations(colours.items(), 2):
        if _max_gap(colour_a, colour_b) <= COLOUR_TOLERANCE:
            reasons.append(f"the colours of {name_a!r} and {name_b!r} are too close to tell apart")

    if not 0 <= column < width:
        reasons.append(f"the {year} column lies outside the picture")
        return _result(CHECK_5, False, details)
    lo = max(0, column - YEAR_HALF_WIDTH)
    hi = min(width - 1, column + YEAR_HALF_WIDTH)
    zones = [_legend_zone(box) for box in legend]
    y_positions: dict[str, float] = {}
    for name, colour in colours.items():
        mean_row, count = _colour_rows(image, colour, lo, hi, zones)
        if mean_row is None or count < MIN_COLUMN_PIXELS:
            reasons.append(
                f"only {count} pixels of {name!r}'s colour in the {year} column; "
                f"need {MIN_COLUMN_PIXELS}"
            )
        else:
            y_positions[name] = mean_row
    details["y_positions"] = {name: round(y, 3) for name, y in y_positions.items()}

    pixel_answer: str | None = None
    gap: float | None = None
    if len(colours) == len(legend) and len(y_positions) == len(legend):
        ranked = sorted(y_positions.items(), key=lambda item: item[1])
        (best, best_y), (second, second_y) = ranked[0], ranked[1]
        if best_y == second_y:
            reasons.append(f"{best!r} and {second!r} sit at the same height in {year}")
        else:
            pixel_answer = best
            gap = (second_y - best_y) / PLOT_HEIGHT_PX
    details["pixel_answer"] = pixel_answer
    details["gap_fraction"] = gap
    if pixel_answer is not None and pixel_answer != expected:
        reasons.append(f"pixel answer {pixel_answer!r} does not match expected {expected!r}")
    passed = pixel_answer is not None and pixel_answer == expected and not reasons
    return _result(CHECK_5, passed, details)


def check_6_line_counterfactual(pkg_dir: Path) -> dict[str, Any]:
    """Sink the answer series at the year, redraw it, and require check 5 to read the new answer.

    The check passes only when the answer changes, the pixel reader passes the redrawn
    package, and its pixel answer equals the new answer.

    Raises FileNotFoundError when spec.json or task.json is missing. Bad content returns
    ``passed`` False with the reasons in ``details["reasons"]``.
    """
    pkg = Path(pkg_dir)
    _require(pkg, SPEC_NAME, TASK_NAME)
    details = _counterfactual_details()
    reasons: list[str] = details["reasons"]
    try:
        spec = _read_json(pkg / SPEC_NAME)
        task = _read_json(pkg / TASK_NAME)
    except (OSError, ValueError) as exc:
        reasons.append(f"could not read the package: {exc}")
        return _result(CHECK_6, False, details)
    if not isinstance(task, dict):
        reasons.append("task.json must hold a JSON object")
        return _result(CHECK_6, False, details)

    original = _text_or_none(task.get("answer"))
    details["year"] = _text_or_none(task.get("year"))
    details["original_answer"] = original
    try:
        validate_spec(spec)
    except Exception as exc:  # validate_spec raises ValueError; be defensive anyway.
        reasons.append(f"spec.json failed validate_spec: {type(exc).__name__}: {exc}")
        return _result(CHECK_6, False, details)
    if spec.get("family") != "line":
        reasons.append(f"check 6 redraws line specs only, not family {spec.get('family')!r}")
        return _result(CHECK_6, False, details)

    try:
        altered = _alter(spec, task)
    except _CannotAlter as exc:
        reasons.append(str(exc))
        return _result(CHECK_6, False, details)
    details["altered_answer"] = altered.answer
    details["altered_value"] = altered.value
    details["changed"] = altered.answer != original
    if not details["changed"]:
        reasons.append(f"the altered data still gives the original answer {original!r}")
        return _result(CHECK_6, False, details)

    try:
        validate_spec(altered.spec)
    except Exception as exc:  # validate_spec raises ValueError; be defensive anyway.
        reasons.append(f"the altered spec failed validate_spec: {type(exc).__name__}: {exc}")
        return _result(CHECK_6, False, details)

    try:
        reader = _redraw_and_read(altered, task)
    except _CannotAlter as exc:
        reasons.append(str(exc))
        return _result(CHECK_6, False, details)

    reader_details = reader.get("details")
    if not isinstance(reader_details, dict):
        reader_details = {}
    reader_passed = reader.get("passed") is True
    pixel_answer = _text_or_none(reader_details.get("pixel_answer"))
    details["reader_passed"] = reader_passed
    details["pixel_answer_after_redraw"] = pixel_answer
    if not reader_passed:
        reasons.append("the pixel reader did not pass the redrawn package")
        reader_reasons = reader_details.get("reasons")
        if isinstance(reader_reasons, list):
            reasons.extend(f"pixel reader: {reason}" for reason in reader_reasons)
    if pixel_answer != altered.answer:
        reasons.append(
            f"the pixel reader answered {pixel_answer!r}, not the altered answer {altered.answer!r}"
        )
    passed = details["changed"] and reader_passed and pixel_answer == altered.answer
    return _result(CHECK_6, passed, details)


def check_7_line_redraw(pkg_dir: Path) -> dict[str, Any]:
    """Redraw the spec with render_line and require the PNG bytes to equal image.png.

    The question is printed only when the spec says so, as in a run. Raises
    FileNotFoundError when spec.json, task.json or image.png is missing.
    """
    pkg = Path(pkg_dir)
    _require(pkg, SPEC_NAME, TASK_NAME, IMAGE_NAME)
    details: dict[str, Any] = {
        "image_sha256": None,
        "redraw_sha256": None,
        "hashes_match": False,
        "question_in_image": False,
        "reasons": [],
    }
    reasons: list[str] = details["reasons"]
    try:
        spec = _read_json(pkg / SPEC_NAME)
        task = _read_json(pkg / TASK_NAME)
        image_bytes = (pkg / IMAGE_NAME).read_bytes()
    except (OSError, ValueError) as exc:
        reasons.append(f"could not read the package: {exc}")
        return _result(CHECK_7, False, details)
    details["image_sha256"] = hashlib.sha256(image_bytes).hexdigest()
    if not isinstance(spec, dict) or not isinstance(task, dict):
        reasons.append("spec.json and task.json must each hold a JSON object")
        return _result(CHECK_7, False, details)

    question_in_image = spec.get("question_in_image") is True
    details["question_in_image"] = question_in_image
    question = task.get("question") if question_in_image else None
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_png = Path(temp_dir) / IMAGE_NAME
            render_line(spec, temp_png, question=question)
            redraw_bytes = temp_png.read_bytes()
    except Exception as exc:  # render_line raises ValueError for a spec it cannot draw.
        reasons.append(f"the spec cannot be drawn: {type(exc).__name__}: {exc}")
        return _result(CHECK_7, False, details)

    details["redraw_sha256"] = hashlib.sha256(redraw_bytes).hexdigest()
    details["hashes_match"] = details["redraw_sha256"] == details["image_sha256"]
    if not details["hashes_match"]:
        reasons.append("the redrawn PNG differs from image.png")
    return _result(CHECK_7, details["hashes_match"], details)


def run_line_checks(pkg_dir: Path, min_margin: float = 0.05) -> list[dict[str, Any]]:
    """Run checks 3, 5, 6 and 7 in order and return their result dicts."""
    return [
        check_3_line_ambiguity(pkg_dir, min_margin=min_margin),
        check_5_line_pixels(pkg_dir),
        check_6_line_counterfactual(pkg_dir),
        check_7_line_redraw(pkg_dir),
    ]


# --- check 5 helpers -------------------------------------------------------------


def _find_year_box(categories: list[_Box], year: str | None, reasons: list[str]) -> _Box | None:
    """The one category label that reads ``year``, or None with the reason."""
    if year is None:
        reasons.append("task.json has no year")
        return None
    hits = [box for box in categories if box.text == year]
    if not hits:
        reasons.append(f"no category label reads {year!r} in the picture")
        return None
    if len(hits) > 1:
        reasons.append(f"{len(hits)} category labels read {year!r}")
        return None
    return hits[0]


def _series_colour(image: np.ndarray, box: _Box) -> tuple[int, int, int] | None:
    """The most frequent saturated, not near-white colour in the strip left of a legend text box.

    The strip runs from 40 px to 6 px left of the text, over the text's rows. It holds
    the legend handle, the only series-coloured pixels there. None when no pixel qualifies.
    """
    height, width = image.shape[:2]
    left = max(0, box.x0 - STRIP_NEAR_PX)
    right = min(width, max(0, box.x0 - STRIP_FAR_PX))
    top = max(0, box.y0)
    bottom = min(height, box.y1)
    if right <= left or bottom <= top:
        return None
    pixels = image[top:bottom, left:right].reshape(-1, 3)
    high = pixels.max(axis=1).astype(np.int16)
    low = pixels.min(axis=1).astype(np.int16)
    keep = (high - low >= MIN_SATURATION) & (low < NEAR_WHITE_MIN)
    if not keep.any():
        return None
    colours, counts = np.unique(pixels[keep], axis=0, return_counts=True)
    best = colours[int(np.argmax(counts))]
    return (int(best[0]), int(best[1]), int(best[2]))


def _legend_zone(box: _Box) -> tuple[int, int, int, int]:
    """The legend entry's area, as (x0, y0, x1, y1) with x1 and y1 exclusive.

    It takes in the handle and the frame's left edge, which lie left of the text, and
    a small margin on the other sides. Pixels here are legend, not plot.
    """
    return (
        box.x0 - LEGEND_LEFT_PAD,
        box.y0 - LEGEND_PAD,
        box.x1 + LEGEND_PAD,
        box.y1 + LEGEND_PAD,
    )


def _colour_rows(
    image: np.ndarray,
    colour: tuple[int, int, int],
    lo: int,
    hi: int,
    zones: list[tuple[int, int, int, int]],
) -> tuple[float | None, int]:
    """Mean row of the plot pixels within tolerance of ``colour`` in columns lo..hi.

    Rows outside PLOT_TOP .. PLOT_BOTTOM - 1 and pixels inside a legend zone are
    ignored. Returns (None, 0) when nothing matches.
    """
    band = image[PLOT_TOP:PLOT_BOTTOM, lo : hi + 1].astype(np.int16)
    target = np.array(colour, dtype=np.int16)
    mask = np.abs(band - target).max(axis=2) <= COLOUR_TOLERANCE
    for x0, y0, x1, y1 in zones:
        r0 = max(y0, PLOT_TOP) - PLOT_TOP
        r1 = min(y1, PLOT_BOTTOM) - PLOT_TOP
        c0 = max(x0, lo) - lo
        c1 = min(x1, hi + 1) - lo
        if r0 < r1 and c0 < c1:
            mask[r0:r1, c0:c1] = False
    rows = np.nonzero(mask)[0] + PLOT_TOP
    if rows.size == 0:
        return None, 0
    return float(rows.mean()), int(rows.size)


def _max_gap(first: tuple[int, int, int], second: tuple[int, int, int]) -> int:
    """Largest per-channel difference between two colours."""
    return max(abs(a - b) for a, b in zip(first, second))


def _text_boxes(raw: Any, role: str) -> list[_Box]:
    """The text boxes of one role, read from the parsed text_boxes.json.

    A box that has an ``anchor`` key must give it as two numbers. A malformed anchor
    raises ValueError, which makes the package unreadable.
    """
    if not isinstance(raw, list):
        raise ValueError("text_boxes.json must hold a list")
    boxes: list[_Box] = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("role") != role:
            continue
        bbox = entry.get("bbox")
        if not _is_numbers(bbox, 4):
            raise ValueError(f"a {role} box needs a bbox of four numbers, got {bbox!r}")
        anchor_x = None
        if "anchor" in entry:
            anchor = entry["anchor"]
            if not _is_numbers(anchor, 2):
                raise ValueError(f"a {role} box needs an anchor of two numbers, got {anchor!r}")
            anchor_x = round(anchor[0])
        x0, y0, x1, y1 = (int(v) for v in bbox)
        boxes.append(_Box(str(entry.get("text", "")), x0, y0, x1, y1, anchor_x))
    return boxes


def _is_numbers(value: Any, count: int) -> bool:
    """True for a list of ``count`` finite numbers, none of them a bool."""
    return (
        isinstance(value, list)
        and len(value) == count
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in value
        )
    )


def _pixel_details() -> dict[str, Any]:
    """The check 5 details, with nothing measured yet."""
    return {
        "year": None,
        "x_source": None,
        "year_column": None,
        "colours": {},
        "y_positions": {},
        "pixel_answer": None,
        "expected_answer": None,
        "gap_fraction": None,
        "reasons": [],
    }


# --- check 6 helpers -------------------------------------------------------------


def _alter(spec: dict[str, Any], task: dict[str, Any]) -> _Alteration:
    """Return a copy of ``spec`` with the answer series sunk at the year, and the new top there.

    The answer series takes the value 0 when the year's smallest value is above 0. Otherwise
    it takes the year's largest value plus LIFT, which keeps it on top. When the answer is
    still the highest after the change, or two series tie for the top, this raises
    _CannotAlter with the reason.
    """
    try:
        x_labels, series = _spec_series(spec)
    except _Malformed as exc:
        raise _CannotAlter(str(exc)) from exc
    names = [name for name, _ in series]
    if len(set(names)) != len(names):
        raise _CannotAlter("the spec's series names are not unique")
    year = _text_or_none(task.get("year"))
    if year not in x_labels:
        raise _CannotAlter(f"task.year {year!r} is not one of the spec's years")
    j = x_labels.index(year)
    answer = _text_or_none(task.get("answer"))
    if answer not in names:
        raise _CannotAlter(f"task.answer {answer!r} is not the name of a series in the spec")
    target = names.index(answer)

    at_year = [values[j] for _, values in series]
    new_value = 0 if min(at_year) > 0 else max(at_year) + LIFT
    altered = copy.deepcopy(spec)
    entries = altered["series"]
    entries[target]["values"][j] = new_value
    entries[target]["labels"][j] = format_value(new_value, _label_format(entries))

    now = [(entry["name"], entry["values"][j]) for entry in entries]
    top = max(value for _, value in now)
    tops = [name for name, value in now if value == top]
    if len(tops) != 1:
        raise _CannotAlter(
            f"after the change {len(tops)} series tie for the highest value in {year}"
        )
    if tops[0] == answer:
        raise _CannotAlter(
            f"the answer {answer!r} is still the highest in {year} after the change, "
            "so the altered data cannot change it"
        )
    return _Alteration(altered, tops[0], top)


def _label_format(entries: list[dict[str, Any]]) -> str:
    """``"{:.1f}M"`` when every printed label ends with "M", else ``"{:,}"``."""
    labels = [label for entry in entries for label in entry["labels"]]
    return MILLIONS_FORMAT if all(label.endswith("M") for label in labels) else PLAIN_FORMAT


def _redraw_and_read(altered: _Alteration, task: dict[str, Any]) -> dict[str, Any]:
    """Draw the altered spec into a temporary package and return check 5's result for it."""
    question = task.get("question") if altered.spec.get("question_in_image") is True else None
    with tempfile.TemporaryDirectory() as temp_dir:
        pkg = Path(temp_dir)
        try:
            boxes = render_line(altered.spec, pkg / IMAGE_NAME, question=question)
        except Exception as exc:  # render_line raises ValueError for a layout it cannot fit.
            raise _CannotAlter(
                f"the altered spec cannot be drawn: {type(exc).__name__}: {exc}"
            ) from exc
        new_task = dict(task)
        new_task.update(
            answer=altered.answer,
            answer_category=altered.answer,
            answer_value=altered.value,
        )
        _write_json(pkg / TEXT_BOXES_NAME, boxes)
        _write_json(pkg / TASK_NAME, new_task)
        _write_json(pkg / SPEC_NAME, altered.spec)
        return check_5_line_pixels(pkg)


def _counterfactual_details() -> dict[str, Any]:
    """The check 6 details, with nothing measured yet."""
    return {
        "year": None,
        "original_answer": None,
        "altered_answer": None,
        "altered_value": None,
        "changed": False,
        "reader_passed": False,
        "pixel_answer_after_redraw": None,
        "reasons": [],
    }


# --- shared helpers --------------------------------------------------------------


def _spec_series(spec: Any) -> tuple[list[str], list[tuple[str, list[int]]]]:
    """The year labels and the (name, values) of each series, or _Malformed with the reason."""
    if not isinstance(spec, dict):
        raise _Malformed("spec.json must hold a JSON object")
    x_labels = spec.get("x_labels")
    if (
        not isinstance(x_labels, list)
        or not x_labels
        or not all(isinstance(label, str) for label in x_labels)
    ):
        raise _Malformed("spec.x_labels must be a non-empty list of year strings")
    raw_series = spec.get("series")
    if not isinstance(raw_series, list) or not 2 <= len(raw_series) <= 3:
        raise _Malformed("spec.series must hold 2 or 3 series")
    series: list[tuple[str, list[int]]] = []
    for position, entry in enumerate(raw_series):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise _Malformed(f"spec.series[{position}] needs a string name")
        name = entry["name"]
        values = entry.get("values")
        if not isinstance(values, list) or len(values) != len(x_labels):
            raise _Malformed(f"series {name!r} needs one value per year")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise _Malformed(f"series {name!r} has a value that is not an integer")
        series.append((name, list(values)))
    return list(x_labels), series


def _flag(details: dict[str, Any], rule: str, reason: str) -> None:
    """Record one failed rule with its reason."""
    details["failed_rules"].append(rule)
    details["reasons"].append(reason)


def _require(pkg: Path, *names: str) -> None:
    """Raise FileNotFoundError for the first named package file that is missing."""
    for name in names:
        if not (pkg / name).is_file():
            raise FileNotFoundError(f"required package file is missing: {pkg / name}")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.array(img.convert("RGB"), dtype=np.uint8)


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _result(name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "details": details}
