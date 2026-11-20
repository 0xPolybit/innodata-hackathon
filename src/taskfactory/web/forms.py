"""The input fields of the TaskFactory form: allowed values, defaults and HTML.

Validation does not live here yet: this module only knows what the fields may
contain and renders the controls with their defaults.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

SEED_MIN = 1
SEED_MAX = 2147483647
CHARTS_PER_TYPE_MIN = 1
CHARTS_PER_TYPE_MAX = 6

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

FORM_DEFAULTS: dict[str, Any] = {
    "seed": 20261206,
    "charts_per_type": 3,
    "chart_types": ["bar", "line"],
    "topic": "tourism",
    "question_types": ["value_lookup", "extremum", "rank_k", "pair_compare", "series_at_x"],
    "difficulty": "standard",
    "question_in_image": True,
}


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
) -> str:
    """A radio or checkbox group wrapped in a fieldset."""
    lines = ['<fieldset class="field">', f"  <legend>{escape(legend)}</legend>"]
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
