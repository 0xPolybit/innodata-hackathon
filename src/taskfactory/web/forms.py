"""The input fields of the TaskFactory form: allowed values, defaults, validation and HTML.

:func:`parse_form` turns a submitted form body into a :class:`ParsedForm` or
raises :class:`FormError` with one message the user can read. The messages are
the ones in docs/IMPLEMENTATION_PLAN.md section 9.

The task count is the number of task slots the sampler would attempt: a bar
chart carries the four bar question types and a line chart carries
``series_at_x`` only. A question type that needs a chart type the user did not
pick adds no tasks. The default choices give 3 bar charts x 4 types + 3 line
charts x 1 type = 15 tasks, and any choice above :data:`MAX_TASKS` is refused.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

SEED_MIN = 1
SEED_MAX = 2147483647
CHARTS_PER_TYPE_MIN = 1
CHARTS_PER_TYPE_MAX = 6
MAX_TASKS = 24

CHART_TYPES: dict[str, str] = {
    "bar": "Bar charts",
    "line": "Line charts",
}

TOPICS: dict[str, str] = {
    "tourism": "Tourism",
    "retail": "Retail",
    "energy": "Energy",
}

QUESTION_TYPES: dict[str, str] = {
    "value_lookup": "Read a single value",
    "extremum": "Find the highest or lowest",
    "rank_k": "Rank the categories",
    "pair_compare": "Compare two categories",
    "series_at_x": "Read a line at a year",
}

DIFFICULTIES: dict[str, str] = {
    "standard": "Standard",
    "harder": "Harder",
}

# The question types each family can carry. questions.py asks these of a bar
# spec, and only series_at_x of a line spec.
BAR_QUESTION_TYPES = ("value_lookup", "extremum", "rank_k", "pair_compare")
LINE_QUESTION_TYPES = ("series_at_x",)

FORM_DEFAULTS: dict[str, Any] = {
    "seed": 20261206,
    "charts_per_type": 3,
    "chart_types": ["bar", "line"],
    "topic": "tourism",
    "question_types": ["value_lookup", "extremum", "rank_k", "pair_compare", "series_at_x"],
    "difficulty": "standard",
    "question_in_image": True,
}

SEED_MESSAGE = "Seed must be a whole number between 1 and 2147483647."
CHARTS_MESSAGE = "Charts per type must be between 1 and 6."
CHOICE_MESSAGE = "Pick at least one chart type and one question type."


class FormError(ValueError):
    """A submitted form value the user can fix, with one user-facing message."""

    @property
    def message(self) -> str:
        """The message to show, identical to ``str(error)``."""
        return str(self)


@dataclass(frozen=True)
class ParsedForm:
    """The validated choices of one form submission."""

    seed: int
    charts_per_type: int
    chart_types: tuple[str, ...]
    topic: str
    question_types: tuple[str, ...]
    difficulty: str
    question_in_image: bool

    @property
    def families(self) -> tuple[str, ...]:
        """The run's families, in the canonical bar, line order."""
        return self.chart_types

    @property
    def domains(self) -> tuple[str, ...]:
        """The run's domains: the one topic the form offers."""
        return (self.topic,)

    @property
    def task_count(self) -> int:
        """The number of task slots these settings would ask the sampler for."""
        return planned_task_count(
            self.chart_types, self.question_types, self.charts_per_type
        )


def planned_task_count(
    chart_types: Sequence[str],
    question_types: Sequence[str],
    charts_per_type: int,
) -> int:
    """Count the task slots the sampler would attempt for one domain.

    A bar chart carries each chosen bar question type and a line chart carries
    ``series_at_x`` when it is chosen. Question types whose family is not
    chosen add nothing, so ``series_at_x`` with bar charts alone makes no
    tasks. The form offers one topic, so one domain.
    """
    family_names = set(chart_types)
    type_names = set(question_types)
    per_chart = 0
    if "bar" in family_names:
        per_chart += len(type_names.intersection(BAR_QUESTION_TYPES))
    if "line" in family_names and "series_at_x" in type_names:
        per_chart += len(type_names.intersection(LINE_QUESTION_TYPES))
    return charts_per_type * per_chart


def task_limit_message(count: int) -> str:
    """The section 9 message for a choice that asks for too many tasks."""
    return (
        f"This choice makes {count} tasks; the limit is {MAX_TASKS}. "
        "Choose fewer charts or question types."
    )


def default_form_payload() -> dict[str, Any]:
    """The values a browser submits for the untouched default form."""
    return {
        "seed": str(FORM_DEFAULTS["seed"]),
        "charts_per_type": str(FORM_DEFAULTS["charts_per_type"]),
        "chart_types": list(FORM_DEFAULTS["chart_types"]),
        "topic": str(FORM_DEFAULTS["topic"]),
        "question_types": list(FORM_DEFAULTS["question_types"]),
        "difficulty": str(FORM_DEFAULTS["difficulty"]),
        "question_in_image": "on",
    }


def parse_form(values: Mapping[str, Any]) -> ParsedForm:
    """Validate one submitted form body and return its parsed choices.

    A missing scalar or unknown choice falls back to :data:`FORM_DEFAULTS`. A
    seed or chart count that is not a whole number in range is an error, never
    a default. ``chart_types`` and ``question_types`` must name at least one
    known choice when they are present; the form sends an empty value for an
    unchecked group, so an unchecked group is an error. The agreement is
    checked in :func:`planned_task_count` because a question type may need a
    chart type the user did not choose.
    """
    if values is None:  # defensive: a WSGI app may pass an empty dict
        values = {}

    seed = _parse_seed(_scalar(values, "seed"))
    charts_per_type = _parse_charts(_scalar(values, "charts_per_type"))

    chart_choices = _selections(values, "chart_types")
    if chart_choices is None:
        chart_choices = _defaults_for("chart_types")
    chart_types = tuple(name for name in CHART_TYPES if name in chart_choices)
    if not chart_types:
        if not chart_choices:
            raise FormError(CHOICE_MESSAGE)
        # Only unknown names were sent; fall back like any other unknown value.
        chart_types = tuple(_defaults_for("chart_types"))

    question_choices = _selections(values, "question_types")
    if question_choices is None:
        question_choices = _defaults_for("question_types")
    question_types = tuple(name for name in QUESTION_TYPES if name in question_choices)
    if not question_types:
        if not question_choices:
            raise FormError(CHOICE_MESSAGE)
        question_types = tuple(_defaults_for("question_types"))

    topic = _parse_choice(_scalar(values, "topic"), TOPICS, FORM_DEFAULTS["topic"])
    difficulty = _parse_choice(
        _scalar(values, "difficulty"), DIFFICULTIES, FORM_DEFAULTS["difficulty"]
    )
    question_in_image = _parse_checkbox(values)

    count = planned_task_count(chart_types, question_types, charts_per_type)
    if count > MAX_TASKS:
        raise FormError(task_limit_message(count))

    return ParsedForm(
        seed=seed,
        charts_per_type=charts_per_type,
        chart_types=chart_types,
        topic=topic,
        question_types=question_types,
        difficulty=difficulty,
        question_in_image=question_in_image,
    )


def _parse_seed(raw: Any) -> int:
    """A whole number from the seed range, or the seed error message."""
    if raw is None:
        return int(FORM_DEFAULTS["seed"])
    try:
        value = int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        raise FormError(SEED_MESSAGE) from None
    if not SEED_MIN <= value <= SEED_MAX:
        raise FormError(SEED_MESSAGE)
    return value


def _parse_charts(raw: Any) -> int:
    """A whole number from the charts-per-type range, or its error message."""
    if raw is None:
        return int(FORM_DEFAULTS["charts_per_type"])
    try:
        value = int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        raise FormError(CHARTS_MESSAGE) from None
    if not CHARTS_PER_TYPE_MIN <= value <= CHARTS_PER_TYPE_MAX:
        raise FormError(CHARTS_MESSAGE)
    return value


def _parse_choice(raw: Any, choices: Mapping[str, str], default: Any) -> str:
    """A known choice, or ``default`` for a missing or unknown one."""
    if raw is None:
        return str(default)
    text = str(raw).strip()
    return text if text in choices else str(default)


def _parse_checkbox(values: Mapping[str, Any]) -> bool:
    """A checkbox is on when its field is present and not the boolean False."""
    if "question_in_image" not in values:
        return False
    raw = values["question_in_image"]
    if isinstance(raw, bool):
        return raw
    return True


def _scalar(values: Mapping[str, Any], key: str) -> Any:
    """One field's last value, or None when the field is absent."""
    if key not in values:
        return None
    raw = values[key]
    if isinstance(raw, (list, tuple)):
        return raw[-1] if raw else ""
    return raw


def _selections(values: Mapping[str, Any], key: str) -> list[str] | None:
    """Every non-empty value of a checkbox group, or None when it is absent."""
    if key not in values:
        return None
    raw = values[key]
    if isinstance(raw, str):
        items: Sequence[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = [raw]
    return [str(item).strip() for item in items if str(item).strip()]


def _defaults_for(key: str) -> list[Any]:
    """A copy of one default choice list."""
    return list(FORM_DEFAULTS[key])


def _merged(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """The defaults, overridden by ``values`` when it is given."""
    merged = dict(FORM_DEFAULTS)
    if values:
        merged.update(values)
    return merged


def _chosen(value: Any) -> list[str]:
    """A list of selected option values from a scalar or a sequence."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def _number_field(
    name: str,
    label: str,
    value: Any,
    minimum: int,
    maximum: int,
    hint: str,
) -> str:
    """One number input with its label and hint."""
    return "\n".join(
        [
            '<div class="field">',
            f'  <label for="{name}">{escape(label)}</label>',
            (
                f'  <input id="{name}" name="{name}" type="number" '
                f'min="{minimum}" max="{maximum}" value="{escape(str(value))}" required>'
            ),
            f'  <p class="hint">{escape(hint)}</p>',
            "</div>",
        ]
    )


def _choice_group(
    name: str,
    legend: str,
    options: Mapping[str, str],
    chosen: Sequence[str],
    kind: str,
    hint: str = "",
    sentinel: bool = False,
) -> str:
    """A radio or checkbox group wrapped in a fieldset.

    A checkbox group gets a hidden empty field with the same name, so an
    unchecked group submits an empty value instead of disappearing. That lets
    the server tell "nothing picked" from a field that was never sent.
    """
    lines = ['<fieldset class="field">', f"  <legend>{escape(legend)}</legend>"]
    if sentinel:
        lines.append(f'  <input type="hidden" name="{name}" value="">')
    for option, label in options.items():
        checked = " checked" if option in chosen else ""
        lines.append(
            f'  <label class="choice"><input type="{kind}" name="{name}" '
            f'value="{escape(option)}"{checked}> {escape(label)}</label>'
        )
    if hint:
        lines.append(f'  <p class="hint">{escape(hint)}</p>')
    lines.append("</fieldset>")
    return "\n".join(lines)


def render_form_fields(values: Mapping[str, Any] | None = None) -> str:
    """Render the form controls as HTML, using the defaults unless overridden."""
    merged = _merged(values)
    question_in_image = bool(merged["question_in_image"])
    checked = " checked" if question_in_image else ""
    return "\n".join(
        [
            _number_field(
                "seed",
                "Seed",
                merged["seed"],
                SEED_MIN,
                SEED_MAX,
                "The same seed always gives the same tasks.",
            ),
            _number_field(
                "charts_per_type",
                "Charts per chart type",
                merged["charts_per_type"],
                CHARTS_PER_TYPE_MIN,
                CHARTS_PER_TYPE_MAX,
                "Between 1 and 6 charts for each selected type.",
            ),
            _choice_group(
                "chart_types",
                "Chart types",
                CHART_TYPES,
                _chosen(merged["chart_types"]),
                "checkbox",
                "Choose at least one.",
                sentinel=True,
            ),
            _choice_group(
                "topic",
                "Topic",
                TOPICS,
                _chosen(merged["topic"]),
                "radio",
            ),
            _choice_group(
                "question_types",
                "Question types",
                QUESTION_TYPES,
                _chosen(merged["question_types"]),
                "checkbox",
                "Choose at least one. Reading a line at a year needs line charts.",
                sentinel=True,
            ),
            _choice_group(
                "difficulty",
                "Difficulty",
                DIFFICULTIES,
                _chosen(merged["difficulty"]),
                "radio",
            ),
            "\n".join(
                [
                    '<fieldset class="field">',
                    "  <legend>Print question on image</legend>",
                    (
                        '  <label class="choice"><input type="checkbox" '
                        f'name="question_in_image" value="on"{checked}> On</label>'
                    ),
                    '  <p class="hint">The exact answer is always printed.</p>',
                    "</fieldset>",
                ]
            ),
        ]
    )
