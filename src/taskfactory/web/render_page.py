"""Render the TaskFactory form page on top of the shared design system."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from taskfactory.web.forms import (
    CHARTS_PER_TYPE_MAX,
    CHARTS_PER_TYPE_MIN,
    CHART_TYPES,
    DIFFICULTIES,
    FORM_DEFAULTS,
    MAX_TASKS,
    QUESTION_TYPES,
    SEED_MAX,
    SEED_MIN,
    TOPICS,
    default_task_count,
)
from taskfactory.web.theme import ICONS, REPO_URL, page_shell

__all__ = ["COLD_START_MESSAGE", "REPO_URL", "render_page"]

# A note on the form, not an error: the container may need to boot before the
# first request is answered. The 60 seconds is the plan's estimate.
COLD_START_MESSAGE = (
    "Starting the demo. The first request can take up to 60 seconds."
)

# The form's plain-English labels. The submitted values stay the ones in
# forms.QUESTION_TYPES; only the words shown beside them change.
QUESTION_LABELS = {
    "value_lookup": "Value lookup",
    "extremum": "Extremum (highest/lowest)",
    "rank_k": "Rank (nth)",
    "pair_compare": "Pair comparison",
    "series_at_x": "Series at x",
}


def _merged(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """The form defaults, overridden by ``values`` when it is given."""
    merged = dict(FORM_DEFAULTS)
    if values:
        merged.update(values)
    return merged


def _chosen(value: Any) -> list[str]:
    """The selected names from a scalar or a sequence."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def _section_title(text: str) -> str:
    """One section heading above a group of fields.

    The registration mark is drawn by CSS, so the heading stays plain text and
    the document has a real h3 under the card's h2.
    """
    return f'<h3 class="section-title">{escape(text)}</h3>'


def _number_field(
    name: str,
    label: str,
    value: Any,
    minimum: int,
    maximum: int,
    hint: str,
    icon: str,
) -> str:
    """A labelled number input with a hint."""
    return "\n".join(
        [
            '<div class="field">',
            f'<label class="label" for="{name}">{ICONS[icon]}<span>{escape(label)}</span></label>',
            (
                f'<input class="input" id="{name}" name="{name}" type="number" '
                f'min="{minimum}" max="{maximum}" value="{escape(str(value))}" required>'
            ),
            f'<p class="hint">{escape(hint)}</p>',
            "</div>",
        ]
    )


def _choice_field(
    name: str,
    legend: str,
    options: Mapping[str, str],
    chosen: Sequence[str],
    kind: str,
    icon: str,
    hint: str = "",
    sentinel: bool = False,
) -> str:
    """A pill-style radio or checkbox group.

    A checkbox group carries a hidden empty value with the same name, so an
    unchecked group submits an empty value instead of disappearing. That is
    what lets the server tell "nothing picked" from a field never sent.
    """
    lines = [
        '<fieldset class="field">',
        f'<legend class="label">{ICONS[icon]}<span>{escape(legend)}</span></legend>',
    ]
    if sentinel:
        lines.append(f'<input type="hidden" name="{name}" value="">')
    lines.append('<div class="checkbox-group">')
    for option, label in options.items():
        checked = " checked" if option in chosen else ""
        lines.append(
            f'<label class="checkbox"><input type="{kind}" name="{name}" '
            f'value="{escape(option)}"{checked}><span>{escape(label)}</span></label>'
        )
    lines.append("</div>")
    if hint:
        lines.append(f'<p class="hint">{escape(hint)}</p>')
    lines.append("</fieldset>")
    return "\n".join(lines)


def _image_toggle(checked: bool) -> str:
    """The question-in-image checkbox, styled as one pill."""
    state = " checked" if checked else ""
    return "\n".join(
        [
            '<fieldset class="field">',
            f'<legend class="label">{ICONS["image"]}<span>Print question on image</span></legend>',
            '<div class="checkbox-group">',
            (
                '<label class="checkbox"><input type="checkbox" '
                f'name="question_in_image" value="on"{state}><span>On</span></label>'
            ),
            "</div>",
            '<p class="hint">The exact answer is always printed.</p>',
            "</fieldset>",
        ]
    )


def _form(values: Mapping[str, Any] | None) -> str:
    """The whole form: Dataset, Charts and Questions groups and the button."""
    merged = _merged(values)
    question_labels = {name: QUESTION_LABELS[name] for name in QUESTION_TYPES}
    return f"""<form method="post" action="/api/generate">
{_section_title("Dataset")}
<div class="form-grid">
{_number_field("seed", "Seed", merged["seed"], SEED_MIN, SEED_MAX, "Same seed, same charts", "sliders-horizontal")}
{_number_field("charts_per_type", "Charts per type", merged["charts_per_type"], CHARTS_PER_TYPE_MIN, CHARTS_PER_TYPE_MAX, "Between 1 and 6 charts for each selected type.", "list-checks")}
{_choice_field("topic", "Topic", TOPICS, _chosen(merged["topic"]), "radio", "database", "Synthetic data for one domain.")}
{_choice_field("difficulty", "Difficulty", DIFFICULTIES, _chosen(merged["difficulty"]), "radio", "gauge", "Standard or harder thresholds for the checks.")}
</div>
<hr class="separator">
{_section_title("Charts")}
<div class="form-grid">
{_choice_field("chart_types", "Chart types", CHART_TYPES, _chosen(merged["chart_types"]), "checkbox", "list-checks", "Choose at least one. Bar charts carry four question types; line charts carry the series question.", sentinel=True)}
{_image_toggle(bool(merged["question_in_image"]))}
</div>
<hr class="separator">
{_section_title("Questions")}
{_choice_field("question_types", "Question types", question_labels, _chosen(merged["question_types"]), "checkbox", "list-checks", "Choose at least one. Series at x needs line charts.", sentinel=True)}
<p class="hint">About {default_task_count()} tasks with these defaults. A choice above {MAX_TASKS} tasks is refused.</p>
<div class="form-actions">
<button class="btn btn-primary btn-lg" type="submit">{ICONS["play"]}<span>Generate charts</span></button>
</div>
</form>"""


def render_page(values: Mapping[str, Any] | None = None) -> str:
    """The form page: hero, the build card, the cold-start note and the checks."""
    body = f"""<section class="hero">
<h1>Make chart questions with exact answers</h1>
<p>Charts are drawn from seeded data, so every answer is known exactly. Seven checks run without a model, and any chart that fails is shown with the reason it was rejected.</p>
</section>

<div class="card page-enter delay-1">
<div class="card-header">
<h2 class="card-title">Build a set of charts</h2>
<p class="card-description">Same seed, same charts. Change anything, then press Generate.</p>
</div>
<div class="card-content">
{_form(values)}
<p class="note" role="status">{ICONS["info"]}<span>{escape(COLD_START_MESSAGE)}</span></p>
</div>
</div>

<section class="checks-intro" aria-labelledby="checks-intro-heading">
<h2 class="section-title" id="checks-intro-heading">How it checks</h2>
<div class="stats">
<div class="stat">
<h3>Exact answers</h3>
<p>Every answer comes from the seeded data, not from a model guess.</p>
</div>
<div class="stat">
<h3>Seven local checks</h3>
<p>Text size, clarity, pixel reader, OCR read-back and redraw tests on each task.</p>
</div>
<div class="stat">
<h3>Free to run</h3>
<p>No billing and no keys. The checks run in plain code.</p>
</div>
</div>
</section>"""
    return page_shell("TaskFactory", body, active="generate")
