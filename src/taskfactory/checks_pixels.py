"""Check 5: recompute a bar chart's answer from its pixels alone.

The reader works from three files in the package folder: ``image.png`` (the
picture), ``text_boxes.json`` (where each category and value label sits and what
it says) and ``task.json`` (the question type, the category a value lookup asks
about, and the expected answer). It never opens ``spec.json`` or any other
generator output, and it never uses the task to choose bars.

Steps, as in PLAN.md section 4.6 (check 5):

1. A bar is a solid rectangle of bar colour (#4C72B0, within 12 per channel),
   found with ``cv2.findContours`` (external contours only), at least 400 px in
   area and 6 px on each side.
2. Orientation is horizontal when the bars are wider than tall on average, else
   vertical. The category labels must confirm it: below the bars when vertical,
   to the left of them when horizontal.
3. Each bar takes the category label whose centre is nearest along the category
   axis, and the value label nearest its far end (top for vertical, right for
   horizontal) that lies beyond that end.
4. A bar's pixel length is its height (vertical) or width (horizontal).
5. An extremum answer is the category of the longest bar. A value lookup answer
   is the value label of the bar for ``task["answer_category"]``. A rank_k answer
   is the category of the bar at the rank that ``task["question"]`` names
   ("Which category ranks second by value?"), with the bars ordered longest first.
   A pair_compare answer is the longer of the two categories that
   ``task["question"]`` names ("Which is higher, A or B?"), each read from its own
   bar. The rank and the names come from the question text and the category
   labels on the chart, never from the spec.
6. The answer must equal ``task["answer"]``. Extremum, rank_k and pair_compare
   answers are compared as category names; a value lookup answer is compared with
   all whitespace removed.
7. The bar count must equal the category label count, and no label may pair
   with two bars.

A tie that leaves no single answer, such as two bars of equal length at the
asked rank, gives no pixel answer and a reason.

Any miss makes ``passed`` False and adds a reason to ``details["reasons"]``.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

import cv2
import numpy as np
from PIL import Image

from taskfactory.checks_layout import pair_names_from_question, rank_from_question

__all__ = ["check_5_pixels"]

CHECK_NAME = "5_pixels"
IMAGE_NAME = "image.png"
TEXT_BOXES_NAME = "text_boxes.json"
TASK_NAME = "task.json"

BAR_RGB = (76, 114, 176)  # #4C72B0, the renderer's BAR_COLOR
COLOR_TOLERANCE = 12  # per channel
MIN_AREA_PX = 400
MIN_SIDE_PX = 6
MIN_FILL_RATIO = 0.98  # share of a bar's bounding box that must be bar colour

CATEGORY_ROLE = "category"
VALUE_ROLE = "value"
EXTREMUM = "extremum"
VALUE_LOOKUP = "value_lookup"
RANK_K = "rank_k"
PAIR_COMPARE = "pair_compare"


class _Rect(NamedTuple):
    """Pixel edges with the origin top-left: x1 and y1 are exclusive."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def xywh(self) -> list[int]:
        return [self.x0, self.y0, self.x1 - self.x0, self.y1 - self.y0]


class _Label(NamedTuple):
    text: str
    rect: _Rect


class _Pair(NamedTuple):
    """One bar with the indices of its category and value labels (None when unpaired)."""

    rect: _Rect
    category: int | None
    value: int | None


def check_5_pixels(pkg_dir: Path) -> dict[str, Any]:
    """Recompute the answer of one bar package from its pixels and compare it with task.json.

    Raises FileNotFoundError when image.png, text_boxes.json or task.json is
    missing. Unreadable files and every failed rule return ``passed`` False.
    """
    pkg = Path(pkg_dir)
    for name in (IMAGE_NAME, TEXT_BOXES_NAME, TASK_NAME):
        if not (pkg / name).is_file():
            raise FileNotFoundError(f"{name} not found in {pkg}")

    try:
        image = _read_rgb(pkg / IMAGE_NAME)
        task = _read_json(pkg / TASK_NAME)
        if not isinstance(task, dict):
            raise ValueError("task.json must hold a JSON object")
        text_boxes = _read_json(pkg / TEXT_BOXES_NAME)
        categories = _labels(text_boxes, CATEGORY_ROLE)
        values = _labels(text_boxes, VALUE_ROLE)
    except (OSError, ValueError) as exc:
        return _result(False, {"reasons": [f"could not read the package: {exc}"]})

    reasons: list[str] = []
    rects, rejected = _find_bars(image)
    if not rects:
        reasons.append("no bar-coloured rectangles were found")

    orientation = _orientation(rects) if rects else None
    confirmed = orientation is not None and _labels_confirm(orientation, rects, categories)
    if orientation is not None and not confirmed:
        where = "below the bars" if orientation == "vertical" else "left of the bars"
        reasons.append(f"category labels do not sit {where}")
    if len(rects) != len(categories):
        reasons.append(f"bar count {len(rects)} does not match category count {len(categories)}")

    pairs: list[_Pair] = []
    if orientation is not None:
        # Bars run in category order: left to right, or top to bottom.
        rects.sort(key=(lambda r: r.x0) if orientation == "vertical" else (lambda r: r.y0))
        pairs = [
            _Pair(
                rect=rect,
                category=_nearest_category(rect, categories, orientation),
                value=_value_beyond(rect, values, orientation),
            )
            for rect in rects
        ]
    _check_pairing(pairs, categories, values, reasons)
    lengths = [_length(p.rect, orientation) for p in pairs]

    task_type = task.get("task_type")
    expected = _text_or_none(task.get("answer"))
    pixel_answer: str | None = None
    if task_type == EXTREMUM:
        pixel_answer = _extremum_answer(pairs, lengths, categories, reasons)
    elif task_type == VALUE_LOOKUP:
        pixel_answer = _value_lookup_answer(
            pairs, categories, values, _text_or_none(task.get("answer_category")), reasons
        )
    elif task_type == RANK_K:
        pixel_answer = _rank_k_answer(pairs, lengths, categories, task.get("question"), reasons)
    elif task_type == PAIR_COMPARE:
        pixel_answer = _pair_compare_answer(
            pairs, lengths, categories, task.get("question"), reasons
        )
    else:
        reasons.append(f"unsupported task_type {task_type!r}")

    match = _answers_match(task_type, pixel_answer, expected)
    if not match:
        reasons.append(f"pixel answer {pixel_answer!r} does not match expected {expected!r}")

    bars = [
        {
            "category_label": categories[p.category].text if p.category is not None else None,
            "value_label": values[p.value].text if p.value is not None else None,
            "length_px": length,
            "rect": p.rect.xywh(),
        }
        for p, length in zip(pairs, lengths)
    ]
    details = {
        "task_type": task_type,
        "orientation": orientation,
        "orientation_confirmed": confirmed,
        "bar_count": len(rects),
        "category_count": len(categories),
        "rejected_regions": rejected,
        "bars": bars,
        "pixel_answer": pixel_answer,
        "expected_answer": expected,
        "match": match,
        "reasons": reasons,
    }
    return _result(match and not reasons, details)


def _result(passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"check": CHECK_NAME, "passed": bool(passed), "details": details}


def _read_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.array(img.convert("RGB"), dtype=np.uint8)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _labels(text_boxes: Any, role: str) -> list[_Label]:
    """The text boxes of one role, as labels with their pixel rectangles."""
    if not isinstance(text_boxes, list):
        raise ValueError("text_boxes.json must hold a list")
    labels: list[_Label] = []
    for box in text_boxes:
        if not isinstance(box, dict) or box.get("role") != role:
            continue
        bbox = box.get("bbox")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(v, (int, float)) for v in bbox)
        ):
            raise ValueError(f"{role} box needs a four-number bbox, got {bbox!r}")
        x0, y0, x1, y1 = (int(v) for v in bbox)
        labels.append(_Label(str(box.get("text", "")), _Rect(x0, y0, x1, y1)))
    return labels


def _find_bars(image: np.ndarray) -> tuple[list[_Rect], int]:
    """Solid bar-coloured rectangles, and how many bar-coloured regions were rejected."""
    target = np.array(BAR_RGB, dtype=np.int16)
    near = np.all(np.abs(image.astype(np.int16) - target) <= COLOR_TOLERANCE, axis=2)
    mask = np.where(near, 255, 0).astype(np.uint8)
    # OpenCV 3 returns three values from findContours and OpenCV 4 and later two.
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    rects: list[_Rect] = []
    rejected = 0
    for contour in contours:
        x, y, w, h = (int(v) for v in cv2.boundingRect(contour))
        if w * h < MIN_AREA_PX or w < MIN_SIDE_PX or h < MIN_SIDE_PX:
            rejected += 1
            continue
        # A bar is a rectangle. A region with a hole or a notch is a covered bar,
        # so it is rejected and the bar count then differs from the category count.
        fill = np.count_nonzero(near[y : y + h, x : x + w]) / (w * h)
        if fill < MIN_FILL_RATIO:
            rejected += 1
            continue
        rects.append(_Rect(x, y, x + w, y + h))
    return rects, rejected


def _orientation(rects: list[_Rect]) -> str:
    mean_w = sum(r.x1 - r.x0 for r in rects) / len(rects)
    mean_h = sum(r.y1 - r.y0 for r in rects) / len(rects)
    return "horizontal" if mean_w > mean_h else "vertical"


def _labels_confirm(orientation: str, rects: list[_Rect], categories: list[_Label]) -> bool:
    """True when every category label sits on the side the orientation predicts."""
    if not rects or not categories:
        return False
    if orientation == "vertical":
        baseline = max(r.y1 for r in rects)  # lowest bar edge
        return all(label.rect.cy > baseline for label in categories)
    left_edge = min(r.x0 for r in rects)  # leftmost bar edge
    return all(label.rect.cx < left_edge for label in categories)


def _nearest_category(rect: _Rect, categories: list[_Label], orientation: str) -> int | None:
    """Index of the category label whose centre is nearest the bar's centre on the category axis."""
    if orientation == "vertical":
        gaps = [abs(label.rect.cx - rect.cx) for label in categories]
    else:
        gaps = [abs(label.rect.cy - rect.cy) for label in categories]
    return min(range(len(gaps)), key=gaps.__getitem__, default=None)


def _value_beyond(rect: _Rect, values: list[_Label], orientation: str) -> int | None:
    """Index of the value label nearest the bar's far end, on the far side of that end."""
    if orientation == "vertical":
        far_x, far_y = rect.cx, rect.y0  # top end
        ahead = [i for i, label in enumerate(values) if label.rect.cy < far_y]
    else:
        far_x, far_y = rect.x1, rect.cy  # right end
        ahead = [i for i, label in enumerate(values) if label.rect.cx > far_x]
    return min(
        ahead,
        key=lambda i: math.hypot(values[i].rect.cx - far_x, values[i].rect.cy - far_y),
        default=None,
    )


def _length(rect: _Rect, orientation: str | None) -> int:
    """Pixel length along the value axis: height for vertical bars, width for horizontal."""
    return rect.y1 - rect.y0 if orientation == "vertical" else rect.x1 - rect.x0


def _check_pairing(
    pairs: list[_Pair], categories: list[_Label], values: list[_Label], reasons: list[str]
) -> None:
    """Every bar needs one category and one value label, and no label may serve two bars."""
    for kind, labels, picked in (
        ("category", categories, [p.category for p in pairs]),
        ("value", values, [p.value for p in pairs]),
    ):
        for position, index in enumerate(picked, start=1):
            if index is None:
                reasons.append(f"bar {position} has no {kind} label")
        for index, count in Counter(i for i in picked if i is not None).items():
            if count > 1:
                reasons.append(f"{kind} label {labels[index].text!r} is paired with {count} bars")


def _extremum_answer(
    pairs: list[_Pair], lengths: list[int], categories: list[_Label], reasons: list[str]
) -> str | None:
    if not pairs:
        return None
    longest = max(lengths)
    winners = [i for i, length in enumerate(lengths) if length == longest]
    if len(winners) > 1:
        reasons.append(f"{len(winners)} bars tie for the longest at {longest} px")
        return None
    index = pairs[winners[0]].category
    return categories[index].text if index is not None else None


def _value_lookup_answer(
    pairs: list[_Pair],
    categories: list[_Label],
    values: list[_Label],
    target: str | None,
    reasons: list[str],
) -> str | None:
    matches = [
        p for p in pairs if p.category is not None and categories[p.category].text == target
    ]
    if not matches:
        reasons.append(f"no bar is labelled with the question's category {target!r}")
        return None
    value = matches[0].value
    return values[value].text if value is not None else None


def _rank_k_answer(
    pairs: list[_Pair],
    lengths: list[int],
    categories: list[_Label],
    question: Any,
    reasons: list[str],
) -> str | None:
    """The category of the bar at the rank the question names, longest bar first."""
    if not pairs:
        return None
    rank = rank_from_question(question)
    if rank is None:
        reasons.append("the question does not ask for a rank such as 'second'")
        return None
    if rank > len(pairs):
        reasons.append(f"the question asks for rank {rank}, but only {len(pairs)} bars were found")
        return None
    order = sorted(range(len(pairs)), key=lambda position: lengths[position], reverse=True)
    length = lengths[order[rank - 1]]
    ties = sum(1 for other in lengths if other == length)
    if ties > 1:
        reasons.append(f"{ties} bars tie at {length} px, so no bar is at rank {rank}")
        return None
    index = pairs[order[rank - 1]].category
    return categories[index].text if index is not None else None


def _pair_compare_answer(
    pairs: list[_Pair],
    lengths: list[int],
    categories: list[_Label],
    question: Any,
    reasons: list[str],
) -> str | None:
    """The longer of the two named categories' bars, reported by its category label."""
    if not pairs:
        return None
    names = [label.text for label in categories]
    asked = pair_names_from_question(question, names)
    if len(asked) != 1:
        reasons.append("the question does not name two categories of the chart")
        return None
    first, second = asked[0]
    bars: dict[str, list[int]] = {first: [], second: []}
    for position, pair in enumerate(pairs):
        if pair.category is not None and categories[pair.category].text in bars:
            bars[categories[pair.category].text].append(position)
    for name in (first, second):
        if len(bars[name]) != 1:
            reasons.append(f"{len(bars[name])} bars are labelled {name!r}, not one")
            return None
    first_length = lengths[bars[first][0]]
    second_length = lengths[bars[second][0]]
    if first_length == second_length:
        reasons.append(f"the bars for {first!r} and {second!r} tie at {first_length} px")
        return None
    return first if first_length > second_length else second


def _answers_match(task_type: Any, pixel_answer: str | None, expected: str | None) -> bool:
    """Category answers compare names exactly; value lookup ignores all whitespace."""
    if pixel_answer is None or expected is None:
        return False
    if task_type in (EXTREMUM, RANK_K, PAIR_COMPARE):
        return pixel_answer == expected
    if task_type == VALUE_LOOKUP:
        return _squash(pixel_answer) == _squash(expected)
    return False


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)
