"""Package checks for schema, text layout, ambiguity and render reproducibility.

Each check reads one package folder written by
:func:`taskfactory.package.write_task_package` and returns a result dict::

    {"check": "<name>", "passed": bool, "details": {...}}

``details`` is always JSON-serialisable.  Bad content never raises: a broken
spec, task or text-box file is reported as ``passed`` False.  The only
exception is a required file that is missing entirely, which raises
:class:`FileNotFoundError`.

Line packages use checks 1 and 2 too. Check 1 also accepts a ``series_at_x``
task of a ``line`` spec: its ``answer`` must be a series name of the spec, its
``answer_category`` the same name, and its ``answer_value`` the value of that
series at ``year``. Check 2 accepts ``legend`` boxes; they must not overlap value,
category or title boxes, or each other.

Bar packages of the ``rank_k`` and ``pair_compare`` types are checked by check 1
against their spec. A rank_k answer is the category at the rank the question
names, with the spec values sorted largest first. A pair_compare answer is the
larger of the two categories the question names, and both must be categories of
the spec. Neither task carries a rank or a name field, so both are read from the
question text.

Check 1 also reads the category or year that a value_lookup, pair_compare or
series_at_x question names. The spec must have that entity (``question_entity_not_in_chart``)
and, for value_lookup and series_at_x, the answer must be about it
(``question_entity_mismatch``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any

from taskfactory.render import render_bar
from taskfactory.sampler import validate_spec

__all__ = [
    "check_1_schema",
    "check_2_layout",
    "check_3_ambiguity",
    "check_7_redraw",
    "pair_names_from_question",
    "rank_from_question",
    "run_layout_checks",
]

_SPEC_NAME = "spec.json"
_TASK_NAME = "task.json"
_TEXT_BOXES_NAME = "text_boxes.json"
_IMAGE_NAME = "image.png"

_TASK_TYPES = ("value_lookup", "extremum", "series_at_x", "rank_k", "pair_compare")
_LINE_FAMILY = "line"
_BAR_FAMILY = "bar"
_RANK_K = "rank_k"
_PAIR_COMPARE = "pair_compare"

# The ordinal words questions.py writes in a rank_k question, each with the rank it
# asks for: "second" is rank 2, the lowest rank a rank_k question can ask.
_RANK_WORDS: dict[str, int] = {
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
}
_RANK_QUESTION = re.compile(r"Which category ranks (\w+) by value\?")

# The start of each question questions.py writes that names a category or a year. The
# name follows the start, and a closing "?" ends the question.
_VALUE_LOOKUP_PREFIX = "What value is shown for "
_SERIES_AT_X_PREFIX = "Which series is highest in "
_PAIR_COMPARE_PREFIX = "Which is higher, "
_PAIR_JOIN = " or "

# Every task.json field and the type it must hold.  ``int`` means a non-boolean
# integer, since bool is a subclass of int in Python.
_TASK_FIELDS: tuple[tuple[str, type], ...] = (
    ("task_type", str),
    ("family", str),
    ("domain", str),
    ("spec_index", int),
    ("question", str),
    ("answer", str),
    ("answer_value", int),
    ("answer_category", str),
    ("reasoning_steps", int),
    ("answer_printed_in_image", bool),
    ("question_in_image", bool),
)

# Fields a series_at_x task carries on top of _TASK_FIELDS.
_SERIES_AT_X_FIELDS: tuple[tuple[str, type], ...] = (("year", str),)


class _BadPackage(Exception):
    """A package file exists but cannot be read or parsed."""


def check_1_schema(pkg_dir: Path) -> dict[str, Any]:
    """Check ``spec.json`` against the sampler and ``task.json`` against its shape.

    The task must carry every required field with the right type.  An
    ``extremum`` answer must equal its category and the largest spec value; a
    ``value_lookup`` answer must equal the printed label for its category. A
    ``rank_k`` answer must be the category at the rank the question names, and a
    ``pair_compare`` answer must be the larger of the two categories it names.

    Every category or year that a value_lookup, pair_compare or series_at_x question
    names must be in the spec (``question_entity_not_in_chart``). The category a
    value_lookup asks about must be the answer's category, and the year a series_at_x
    asks about must be the task's year (``question_entity_mismatch``).
    """
    pkg_dir = Path(pkg_dir)
    try:
        spec = _read_json(pkg_dir / _SPEC_NAME)
        task = _read_json(pkg_dir / _TASK_NAME)
    except _BadPackage as exc:
        return _result("1_schema", False, _read_failure(exc))

    failures: list[dict[str, str]] = []
    spec_valid = True
    spec_error: str | None = None
    try:
        validate_spec(spec)
    except Exception as exc:  # validate_spec raises ValueError; be defensive anyway.
        spec_valid = False
        spec_error = f"{type(exc).__name__}: {exc}"
        failures.append(
            _failure("spec_valid", f"spec.json failed validate_spec: {spec_error}")
        )

    task_is_object = isinstance(task, dict)
    if not task_is_object:
        failures.append(_failure("task_object", "task.json must contain a JSON object"))
        task = {}

    task_type = task.get("task_type")
    for key, expected in _required_fields(task_type):
        if key not in task:
            failures.append(_failure(f"task_key_{key}", f"task.json is missing {key!r}"))
        elif not _matches_type(task[key], expected):
            failures.append(
                _failure(
                    f"task_type_{key}",
                    f"task.{key}: expected {_type_name(expected)}, "
                    f"got {type(task[key]).__name__}",
                )
            )

    if isinstance(task_type, str) and task_type not in _TASK_TYPES:
        failures.append(
            _failure(
                "task_type_supported",
                f"task.task_type: expected one of {list(_TASK_TYPES)}, "
                f"got {task_type!r}",
            )
        )

    if task_type == "extremum":
        _check_extremum_task(task, spec, spec_valid, failures)
    elif task_type == "value_lookup":
        _check_lookup_task(task, spec, spec_valid, failures)
    elif task_type == "series_at_x":
        _check_series_at_x_task(task, spec, spec_valid, failures)
    elif task_type == _RANK_K:
        _check_rank_k_task(task, spec, spec_valid, failures)
    elif task_type == _PAIR_COMPARE:
        _check_pair_compare_task(task, spec, spec_valid, failures)
    _check_question_entities(task, spec, spec_valid, failures)

    details = {
        "spec_valid": spec_valid,
        "spec_error": spec_error,
        "task_is_object": task_is_object,
        "task_type": task_type if isinstance(task_type, str) else None,
        "failed_rules": [item["rule"] for item in failures],
        "failures": failures,
    }
    return _result("1_schema", not failures, details)


def check_2_layout(
    pkg_dir: Path, canvas: tuple[int, int] = (1200, 800), min_font_px: int = 9
) -> dict[str, Any]:
    """Check text boxes stay on the canvas, stay legible and do not collide.

    Value boxes must not overlap other value boxes, category boxes or the
    title, and category boxes must not overlap each other. Legend boxes, which
    only line charts draw, must not overlap value, category or title boxes, or
    each other.
    """
    pkg_dir = Path(pkg_dir)
    canvas_w, canvas_h = float(canvas[0]), float(canvas[1])
    try:
        raw_boxes = _read_json(pkg_dir / _TEXT_BOXES_NAME)
    except _BadPackage as exc:
        details = _empty_layout_details(canvas_w, canvas_h, min_font_px)
        details["error"] = str(exc)
        return _result("2_layout", False, details)

    details = _empty_layout_details(canvas_w, canvas_h, min_font_px)
    if not isinstance(raw_boxes, list):
        details["malformed_boxes"].append(
            {"index": None, "message": "text_boxes.json must contain a JSON list"}
        )
        return _result("2_layout", False, details)

    details["box_count"] = len(raw_boxes)
    boxes: list[dict[str, Any]] = []
    for index, raw_box in enumerate(raw_boxes):
        box, problem = _parse_box(raw_box, index)
        if problem is not None:
            details["malformed_boxes"].append({"index": index, "message": problem})
            continue

        x0, y0, x1, y1 = (float(value) for value in box["bbox"])
        if x0 < 0 or y0 < 0 or x1 > canvas_w or y1 > canvas_h:
            details["outside_canvas"].append(_box_summary(box))
        if float(box["font_px"]) < min_font_px:
            details["small_font_boxes"].append(_box_summary(box))
        boxes.append(box)

    values = [box for box in boxes if box["role"] == "value"]
    categories = [box for box in boxes if box["role"] == "category"]
    titles = [box for box in boxes if box["role"] == "title"]

    for first, second in combinations(values, 2):
        if _overlaps(first, second):
            details["overlapping_pairs"].append(_overlap_pair(first, second, "value-value"))
    for first, second in combinations(categories, 2):
        if _overlaps(first, second):
            details["overlapping_pairs"].append(
                _overlap_pair(first, second, "category-category")
            )
    for value in values:
        for category in categories:
            if _overlaps(value, category):
                details["overlapping_pairs"].append(
                    _overlap_pair(value, category, "value-category")
                )
        for title in titles:
            if _overlaps(value, title):
                details["overlapping_pairs"].append(
                    _overlap_pair(value, title, "value-title")
                )

    legends = [box for box in boxes if box["role"] == "legend"]
    for first, second in combinations(legends, 2):
        if _overlaps(first, second):
            details["overlapping_pairs"].append(_overlap_pair(first, second, "legend-legend"))
    for legend in legends:
        for other, kind in (
            (values, "legend-value"),
            (categories, "legend-category"),
            (titles, "legend-title"),
        ):
            for box in other:
                if _overlaps(legend, box):
                    details["overlapping_pairs"].append(_overlap_pair(legend, box, kind))

    passed = not (
        details["outside_canvas"]
        or details["small_font_boxes"]
        or details["overlapping_pairs"]
        or details["malformed_boxes"]
    )
    return _result("2_layout", passed, details)


def check_3_ambiguity(pkg_dir: Path, min_margin: float = 0.05) -> dict[str, Any]:
    """Check that the top two values and the printed labels are distinct enough.

    The relative margin is ``(max - second) / max``; it must be at least
    ``min_margin``.  Duplicate values and duplicate labels both fail.
    """
    pkg_dir = Path(pkg_dir)
    details: dict[str, Any] = {
        "margin": None,
        "min_margin": min_margin,
        "values": [],
        "labels": [],
        "largest": None,
        "second_largest": None,
        "duplicate_values": [],
        "duplicate_labels": [],
        "failed_rules": [],
    }
    try:
        spec = _read_json(pkg_dir / _SPEC_NAME)
    except _BadPackage as exc:
        details["error"] = str(exc)
        details["failed_rules"].append("readable_spec")
        return _result("3_ambiguity", False, details)

    try:
        values = list(spec["series"][0]["values"])
        labels = list(spec["series"][0]["labels"])
    except (KeyError, IndexError, TypeError):
        details["error"] = "spec.json has no readable series[0] values and labels"
        details["failed_rules"].append("structure")
        return _result("3_ambiguity", False, details)

    details["values"] = values
    details["labels"] = labels
    if not values or not all(_is_number(value) for value in values):
        details["error"] = "spec values must be a non-empty list of finite numbers"
        details["failed_rules"].append("values_numeric")
        return _result("3_ambiguity", False, details)
    if len(values) != len(labels) or not all(isinstance(label, str) for label in labels):
        details["error"] = "spec labels must be strings matching the values one for one"
        details["failed_rules"].append("labels_valid")
        return _result("3_ambiguity", False, details)
    if len(values) < 2:
        details["error"] = "the check needs at least two values"
        details["failed_rules"].append("enough_values")
        return _result("3_ambiguity", False, details)

    duplicate_values = _duplicates(values)
    duplicate_labels = _duplicates(labels)
    details["duplicate_values"] = duplicate_values
    details["duplicate_labels"] = duplicate_labels
    if duplicate_values:
        details["failed_rules"].append("duplicate_values")
    if duplicate_labels:
        details["failed_rules"].append("duplicate_labels")

    ordered = sorted(values, reverse=True)
    largest, second_largest = ordered[0], ordered[1]
    details["largest"] = largest
    details["second_largest"] = second_largest

    margin: float | None
    if largest == 0:
        margin = None
        details["error"] = "the largest value is zero, so the margin is undefined"
        details["failed_rules"].append("margin_undefined")
    else:
        try:
            margin = (float(largest) - float(second_largest)) / float(largest)
        except (OverflowError, ZeroDivisionError):
            margin = None
            details["error"] = "the largest value cannot be scaled to a finite number"
            details["failed_rules"].append("margin_undefined")
        else:
            details["margin"] = margin
            if margin < min_margin:
                details["failed_rules"].append("small_margin")

    return _result("3_ambiguity", not details["failed_rules"], details)


def check_7_redraw(pkg_dir: Path) -> dict[str, Any]:
    """Re-render the spec and compare its bytes with the package image.

    The rendered question is the task question when the spec prints it.  A
    package that prints the question must also carry a matching ``caption``
    text box.
    """
    pkg_dir = Path(pkg_dir)
    try:
        spec = _read_json(pkg_dir / _SPEC_NAME)
        task = _read_json(pkg_dir / _TASK_NAME)
        raw_boxes = _read_json(pkg_dir / _TEXT_BOXES_NAME)
        image_bytes = _read_bytes(pkg_dir / _IMAGE_NAME)
    except _BadPackage as exc:
        details = _empty_redraw_details()
        details["error"] = str(exc)
        details["failed_rules"].append("readable_files")
        return _result("7_redraw", False, details)

    details = _empty_redraw_details()
    details["image_sha256"] = hashlib.sha256(image_bytes).hexdigest()
    failures: list[str] = details["failed_rules"]

    spec_is_object = isinstance(spec, dict)
    if not spec_is_object:
        failures.append("spec_not_an_object")
    question_in_image = bool(spec_is_object and spec.get("question_in_image") is True)
    details["question_in_image"] = question_in_image

    task_is_object = isinstance(task, dict)
    if not task_is_object:
        failures.append("task_not_an_object")
    question = task.get("question") if task_is_object else None

    caption_texts: list[str] = []
    if isinstance(raw_boxes, list):
        for box in raw_boxes:
            if isinstance(box, dict) and box.get("role") == "caption":
                text = box.get("text")
                if isinstance(text, str):
                    caption_texts.append(text)
    else:
        failures.append("text_boxes_not_a_list")
    details["caption_texts"] = caption_texts
    details["caption_present"] = bool(caption_texts)

    caption_required = question_in_image
    details["caption_required"] = caption_required
    caption_matches = True
    if caption_required:
        if not isinstance(question, str):
            caption_matches = False
            failures.append("question_not_a_string")
        else:
            caption_matches = question in caption_texts
            if not caption_matches:
                failures.append("caption_missing")
    details["caption_matches"] = caption_matches

    if spec_is_object:
        render_question = (
            question if question_in_image and isinstance(question, str) else None
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_png = Path(temp_dir) / _IMAGE_NAME
                render_bar(spec, temp_png, question=render_question)
                details["redraw_sha256"] = hashlib.sha256(
                    temp_png.read_bytes()
                ).hexdigest()
        except Exception as exc:  # render_bar may raise ValueError or OSError.
            details["render_error"] = f"{type(exc).__name__}: {exc}"
            failures.append("render_failed")

    hashes_match = (
        details["redraw_sha256"] is not None
        and details["redraw_sha256"] == details["image_sha256"]
    )
    details["hashes_match"] = hashes_match
    if not hashes_match:
        failures.append("hash_mismatch")

    return _result("7_redraw", not failures, details)


def run_layout_checks(
    pkg_dir: Path,
    min_margin: float = 0.05,
    min_font_px: int = 9,
    *,
    include_redraw: bool = True,
) -> list[dict[str, Any]]:
    """Run checks 1, 2, 3 and 7 in order and return their result dicts.

    With ``include_redraw`` False, check 7 is left out and checks 1, 2 and 3 alone run:
    the content checks, without the redraw.
    """
    results = [
        check_1_schema(pkg_dir),
        check_2_layout(pkg_dir, min_font_px=min_font_px),
        check_3_ambiguity(pkg_dir, min_margin=min_margin),
    ]
    if include_redraw:
        results.append(check_7_redraw(pkg_dir))
    return results


def rank_from_question(question: Any) -> int | None:
    """The rank a ``rank_k`` question asks for: 2 for "Which category ranks second by value?".

    Returns None when ``question`` is not a string or does not use one of the
    ordinals questions.py writes, which run from "second" to "eighth".
    """
    if not isinstance(question, str):
        return None
    match = _RANK_QUESTION.fullmatch(question)
    if match is None:
        return None
    return _RANK_WORDS.get(match.group(1))


def pair_names_from_question(question: Any, names: list[str]) -> list[tuple[str, str]]:
    """The ordered pairs of distinct ``names`` that a ``pair_compare`` question asks about.

    The question reads "Which is higher, A or B?". A name may itself contain " or "
    or a comma, so each ordered pair of ``names`` is tried against the exact
    wording instead of splitting the text. questions.py writes one pair for each
    question; any other count means the question does not name two categories
    cleanly.
    """
    if not isinstance(question, str):
        return []
    return [
        (first, second)
        for first in names
        for second in names
        if first != second and question == f"Which is higher, {first} or {second}?"
    ]


def _check_rank_k_task(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check a rank_k answer and value against the category at the asked rank."""
    _check_family_and_answer(task, _RANK_K, failures)
    if not spec_valid:
        return
    if not _is_bar_spec(spec):
        failures.append(
            _failure("rank_k_spec_family", f"a rank_k task needs a {_BAR_FAMILY!r} spec")
        )
        return

    rank = rank_from_question(task.get("question"))
    if rank is None:
        failures.append(
            _failure(
                "rank_k_question",
                "task.question must ask for a rank such as 'second', as in "
                "'Which category ranks second by value?'",
            )
        )
        return
    ranking = _bar_ranking(spec)
    if rank > len(ranking):
        failures.append(
            _failure(
                "rank_k_rank",
                f"task.question asks for rank {rank}, but the spec has {len(ranking)} categories",
            )
        )
        return

    expected_category, expected_value = ranking[rank - 1]
    answer = task.get("answer")
    if answer != expected_category:
        failures.append(
            _failure(
                "rank_k_answer",
                f"task.answer {answer!r} is not the category at rank {rank} by value, "
                f"which is {expected_category!r}",
            )
        )
    answer_value = task.get("answer_value")
    if not (_matches_type(answer_value, int) and answer_value == expected_value):
        failures.append(
            _failure(
                "rank_k_answer_value",
                f"task.answer_value {answer_value!r} is not the value at rank {rank}, "
                f"which is {expected_value!r}",
            )
        )


def _check_pair_compare_task(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check a pair_compare answer: the larger of the two categories the question names."""
    _check_family_and_answer(task, _PAIR_COMPARE, failures)
    if not spec_valid:
        return
    if not _is_bar_spec(spec):
        failures.append(
            _failure(
                "pair_compare_spec_family",
                f"a pair_compare task needs a {_BAR_FAMILY!r} spec",
            )
        )
        return

    x_labels: list[str] = spec["x_labels"]
    asked = pair_names_from_question(task.get("question"), x_labels)
    if len(asked) != 1:
        failures.append(
            _failure(
                "pair_compare_names",
                "task.question must be 'Which is higher, A or B?' where A and B are each "
                "a category of the spec",
            )
        )
        return
    first, second = asked[0]
    # validate_spec rejects duplicate values, so the two values always differ here.
    values = spec["series"][0]["values"]
    first_value = values[x_labels.index(first)]
    second_value = values[x_labels.index(second)]
    if first_value > second_value:
        larger, larger_value = first, first_value
    else:
        larger, larger_value = second, second_value
    answer = task.get("answer")
    if answer != larger:
        failures.append(
            _failure(
                "pair_compare_answer",
                f"task.answer {answer!r} is not the larger of {first!r} and {second!r}, "
                f"which is {larger!r}",
            )
        )
    answer_value = task.get("answer_value")
    if not (_matches_type(answer_value, int) and answer_value == larger_value):
        failures.append(
            _failure(
                "pair_compare_answer_value",
                f"task.answer_value {answer_value!r} is not the value of {larger!r}, "
                f"which is {larger_value!r}",
            )
        )


def _check_family_and_answer(
    task: dict[str, Any], task_type: str, failures: list[dict[str, str]]
) -> None:
    """The family and answer-equals-category rules that rank_k and pair_compare share."""
    if task.get("family") != _BAR_FAMILY:
        failures.append(
            _failure(
                f"{task_type}_family",
                f"task.family {task.get('family')!r} must be {_BAR_FAMILY!r}",
            )
        )
    answer = task.get("answer")
    answer_category = task.get("answer_category")
    if not (
        isinstance(answer, str)
        and isinstance(answer_category, str)
        and answer == answer_category
    ):
        failures.append(
            _failure(
                f"{task_type}_answer_equals_category",
                f"task.answer {answer!r} must equal task.answer_category {answer_category!r}",
            )
        )


def _is_bar_spec(spec: Any) -> bool:
    """True when ``spec`` is a dict of the bar family."""
    return isinstance(spec, dict) and spec.get("family") == _BAR_FAMILY


def _bar_ranking(spec: dict[str, Any]) -> list[tuple[str, int]]:
    """(category, value) for each bar of a valid bar spec, largest value first.

    Equal values keep their spec order, as questions.py sorts them, so a tie
    picks the same category here as it did when the question was written.
    """
    x_labels: list[str] = spec["x_labels"]
    values: list[int] = spec["series"][0]["values"]
    order = sorted(range(len(values)), key=lambda position: values[position], reverse=True)
    return [(x_labels[position], values[position]) for position in order]


def _check_extremum_task(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check the extremum answer and value against the spec."""
    answer = task.get("answer")
    answer_category = task.get("answer_category")
    if not (
        isinstance(answer, str)
        and isinstance(answer_category, str)
        and answer == answer_category
    ):
        failures.append(
            _failure(
                "extremum_answer_equals_category",
                f"task.answer {answer!r} must equal task.answer_category "
                f"{answer_category!r}",
            )
        )

    if not spec_valid:
        return
    maximum = _max_spec_value(spec)
    answer_value = task.get("answer_value")
    if maximum is None:
        failures.append(
            _failure("extremum_max_value", "could not read the maximum spec value")
        )
    elif not (isinstance(answer_value, int) and not isinstance(answer_value, bool)):
        failures.append(
            _failure(
                "extremum_max_value",
                f"task.answer_value: expected int, got {type(answer_value).__name__}",
            )
        )
    elif answer_value != maximum:
        failures.append(
            _failure(
                "extremum_max_value",
                f"task.answer_value {answer_value!r} is not the maximum spec value "
                f"{maximum!r}",
            )
        )


def _check_lookup_task(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check the value_lookup answer against the label for its category."""
    if not spec_valid:
        return
    answer_category = task.get("answer_category")
    label = _label_for_category(spec, answer_category)
    if label is None:
        failures.append(
            _failure(
                "value_lookup_category",
                f"task.answer_category {answer_category!r} is not a category with a "
                "printed label in spec.json",
            )
        )
        return
    answer = task.get("answer")
    if not (isinstance(answer, str) and answer == label):
        failures.append(
            _failure(
                "value_lookup_answer",
                f"task.answer {answer!r} does not equal the printed label {label!r} "
                f"for category {answer_category!r}",
            )
        )


def _check_series_at_x_task(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check a series_at_x task against its line spec: the series named and its value at the year."""
    if task.get("family") != _LINE_FAMILY:
        failures.append(
            _failure(
                "series_at_x_family",
                f"task.family {task.get('family')!r} must be {_LINE_FAMILY!r}",
            )
        )
    answer = task.get("answer")
    answer_category = task.get("answer_category")
    if not (
        isinstance(answer, str)
        and isinstance(answer_category, str)
        and answer == answer_category
    ):
        failures.append(
            _failure(
                "series_at_x_answer_equals_category",
                f"task.answer {answer!r} must equal task.answer_category "
                f"{answer_category!r}",
            )
        )

    if not spec_valid:
        return
    if not isinstance(spec, dict) or spec.get("family") != _LINE_FAMILY:
        failures.append(
            _failure(
                "series_at_x_spec_family",
                f"a series_at_x task needs a {_LINE_FAMILY!r} spec",
            )
        )
        return

    year = task.get("year")
    at_year = _series_at_year(spec, year)
    if at_year is None:
        failures.append(
            _failure(
                "series_at_x_year",
                f"task.year {year!r} is not one of the spec's years",
            )
        )
        return

    values = [value for name, value in at_year if name == answer]
    if len(values) != 1:
        failures.append(
            _failure(
                "series_at_x_answer_series",
                f"task.answer {answer!r} is not the name of exactly one series in the spec",
            )
        )
        return

    answer_value = task.get("answer_value")
    if not (
        isinstance(answer_value, int)
        and not isinstance(answer_value, bool)
        and answer_value == values[0]
    ):
        failures.append(
            _failure(
                "series_at_x_answer_value",
                f"task.answer_value {answer_value!r} is not the value of {answer!r} "
                f"in {year!r}, which is {values[0]!r}",
            )
        )


def _series_at_year(spec: dict[str, Any], year: Any) -> list[tuple[Any, Any]] | None:
    """Each series' (name, value) at ``year``, or None when ``year`` is not one of the spec's years."""
    try:
        position = spec["x_labels"].index(year)
        return [(entry["name"], entry["values"][position]) for entry in spec["series"]]
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        return None


def _check_question_entities(
    task: dict[str, Any],
    spec: Any,
    spec_valid: bool,
    failures: list[dict[str, str]],
) -> None:
    """Check the category or year a question names against the spec and against the answer.

    A ``value_lookup`` question names its category, which must be a category of the spec
    and the task's ``answer_category``. A ``series_at_x`` question names its year, which
    must be one of the spec's years and the task's ``year``. A ``pair_compare`` question
    names two categories, and each must be a category of the spec. An ``extremum`` or
    ``rank_k`` question names no category, so there is nothing to check here.

    A named entity that the spec lacks fails ``question_entity_not_in_chart``. One that the
    spec has, but that the answer is not about, fails ``question_entity_mismatch``. Nothing
    is checked when the spec is invalid, since its categories cannot then be read.
    """
    if not spec_valid:
        return
    x_labels: list[str] = spec["x_labels"]
    question = task.get("question")
    task_type = task.get("task_type")

    if task_type == "value_lookup":
        named = _text_after(question, _VALUE_LOOKUP_PREFIX)
        if named is None:
            return
        category = task.get("answer_category")
        if named not in x_labels:
            failures.append(
                _failure(
                    "question_entity_not_in_chart",
                    f"task.question names {named!r}, which is not a category of the spec",
                )
            )
        elif named != category:
            failures.append(
                _failure(
                    "question_entity_mismatch",
                    f"task.question names {named!r}, but task.answer_category is {category!r}",
                )
            )
    elif task_type == "series_at_x":
        named = _text_after(question, _SERIES_AT_X_PREFIX)
        if named is None:
            return
        year = task.get("year")
        if named not in x_labels:
            failures.append(
                _failure(
                    "question_entity_not_in_chart",
                    f"task.question names the year {named!r}, which is not one of the spec's years",
                )
            )
        elif named != year:
            failures.append(
                _failure(
                    "question_entity_mismatch",
                    f"task.question names the year {named!r}, but task.year is {year!r}",
                )
            )
    elif task_type == _PAIR_COMPARE:
        candidates = _pair_name_candidates(question)
        if not candidates:
            return  # pair_compare_names already reports a question that names no pair
        # Keep the reading whose names the spec has most of, so a name with " or " in it
        # is not reported as missing.
        first, second = min(
            candidates, key=lambda pair: sum(name not in x_labels for name in pair)
        )
        missing = [name for name in (first, second) if name not in x_labels]
        if missing:
            names = ", ".join(repr(name) for name in missing)
            failures.append(
                _failure(
                    "question_entity_not_in_chart",
                    f"task.question names {names}, which is not a category of the spec",
                )
            )


def _text_after(question: Any, prefix: str) -> str | None:
    """The text between ``prefix`` and the closing "?" of ``question``, or None.

    questions.py writes each question that names a category or a year as the prefix, then
    the name, then "?". A question in any other form has no name that this reads.
    """
    if not isinstance(question, str) or not question.startswith(prefix):
        return None
    if not question.endswith("?"):
        return None
    return question[len(prefix) : -1]


def _pair_name_candidates(question: Any) -> list[tuple[str, str]]:
    """Every way to split the two names of a pair_compare question at a " or ".

    A name may itself contain " or ", so each split is returned and the caller keeps the
    one that the spec's categories fit.
    """
    body = _text_after(question, _PAIR_COMPARE_PREFIX)
    if body is None:
        return []
    return [
        (body[:position], body[position + len(_PAIR_JOIN) :])
        for position in range(len(body))
        if body.startswith(_PAIR_JOIN, position)
    ]


def _max_spec_value(spec: Any) -> int | float | None:
    """Largest value across every series, or None when the spec is unreadable."""
    try:
        values = [value for series in spec["series"] for value in series["values"]]
    except (KeyError, TypeError):
        return None
    if not values:
        return None
    try:
        return max(values)
    except TypeError:
        return None


def _label_for_category(spec: Any, category: Any) -> str | None:
    """Printed label of ``category`` in the first series, or None if absent."""
    if not isinstance(category, str):
        return None
    try:
        position = spec["x_labels"].index(category)
        label = spec["series"][0]["labels"][position]
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        return None
    return label if isinstance(label, str) else None


def _parse_box(
    raw_box: Any, index: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Return a normalised text box, or (None, why it is malformed)."""
    if not isinstance(raw_box, dict):
        return None, "box must be a JSON object"

    role = raw_box.get("role")
    if not isinstance(role, str):
        return None, "'role' must be a string"
    text = raw_box.get("text")
    if not isinstance(text, str):
        return None, "'text' must be a string"

    bbox = raw_box.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None, "'bbox' must be a list of four numbers"
    if not all(_is_number(value) for value in bbox):
        return None, "'bbox' must hold four finite numbers"
    x0, y0, x1, y1 = (float(value) for value in bbox)
    if x0 > x1 or y0 > y1:
        return None, "'bbox' must satisfy x0 <= x1 and y0 <= y1"

    font_px = raw_box.get("font_px")
    if not _is_number(font_px):
        return None, "'font_px' must be a finite number"

    return {
        "index": index,
        "role": role,
        "text": text,
        "bbox": list(bbox),
        "font_px": font_px,
    }, None


def _overlaps(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """True when two boxes share interior area; touching edges do not count."""
    ax0, ay0, ax1, ay1 = (float(value) for value in first["bbox"])
    bx0, by0, bx1, by1 = (float(value) for value in second["bbox"])
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _overlap_pair(
    first: dict[str, Any], second: dict[str, Any], kind: str
) -> dict[str, Any]:
    """JSON-serialisable description of one overlapping pair."""
    return {
        "kind": kind,
        "first": _box_summary(first),
        "second": _box_summary(second),
    }


def _box_summary(box: dict[str, Any]) -> dict[str, Any]:
    """Role, text and bbox of one box, without the internal index."""
    return {"role": box["role"], "text": box["text"], "bbox": list(box["bbox"])}


def _empty_layout_details(
    canvas_w: float, canvas_h: float, min_font_px: int
) -> dict[str, Any]:
    """The result-detail shape used by check 2, with every failure list empty."""
    return {
        "canvas": [canvas_w, canvas_h],
        "min_font_px": min_font_px,
        "box_count": 0,
        "outside_canvas": [],
        "small_font_boxes": [],
        "overlapping_pairs": [],
        "malformed_boxes": [],
    }


def _empty_redraw_details() -> dict[str, Any]:
    """The result-detail shape used by check 7, with nothing measured yet."""
    return {
        "image_sha256": None,
        "redraw_sha256": None,
        "hashes_match": False,
        "question_in_image": False,
        "caption_required": False,
        "caption_present": False,
        "caption_matches": False,
        "caption_texts": [],
        "render_error": None,
        "failed_rules": [],
    }


def _read_failure(exc: _BadPackage) -> dict[str, Any]:
    """Details for a package file that exists but cannot be parsed."""
    return {"failed_rules": ["readable_files"], "failures": [_failure("readable_files", str(exc))]}


def _read_json(path: Path) -> Any:
    """Load one JSON package file; a missing file raises FileNotFoundError."""
    if not path.is_file():
        raise FileNotFoundError(f"required package file is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _BadPackage(f"cannot read {path.name}: {exc}") from exc


def _read_bytes(path: Path) -> bytes:
    """Read one package file; a missing file raises FileNotFoundError."""
    if not path.is_file():
        raise FileNotFoundError(f"required package file is missing: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _BadPackage(f"cannot read {path.name}: {exc}") from exc


def _required_fields(task_type: Any) -> tuple[tuple[str, type], ...]:
    """Every field a task of ``task_type`` must carry, each with its type."""
    if task_type == "series_at_x":
        return _TASK_FIELDS + _SERIES_AT_X_FIELDS
    return _TASK_FIELDS


def _matches_type(value: Any, expected: type) -> bool:
    """Type check where ``int`` excludes bool and ``bool`` is exact."""
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


def _type_name(expected: type) -> str:
    """Human-readable name for an expected task field type."""
    return "non-boolean int" if expected is int else expected.__name__


def _is_number(value: Any) -> bool:
    """True for finite ints and floats, excluding bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _duplicates(items: list[Any]) -> list[Any]:
    """Items that appear more than once, in first-seen order."""
    seen: set[Any] = set()
    repeated: list[Any] = []
    for item in items:
        if item in seen and item not in repeated:
            repeated.append(item)
        seen.add(item)
    return repeated


def _failure(rule: str, message: str) -> dict[str, str]:
    """One failed rule record for a check's details."""
    return {"rule": rule, "message": message}


def _result(name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    """Build the result dict every check returns."""
    return {"check": name, "passed": bool(passed), "details": details}
