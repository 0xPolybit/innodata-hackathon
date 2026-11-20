"""Question templates with ground-truth answers for bar and line chart specs.

Ground truth is read from the spec alone: ``x_labels`` names the categories (bar)
or the years (line) and ``series[*].values`` / ``labels`` hold each bar's or
point's raw value and its printed label.  Nothing is read back from a rendered
image.

:func:`make_questions` returns one task dict per supported question type.  For a
bar spec the order is ``value_lookup``, ``extremum``, ``rank_k`` then
``pair_compare``; for a line spec only ``series_at_x`` is produced.  A task
whose relative gap falls below ``min_margin`` is skipped entirely, contributing
no dict for that spec.  ``answer`` is exactly the string a model must output;
``answer_value`` and ``answer_category`` carry the numeric value and category
alongside it for scoring.
"""

from __future__ import annotations

from typing import Any

__all__ = ["make_questions", "normalise_answer"]

_BAR = "bar"
_LINE = "line"
_VALUE_LOOKUP = "value_lookup"
_EXTREMUM = "extremum"
_RANK_K = "rank_k"
_PAIR_COMPARE = "pair_compare"
_SERIES_AT_X = "series_at_x"

# Ordinal words for the ranks a rank_k question asks for: index i names rank i + 2,
# so the tuple covers ranks 2 to 19, enough for a 20-category chart.
_ORDINALS = (
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
)


class _SkipQuestion(ValueError):
    """A question type that cannot be asked for this spec."""


def normalise_answer(text: str) -> str:
    """Return ``text`` in the form used to compare a model answer.

    The text is stripped, lowercased, its internal whitespace runs are
    collapsed to single spaces and one trailing period is removed, so
    ``" Spain. "`` and ``"spain"`` compare equal.
    """
    if not isinstance(text, str):
        raise ValueError(f"text: expected a string, got {type(text).__name__}")
    normalised = " ".join(text.strip().lower().split())
    if normalised.endswith("."):
        normalised = normalised[:-1].rstrip()
    return normalised


def make_questions(
    spec: dict[str, Any], *, min_margin: float = 0.05
) -> list[dict[str, Any]]:
    """Build the question tasks for one bar or line spec.

    A bar spec returns one dict per implemented type, in the order
    ``value_lookup``, ``extremum``, ``rank_k`` then ``pair_compare``.  A line
    spec returns only a ``series_at_x`` dict, or an empty list when the top two
    series at the asked year are closer than ``min_margin``.  ``min_margin`` is
    the smallest relative gap an answer may have to the values it is compared
    with; a type below it is skipped and contributes no dict for that spec.

    Raises :class:`ValueError` for an unsupported family, a malformed spec, a
    bar extremum or line maximum whose top value is shared by more than one
    category or series, or a ``seed`` that would ask for a rank beyond the
    supported ordinals.
    """
    if not isinstance(spec, dict):
        raise ValueError(f"spec: expected a dict, got {type(spec).__name__}")

    family = spec.get("family")
    if family == _LINE:
        return _line_questions(spec, min_margin=min_margin)
    if family != _BAR:
        raise ValueError(
            "spec.family: make_questions supports 'bar' and 'line', "
            f"got {family!r}"
        )

    domain = _require_str(spec, "domain")
    index = _require_int(spec, "index")
    seed = _require_int(spec, "seed")
    x_labels = _require_str_list(spec, "x_labels")

    question_in_image = spec.get("question_in_image")
    if not isinstance(question_in_image, bool):
        raise ValueError("spec.question_in_image: expected a boolean")

    series = spec.get("series")
    if not isinstance(series, list) or len(series) != 1:
        raise ValueError("spec.series: a bar spec needs exactly one series")
    bar = series[0]
    if not isinstance(bar, dict):
        raise ValueError("spec.series[0]: expected an object")

    values = _int_list(bar.get("values"), "spec.series[0].values")
    labels = _str_list(bar.get("labels"), "spec.series[0].labels")
    if len(values) != len(x_labels):
        raise ValueError(
            "spec.series[0].values: expected "
            f"{len(x_labels)} values to match x_labels, got {len(values)}"
        )
    if len(labels) != len(values):
        raise ValueError(
            "spec.series[0].labels: expected "
            f"{len(values)} labels to match values, got {len(labels)}"
        )

    position = seed % len(x_labels)
    lookup = {
        "task_type": _VALUE_LOOKUP,
        "family": _BAR,
        "domain": domain,
        "spec_index": index,
        "question": f"What value is shown for {x_labels[position]}?",
        "answer": labels[position],
        "answer_value": values[position],
        "answer_category": x_labels[position],
        "reasoning_steps": 1,
        "answer_printed_in_image": True,
        "question_in_image": question_in_image,
    }

    maximum = max(values)
    winners = [offset for offset, value in enumerate(values) if value == maximum]
    if len(winners) != 1:
        raise ValueError(
            "spec.series[0].values: the maximum value is not unique"
        )
    best = winners[0]
    extremum = {
        "task_type": _EXTREMUM,
        "family": _BAR,
        "domain": domain,
        "spec_index": index,
        "question": "Which category has the highest value?",
        "answer": x_labels[best],
        "answer_value": maximum,
        "answer_category": x_labels[best],
        "reasoning_steps": len(x_labels),
        "answer_printed_in_image": True,
        "question_in_image": question_in_image,
    }

    tasks = [lookup, extremum]

    try:
        tasks.append(
            _rank_k_task(
                domain=domain,
                index=index,
                seed=seed,
                x_labels=x_labels,
                values=values,
                question_in_image=question_in_image,
                min_margin=min_margin,
            )
        )
    except _SkipQuestion:
        pass

    try:
        tasks.append(
            _pair_compare_task(
                domain=domain,
                index=index,
                x_labels=x_labels,
                values=values,
                question_in_image=question_in_image,
                min_margin=min_margin,
            )
        )
    except _SkipQuestion:
        pass

    return tasks


def _line_questions(
    spec: dict[str, Any], *, min_margin: float
) -> list[dict[str, Any]]:
    """Return the ``series_at_x`` task for a line spec, or no dict.

    The year is ``x_labels[seed % len(x_labels)]``.  The answer is the series
    with the highest value at that year; the task is skipped when the top two
    values are closer than ``min_margin``, measured as
    ``(max - second) / max``.  A shared maximum is an error because the answer
    would not be unique.
    """
    domain = _require_str(spec, "domain")
    index = _require_int(spec, "index")
    seed = _require_int(spec, "seed")
    x_labels = _require_str_list(spec, "x_labels")

    question_in_image = spec.get("question_in_image")
    if not isinstance(question_in_image, bool):
        raise ValueError("spec.question_in_image: expected a boolean")

    series = spec.get("series")
    if not isinstance(series, list) or len(series) < 2:
        raise ValueError("spec.series: a line spec needs at least two series")

    names: list[str] = []
    columns: list[list[int]] = []
    for position, item in enumerate(series):
        prefix = f"spec.series[{position}]"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix}: expected an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{prefix}.name: expected a non-empty string")
        if name in names:
            raise ValueError(f"spec.series: duplicate series name {name!r}")
        values = _int_list(item.get("values"), f"{prefix}.values")
        if len(values) != len(x_labels):
            raise ValueError(
                f"{prefix}.values: expected "
                f"{len(x_labels)} values to match x_labels, got {len(values)}"
            )
        names.append(name)
        columns.append(values)

    year_position = seed % len(x_labels)
    year = x_labels[year_position]
    at_year = [values[year_position] for values in columns]

    maximum = max(at_year)
    winners = [
        position for position, value in enumerate(at_year) if value == maximum
    ]
    if len(winners) != 1:
        raise ValueError(
            f"spec.series: the highest value in {year} is not unique"
        )
    best = winners[0]
    second = max(
        value for position, value in enumerate(at_year) if position != best
    )
    margin = 0.0 if maximum == 0 else (maximum - second) / maximum
    if margin < min_margin:
        return []

    return [
        {
            "task_type": _SERIES_AT_X,
            "family": _LINE,
            "domain": domain,
            "spec_index": index,
            "question": f"Which series is highest in {year}?",
            "answer": names[best],
            "answer_value": at_year[best],
            "answer_category": names[best],
            "year": year,
            "reasoning_steps": len(series),
            "answer_printed_in_image": True,
            "question_in_image": question_in_image,
        }
    ]


def _rank_k_task(
    *,
    domain: str,
    index: int,
    seed: int,
    x_labels: list[str],
    values: list[int],
    question_in_image: bool,
    min_margin: float,
) -> dict[str, Any]:
    """Return the rank_k task or raise :class:`_SkipQuestion`.

    The rank is chosen without randomness as ``(seed % (n - 2)) + 2``, so it
    lies in ``2 .. n - 1``: the answer always has one higher and one lower
    value.  Values must be distinct, as the sampler guarantees.
    """
    count = len(x_labels)
    if count < 3:
        raise _SkipQuestion("rank_k needs at least three categories")

    rank = (seed % (count - 2)) + 2
    if rank - 2 >= len(_ORDINALS):
        raise ValueError(
            f"rank_k: no ordinal for rank {rank}; "
            f"at most {len(_ORDINALS) + 2} categories are supported"
        )

    ranked = sorted(
        range(count), key=lambda position: values[position], reverse=True
    )
    position = ranked[rank - 1]
    answer_value = values[position]

    for neighbour_rank in (rank - 1, rank + 1):
        if neighbour_rank < 1 or neighbour_rank > count:
            continue
        neighbour_value = values[ranked[neighbour_rank - 1]]
        largest = max(answer_value, neighbour_value)
        if largest <= 0:
            continue
        gap = abs(answer_value - neighbour_value) / largest
        if gap < min_margin:
            raise _SkipQuestion("rank gap below margin")

    return {
        "task_type": _RANK_K,
        "family": _BAR,
        "domain": domain,
        "spec_index": index,
        "question": f"Which category ranks {_ORDINALS[rank - 2]} by value?",
        "answer": x_labels[position],
        "answer_value": answer_value,
        "answer_category": x_labels[position],
        "reasoning_steps": count,
        "answer_printed_in_image": True,
        "question_in_image": question_in_image,
    }


def _pair_compare_task(
    *,
    domain: str,
    index: int,
    x_labels: list[str],
    values: list[int],
    question_in_image: bool,
    min_margin: float,
) -> dict[str, Any]:
    """Return the pair_compare task or raise :class:`_SkipQuestion`.

    The pair with the largest relative difference wins.  The scan runs left to
    right and only a strictly larger difference replaces the current pair, so
    ties resolve to the lower first index, then the lower second index.
    """
    best_gap = -1.0
    best_pair: tuple[int, int] | None = None
    for first in range(len(values)):
        for second in range(first + 1, len(values)):
            largest = max(values[first], values[second])
            gap = (
                0.0
                if largest == 0
                else abs(values[first] - values[second]) / largest
            )
            if gap > best_gap:
                best_gap = gap
                best_pair = (first, second)

    if best_pair is None:
        raise _SkipQuestion("pair_compare needs at least two categories")
    if best_gap < min_margin:
        raise _SkipQuestion("pair difference below margin")

    first, second = best_pair
    if values[first] > values[second]:
        answer_position = first
    else:
        answer_position = second

    return {
        "task_type": _PAIR_COMPARE,
        "family": _BAR,
        "domain": domain,
        "spec_index": index,
        "question": (
            f"Which is higher, {x_labels[first]} or {x_labels[second]}?"
        ),
        "answer": x_labels[answer_position],
        "answer_value": values[answer_position],
        "answer_category": x_labels[answer_position],
        "reasoning_steps": 2,
        "answer_printed_in_image": True,
        "question_in_image": question_in_image,
    }


def _require_int(spec: dict[str, Any], key: str) -> int:
    """Return ``spec[key]`` as a non-boolean integer or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    value = spec[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"spec.{key}: expected an integer, got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"spec.{key}: must be non-negative, got {value}")
    return value


def _require_str(spec: dict[str, Any], key: str) -> str:
    """Return ``spec[key]`` as a non-empty string or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    value = spec[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"spec.{key}: expected a non-empty string")
    return value


def _require_str_list(spec: dict[str, Any], key: str) -> list[str]:
    """Return ``spec[key]`` as a non-empty list of non-empty strings or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    return _str_list(spec[key], f"spec.{key}")


def _str_list(value: Any, name: str) -> list[str]:
    """Return ``value`` as a non-empty list of non-empty strings or raise."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name}: expected a non-empty list of strings")
    for position, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name}[{position}]: expected a non-empty string")
    return list(value)


def _int_list(value: Any, name: str) -> list[int]:
    """Return ``value`` as a non-empty list of non-boolean integers or raise."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name}: expected a non-empty list of integers")
    for position, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(
                f"{name}[{position}]: expected an integer, "
                f"got {type(item).__name__}"
            )
    return list(value)
