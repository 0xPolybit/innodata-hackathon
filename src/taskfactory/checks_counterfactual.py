"""Check 6: counterfactual re-render. Change the data, redraw it, and require the pixel reader to follow.

A bar package passes when altering its data changes the true answer, the altered
chart is redrawn from the altered spec, and the pixel reader (check 5) reads the
new answer from that picture. A reader that memorised the original picture, or
that copied the old label, fails this check.

The steps follow PLAN.md section 4.6 (check 6):

1. Load ``spec.json`` and ``task.json``. The original answer is ``task["answer"]``.
2. Alter a deep copy of the spec so the true answer must change.

   - extremum: the answer bar is sunk below the smallest value when that is at
     least 1, else lifted above the largest. A lift keeps the answer category on
     top, so the check reports the answer as unchanged and fails.
   - value_lookup: the value of the answer category becomes ``round(value * 1.5)``,
     or ``value * 2`` when another category already has that value. The new answer
     is the new printed label of that category.
   - rank_k: the answer category swaps values with the category one rank above it,
     so the category at the asked rank changes. The answer must already be the
     category at that rank in the spec, else the check cannot alter it. The new
     answer is the category now at that rank.
   - pair_compare: the two categories the question names swap values, so the
     larger name flips. The answer must already be the larger of the two. The new
     answer is the new larger name.
   - the label of every category whose value changed is recomputed, with
     ``value_format``. When that is None the format is ``"{:.1f}M"`` if every label
     ends with "M", else ``"{:,}"``.

3. Check the altered spec with ``validate_spec``.
4. Redraw it with ``render_bar`` into a temporary package folder, with the new
   answer in ``task.json`` and the altered data in ``spec.json``.
5. Run ``check_5_pixels`` on that folder. Its pixel answer must be the new answer.

The check passes only when the answer changed, the pixel reader passed, and its
pixel answer equals the new answer. Bad content returns ``passed`` False with the
reasons in ``details["reasons"]``. Only a missing ``spec.json`` or ``task.json``
raises :class:`FileNotFoundError`.
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

from taskfactory.checks_layout import pair_names_from_question, rank_from_question
from taskfactory.checks_pixels import check_5_pixels
from taskfactory.render import render_bar
from taskfactory.sampler import format_value, validate_spec

__all__ = ["check_6_counterfactual"]

CHECK_NAME = "6_counterfactual"
_SPEC_NAME = "spec.json"
_TASK_NAME = "task.json"
_IMAGE_NAME = "image.png"
_TEXT_BOXES_NAME = "text_boxes.json"

_BAR = "bar"
_EXTREMUM = "extremum"
_VALUE_LOOKUP = "value_lookup"
_RANK_K = "rank_k"
_PAIR_COMPARE = "pair_compare"
_TASK_TYPES = (_EXTREMUM, _VALUE_LOOKUP, _RANK_K, _PAIR_COMPARE)

_LOOKUP_FACTOR = 1.5  # value_lookup: the first new value is round(value * 1.5)
_LOOKUP_FALLBACK = 2  # the second is value * 2, used when the first is already taken
_MILLIONS_FORMAT = "{:.1f}M"  # inferred when every label ends with "M"
_PLAIN_FORMAT = "{:,}"  # inferred otherwise


class _CannotAlter(Exception):
    """The package cannot be altered and redrawn. The message is the reason."""


class _Alteration(NamedTuple):
    """The altered spec and the answer it must produce."""

    spec: dict[str, Any]
    answer: str
    answer_category: str
    answer_value: int


def check_6_counterfactual(pkg_dir: Path, value_format: str | None = None) -> dict[str, Any]:
    """Alter the data of one bar package, redraw it, and require the pixel reader to follow.

    ``value_format`` is the format the labels were printed with, such as
    ``"{:.1f}M"``. When it is None the format is inferred from the labels.

    Raises FileNotFoundError when spec.json or task.json is missing. Bad content
    returns ``passed`` False with the reasons in ``details["reasons"]``.
    """
    pkg = Path(pkg_dir)
    for name in (_SPEC_NAME, _TASK_NAME):
        if not (pkg / name).is_file():
            raise FileNotFoundError(f"required package file is missing: {pkg / name}")

    details = _empty_details()
    reasons: list[str] = details["reasons"]
    try:
        spec = _read_json(pkg / _SPEC_NAME)
        task = _read_json(pkg / _TASK_NAME)
    except (OSError, ValueError) as exc:
        reasons.append(f"could not read the package: {exc}")
        return _result(False, details)
    if not isinstance(spec, dict):
        reasons.append("spec.json must hold a JSON object")
        return _result(False, details)
    if not isinstance(task, dict):
        reasons.append("task.json must hold a JSON object")
        return _result(False, details)

    original = _str_or_none(task.get("answer"))
    details["task_type"] = _str_or_none(task.get("task_type"))
    details["original_answer"] = original

    problem = _input_problem(spec, task)
    if problem is not None:
        reasons.append(problem)
        return _result(False, details)

    try:
        altered = _alter(spec, task, value_format)
    except _CannotAlter as exc:
        reasons.append(str(exc))
        return _result(False, details)
    details["altered_answer"] = altered.answer
    details["altered_values"] = list(altered.spec["series"][0]["values"])

    details["changed"] = altered.answer != original
    if not details["changed"]:
        reasons.append(f"the altered data still gives the original answer {original!r}")
        return _result(False, details)

    try:
        validate_spec(altered.spec)
    except Exception as exc:  # validate_spec raises ValueError; be defensive anyway.
        reasons.append(f"the altered spec failed validate_spec: {type(exc).__name__}: {exc}")
        return _result(False, details)

    try:
        reader = _redraw_and_read(altered, task)
    except _CannotAlter as exc:
        reasons.append(str(exc))
        return _result(False, details)

    reader_details = reader.get("details")
    if not isinstance(reader_details, dict):
        reader_details = {}
    reader_passed = reader.get("passed") is True
    pixel_answer = _str_or_none(reader_details.get("pixel_answer"))
    details["reader_passed"] = reader_passed
    details["pixel_answer_after_redraw"] = pixel_answer

    if not reader_passed:
        reasons.append("the pixel reader did not pass the redrawn package")
        reasons.extend(f"pixel reader: {reason}" for reason in reader_details.get("reasons", []))
    if pixel_answer != altered.answer:
        reasons.append(
            f"the pixel reader answered {pixel_answer!r}, "
            f"not the altered answer {altered.answer!r}"
        )

    passed = details["changed"] and reader_passed and pixel_answer == altered.answer
    return _result(passed, details)


def _input_problem(spec: dict[str, Any], task: dict[str, Any]) -> str | None:
    """Why the original package cannot be altered, or None when it can."""
    try:
        validate_spec(spec)
    except Exception as exc:  # validate_spec raises ValueError; be defensive anyway.
        return f"spec.json failed validate_spec: {type(exc).__name__}: {exc}"
    if spec.get("family") != _BAR:
        return f"check 6 redraws bar specs only, not family {spec.get('family')!r}"
    if task.get("task_type") not in _TASK_TYPES:
        return f"unsupported task_type {task.get('task_type')!r}"
    if not isinstance(task.get("answer"), str):
        return "task.answer must be a string"
    return None


def _alter(spec: dict[str, Any], task: dict[str, Any], value_format: str | None) -> _Alteration:
    """Return an altered copy of ``spec`` and its new answer.

    Raises _CannotAlter when the answer category is missing, the question does
    not name what the alteration needs, or the label cannot be printed.
    """
    x_labels: list[str] = spec["x_labels"]
    category = task.get("answer_category")
    if not isinstance(category, str) or category not in x_labels:
        raise _CannotAlter(
            f"task.answer_category {category!r} is not one of the spec's categories"
        )
    if len(set(x_labels)) != len(x_labels):
        raise _CannotAlter("the spec's category names are not unique")
    index = x_labels.index(category)

    altered = copy.deepcopy(spec)
    series = altered["series"][0]
    values: list[int] = series["values"]
    fmt = value_format if value_format is not None else _inferred_format(series["labels"])

    task_type = task.get("task_type")
    if task_type == _EXTREMUM:
        _sink_or_lift_bar(values, index)
        series["labels"][index] = _print_label(values[index], fmt)
        top = values.index(max(values))
        return _Alteration(altered, x_labels[top], x_labels[top], values[top])
    if task_type == _RANK_K:
        return _swap_for_rank_k(altered, task, index, fmt)
    if task_type == _PAIR_COMPARE:
        return _swap_for_pair_compare(altered, task, category, fmt)
    if task_type != _VALUE_LOOKUP:
        raise _CannotAlter(f"unsupported task_type {task_type!r}")
    _scale_bar(values, index)
    series["labels"][index] = _print_label(values[index], fmt)
    return _Alteration(altered, series["labels"][index], category, values[index])


def _swap_for_rank_k(
    altered: dict[str, Any], task: dict[str, Any], index: int, fmt: str
) -> _Alteration:
    """Swap the answer category's value with the value of the category one rank above it.

    The answer must sit at the asked rank, so the category one rank above it is
    the one just before it in the ranking. After the swap the answer takes the
    higher value and moves up a rank, and its neighbour moves down into the asked
    rank. The new answer is read from the altered values, not assumed.
    """
    rank = rank_from_question(task.get("question"))
    if rank is None:
        raise _CannotAlter("task.question does not ask for a rank such as 'second'")
    x_labels: list[str] = altered["x_labels"]
    series = altered["series"][0]
    values: list[int] = series["values"]
    ranking = _ranking(values)
    if rank > len(ranking):
        raise _CannotAlter(f"the spec has {len(ranking)} categories, too few for rank {rank}")
    if ranking[rank - 1] != index:
        raise _CannotAlter(
            f"task.answer_category {x_labels[index]!r} is not the category at rank {rank} "
            "by value in spec.json"
        )

    above = ranking[rank - 2]  # rank 2 or lower, so this is a real category
    values[index], values[above] = values[above], values[index]
    series["labels"][index] = _print_label(values[index], fmt)
    series["labels"][above] = _print_label(values[above], fmt)

    winner = _ranking(values)[rank - 1]
    return _Alteration(altered, x_labels[winner], x_labels[winner], values[winner])


def _swap_for_pair_compare(
    altered: dict[str, Any], task: dict[str, Any], category: str, fmt: str
) -> _Alteration:
    """Swap the values of the two categories the question names, so the larger name flips."""
    x_labels: list[str] = altered["x_labels"]
    asked = pair_names_from_question(task.get("question"), x_labels)
    if len(asked) != 1:
        raise _CannotAlter("task.question does not name two categories of the spec")
    first, second = asked[0]
    if category not in (first, second):
        raise _CannotAlter(
            f"task.answer_category {category!r} is not one of the two categories the question names"
        )
    series = altered["series"][0]
    values: list[int] = series["values"]
    # validate_spec rejects duplicate values, so the two values always differ here.
    first_at, second_at = x_labels.index(first), x_labels.index(second)
    if values[x_labels.index(category)] != max(values[first_at], values[second_at]):
        raise _CannotAlter(
            f"task.answer_category {category!r} is not the larger of {first!r} and "
            f"{second!r} in spec.json"
        )

    values[first_at], values[second_at] = values[second_at], values[first_at]
    series["labels"][first_at] = _print_label(values[first_at], fmt)
    series["labels"][second_at] = _print_label(values[second_at], fmt)

    larger = first if values[first_at] > values[second_at] else second
    larger_at = x_labels.index(larger)
    return _Alteration(altered, larger, larger, values[larger_at])


def _ranking(values: list[int]) -> list[int]:
    """Positions of ``values`` from largest to smallest, equal values in position order.

    This is the order questions.py sorts bars in, so a tie picks the same category.
    """
    return sorted(range(len(values)), key=lambda position: values[position], reverse=True)


def _sink_or_lift_bar(values: list[int], index: int) -> None:
    """Move the answer bar so it stops being the maximum, where the data allows it.

    The bar goes below the smallest value when that is at least 1, else above the
    largest. When sinking it does not leave a unique maximum, it goes above the
    largest instead. Going above keeps it the maximum, so the caller reports the
    answer as unchanged.
    """
    low, high = min(values), max(values)
    new_value = low - 1 if low - 1 >= 1 else high + 1
    trial = values[:index] + [new_value] + values[index + 1 :]
    if trial.count(max(trial)) != 1:
        new_value = high + 1
    values[index] = new_value


def _scale_bar(values: list[int], index: int) -> None:
    """Give the answer bar a new value: round(value * 1.5), or value * 2 when that is in use."""
    new_value = round(values[index] * _LOOKUP_FACTOR)
    if new_value in values[:index] + values[index + 1 :]:
        new_value = values[index] * _LOOKUP_FALLBACK
    values[index] = new_value


def _inferred_format(labels: list[str]) -> str:
    """``"{:.1f}M"`` when every existing label ends with "M", else ``"{:,}"``."""
    return _MILLIONS_FORMAT if all(label.endswith("M") for label in labels) else _PLAIN_FORMAT


def _print_label(value: int, value_format: str) -> str:
    """The printed label for ``value``. Raises _CannotAlter when the format cannot print it."""
    try:
        label = format_value(value, value_format)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise _CannotAlter(
            f"value_format {value_format!r} cannot print {value}: {type(exc).__name__}: {exc}"
        ) from exc
    if not label.strip():
        raise _CannotAlter(f"value_format {value_format!r} prints an empty label for {value}")
    return label


def _redraw_and_read(altered: _Alteration, task: dict[str, Any]) -> dict[str, Any]:
    """Draw the altered spec into a temporary package and return the pixel reader's result."""
    question = task.get("question") if altered.spec["question_in_image"] is True else None
    with tempfile.TemporaryDirectory() as temp_dir:
        pkg = Path(temp_dir)
        try:
            boxes = render_bar(altered.spec, pkg / _IMAGE_NAME, question=question)
        except Exception as exc:  # render_bar raises ValueError for a layout it cannot fit.
            raise _CannotAlter(
                f"the altered spec cannot be drawn: {type(exc).__name__}: {exc}"
            ) from exc
        new_task = dict(task)
        new_task.update(
            answer=altered.answer,
            answer_category=altered.answer_category,
            answer_value=altered.answer_value,
        )
        _write_json(pkg / _TEXT_BOXES_NAME, boxes)
        _write_json(pkg / _TASK_NAME, new_task)
        _write_json(pkg / _SPEC_NAME, altered.spec)
        return check_5_pixels(pkg)


def _empty_details() -> dict[str, Any]:
    """The result-detail shape, with nothing measured yet."""
    return {
        "task_type": None,
        "original_answer": None,
        "altered_answer": None,
        "altered_values": None,
        "pixel_answer_after_redraw": None,
        "reader_passed": False,
        "changed": False,
        "reasons": [],
    }


def _result(passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"check": CHECK_NAME, "passed": bool(passed), "details": details}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
