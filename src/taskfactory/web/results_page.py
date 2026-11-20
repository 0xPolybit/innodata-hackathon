"""The self-contained results page: summary band, seven checks, cards and rejects.

The page is built from a :class:`~taskfactory.web.generate.GenerationResult`
whose ``artifacts`` hold the run's files and is wrapped in the shared
:func:`~taskfactory.web.theme.page_shell`. Every image is embedded as a base64
data URI, every text value is escaped, and the document loads no script and no
external resource. If the finished page would be larger than
:data:`MAX_PAGE_BYTES`, the section 9 "too large" message page is returned
instead.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from html import escape
from typing import TYPE_CHECKING, Any

from taskfactory.web import forms
from taskfactory.web.generate import RESULT_TOO_LARGE_MESSAGE
from taskfactory.web.results_summary import back_href, render_message
from taskfactory.web.theme import ICONS, page_shell

if TYPE_CHECKING:  # avoids importing the generator at page-render time
    from taskfactory.web.generate import GenerationResult, TaskSummary

__all__ = ["CHECK_NAMES", "CHECK_LABELS", "MAX_PAGE_BYTES", "render_results_page"]

# The seven checks, in the order the bar pipeline runs them. The line checks
# carry a family prefix (``5_line_pixels``); _check_outcomes maps them back to
# these names so one list covers every task.
CHECK_NAMES = (
    "1_schema",
    "2_layout",
    "3_ambiguity",
    "7_redraw",
    "4_ocr",
    "5_pixels",
    "6_counterfactual",
)

_CHECK_ALIASES = {
    "3_line_ambiguity": "3_ambiguity",
    "5_line_pixels": "5_pixels",
    "6_line_counterfactual": "6_counterfactual",
    "7_line_redraw": "7_redraw",
}

# Plain English for the same seven ids, so the page reads without jargon.
CHECK_LABELS = {
    "1_schema": "Schema",
    "2_layout": "Layout",
    "3_ambiguity": "Ambiguity",
    "7_redraw": "Redraw",
    "4_ocr": "OCR read-back",
    "5_pixels": "Pixel reader",
    "6_counterfactual": "Counterfactual",
}

EMPTY_ACCEPTED_MESSAGE = (
    "No tasks were accepted for these settings. Try a different seed or fewer "
    "question types."
)

ZIP_NOTE = (
    "This re-runs the same settings to build the ZIP, so it takes about as long "
    "as the first run."
)

MAX_PAGE_BYTES = 4_000_000


def _svg(paths: str) -> str:
    """One local Lucide-style icon, in the same shape as the shared icons."""
    return (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{paths}</svg>'
    )


# The shared icon set has no home, download, plain check or plain x; these four
# live here so the shared theme stays the form's stylesheet.
_ICONS = {
    "home": _svg(
        '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/>'
        '<path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 '
        '5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "download": _svg(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" x2="12" y1="15" y2="3"/>'
    ),
    "check": _svg('<path d="M20 6 9 17l-5-5"/>'),
    "x": _svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
}

_STYLE = """
.breadcrumb { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 20px; color: var(--muted-foreground); font-size: 13px; }
.breadcrumb a { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; margin-left: -8px; padding: 0 8px; border-radius: var(--radius-control); font-weight: 500; }
.breadcrumb a:hover { background: var(--accent); color: var(--foreground); text-decoration: none; }
.breadcrumb-sep { opacity: 0.55; }
.page-head { margin-bottom: 24px; }
.page-head h1 { margin: 0 0 8px; font-size: clamp(2rem, 1.4rem + 2.4vw, 2.75rem); line-height: 1.1; font-weight: 500; letter-spacing: -0.015em; }
.page-lead { margin: 0; max-width: 44rem; color: var(--muted-foreground); }
.summary-figures { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; border-top: 1px solid var(--border); }
.summary-figure { min-width: 0; margin: 0; padding: 16px 0; border-bottom: 1px solid var(--border); }
.summary-figure:nth-child(odd) { padding-right: 16px; }
.summary-figure:nth-child(even) { padding-left: 16px; border-left: 1px solid var(--border); }
.summary-label { margin: 0; color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; }
.summary-value { margin: 4px 0 0; font-size: 28px; font-weight: 500; line-height: 1.05; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.meter { height: 4px; margin-top: 8px; border-radius: 2px; background: var(--muted); overflow: hidden; }
.meter-fill { display: block; height: 100%; background: var(--primary); }
.run-meta { display: flex; flex-wrap: wrap; gap: 4px 20px; margin: 16px 0 0; color: var(--muted-foreground); font-size: 13px; }
.run-meta code, .task-id, .check-code, .commit-details code { font-family: var(--mono); }
.run-meta code { font-size: 12px; overflow-wrap: anywhere; }
.num { color: var(--foreground); font-family: var(--mono); font-size: 12px; font-weight: 400; }
.commit-details { margin-top: 8px; font-size: 13px; }
.commit-details summary { display: list-item; min-height: 32px; padding-left: 2px; cursor: pointer; color: var(--muted-foreground); font-size: 13px; }
.commit-details summary:hover { color: var(--foreground); }
.commit-details p { margin: 4px 0 0; }
.commit-details code { font-size: 12px; overflow-wrap: anywhere; }
.band-actions { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 12px; margin-top: 20px; }
.band-actions form { margin: 0; }
.band-actions .hint { margin: 8px 0 0; max-width: 34rem; }
.results-section { margin-top: 40px; }
.section-head { margin: 0 0 12px; }
.section-head h2 { display: flex; align-items: baseline; gap: 8px; margin: 0; font-size: 20px; font-weight: 500; letter-spacing: -0.01em; }
.count { color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; font-weight: 400; }
.check-list { list-style: none; display: grid; gap: 12px; margin: 0; padding: 0; }
.check-row { min-width: 0; }
.check-line { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 2px 16px; }
.check-name { font-size: 14px; font-weight: 500; }
.check-code { color: var(--muted-foreground); font-size: 11px; font-weight: 400; }
.check-score { color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; }
.check-row .meter { margin-top: 4px; }
.checks-card .alert { margin-top: 16px; }
.task-grid { list-style: none; display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; margin: 0; padding: 0; }
.task-card { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.task-media { padding: 16px 16px 0; }
.task-media img { display: block; width: 100%; height: auto; border: 1px solid var(--border); border-radius: var(--radius-tag); background: #fff; }
.rejected-card .task-media img { opacity: 0.82; }
.task-body { display: flex; flex: 1; flex-direction: column; gap: 12px; min-width: 0; padding: 16px; }
.task-id { margin: 0; color: var(--muted-foreground); font-size: 11px; overflow-wrap: anywhere; }
.task-question { margin: 0; font-size: 16px; font-weight: 500; line-height: 1.4; overflow-wrap: anywhere; }
.answer-box { display: flex; align-items: flex-start; gap: 8px; padding-top: 12px; border-top: 1px solid var(--border); }
.answer-box > .icon { margin-top: 2px; color: var(--primary); }
.answer-label { display: block; color: var(--muted-foreground); font-family: var(--mono); font-size: 11px; }
.answer-value { margin: 2px 0 0; font-size: 15px; font-weight: 500; overflow-wrap: anywhere; }
.task-meta { margin: 0; color: var(--muted-foreground); font-family: var(--mono); font-size: 11px; overflow-wrap: anywhere; }
.task-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.task-checks { margin: 0; color: var(--muted-foreground); font-size: 12px; }
.check-strip { list-style: none; display: flex; gap: 4px; margin: 0; padding: 0; }
.check-strip li { width: 8px; height: 8px; border-radius: 2px; background: var(--primary); }
.check-strip li.fail { background: var(--destructive); }
.task-badges { list-style: none; display: flex; flex-wrap: wrap; gap: 4px; margin: 0; padding: 0; }
.alert-text { min-width: 0; }
.alert-text ul { margin: 0; padding-left: 16px; }
.reason-list li { overflow-wrap: anywhere; }
.reason-list strong { font-weight: 500; }
.empty-line { display: flex; align-items: flex-start; gap: 8px; margin: 0; color: var(--muted-foreground); font-size: 14px; }
.empty-line .icon { margin-top: 2px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (min-width: 720px) {
  .summary-figures { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .summary-figure { padding: 16px; border-bottom: 0; }
  .summary-figure:nth-child(1) { padding-left: 0; }
  .summary-figure + .summary-figure { border-left: 1px solid var(--border); }
}
@media (min-width: 900px) {
  .task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: no-preference) {
  @keyframes page-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .page-head { animation: page-in 360ms cubic-bezier(0.22, 1, 0.36, 1) both; }
  .task-card { transition: border-color 140ms cubic-bezier(0.22, 1, 0.36, 1); }
  @media (hover: hover) { .task-card:hover { border-color: color-mix(in srgb, var(--foreground) 22%, var(--border)); } }
}
"""


def render_results_page(
    result: "GenerationResult",
    form: forms.ParsedForm | None = None,
) -> str:
    """The whole results document for ``result``, or the too-large message page.

    ``form`` supplies the planned task count and the hidden fields the ZIP form
    reposts. When the finished document would exceed :data:`MAX_PAGE_BYTES`
    bytes, the section 9 too-large message page is returned instead.
    """
    page = _page(result, form)
    if len(page.encode("utf-8")) > MAX_PAGE_BYTES:
        return render_message("Result too large", RESULT_TOO_LARGE_MESSAGE, form)
    return page


def _page(result: "GenerationResult", form: forms.ParsedForm | None) -> str:
    """Build the page text without the size check."""
    body = f"""<style>{_STYLE}</style>
{_breadcrumb()}
<header class="page-head">
<h1>Results</h1>
<p class="page-lead">TaskFactory results for the settings you chose. Every chart carries its question, exact answer and all seven checks.</p>
</header>
{_summary_band(result, form)}
{_planned_note(result, form)}
{_checks_card(result)}
{_accepted_section(result)}
{_rejected_section(result)}"""
    return page_shell("Results", body)


def _breadcrumb() -> str:
    """Home icon-link to the form, then the current Results label."""
    return f"""<nav class="breadcrumb" aria-label="Breadcrumb">
<a href="/">{_ICONS["home"]}<span>Home</span></a>
<span class="breadcrumb-sep" aria-hidden="true">/</span>
<span aria-current="page">Results</span>
</nav>"""


def _summary_band(result: "GenerationResult", form: forms.ParsedForm | None) -> str:
    """The four figures, the run line, the full commit and the two actions."""
    rate = min(max(result.yield_ * 100, 0.0), 100.0)
    rate_text = f"{rate:.1f}"
    elapsed = f"{result.elapsed_seconds:.1f} s"
    return f"""<section class="card results-band" aria-labelledby="summary-heading">
<div class="card-header">
<h2 class="card-title" id="summary-heading">Run summary</h2>
<p class="card-description">Totals for this run. The ZIP holds the same charts and files.</p>
</div>
<div class="card-content">
<div class="summary-figures">
{_summary_figure("Attempted", str(result.attempted))}
{_summary_figure("Accepted", str(result.accepted))}
{_summary_figure("Rejected", str(result.rejected))}
{_summary_figure("Yield", f"{rate_text}%", meter=rate_text)}
</div>
<p class="run-meta">
<span>Run <code>{escape(result.run_id)}</code></span>
<span>Seed <span class="num">{escape(str(result.seed))}</span></span>
<span>Elapsed <span class="num">{escape(elapsed)}</span></span>
<span>Commit <code>{escape(result.commit[:7])}</code></span>
</p>
<details class="commit-details">
<summary>Full commit</summary>
<p><code>{escape(result.commit)}</code></p>
</details>
<div class="band-actions">
{_download_form(form)}
<a class="btn btn-outline" href="{back_href(form)}">{ICONS["arrow-left"]}<span>Back to the form</span></a>
</div>
</div>
</section>"""


def _summary_figure(label: str, value: str, *, meter: str | None = None) -> str:
    """One labelled figure. Yield alone carries a thin bar."""
    bar = ""
    if meter is not None:
        bar = (
            f'<div class="meter" role="progressbar" aria-label="Yield" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{escape(meter)}">'
            f'<span class="meter-fill" style="width:{escape(meter)}%"></span></div>'
        )
    return f"""<div class="summary-figure">
<p class="summary-label">{escape(label)}</p>
<p class="summary-value">{escape(value)}</p>
{bar}
</div>"""


def _planned_note(result: "GenerationResult", form: forms.ParsedForm | None) -> str:
    """The one-line explanation when the pipeline attempted fewer tasks than planned."""
    if form is None:
        return ""
    planned = forms.planned_task_count(
        form.chart_types, form.question_types, form.charts_per_type
    )
    if result.attempted == planned:
        return ""
    text = (
        f"The form planned {planned} tasks; the pipeline attempted "
        f"{result.attempted} because some question types are skipped by the "
        "margin rule at this seed."
    )
    return (
        f'<div class="alert alert-info" role="status">{ICONS["info"]}'
        f"<p>{escape(text)}</p></div>"
    )


def _checks_card(result: "GenerationResult") -> str:
    """One row per check: its plain name, its id and a bar of passes."""
    passed = _check_totals(result)
    rows = []
    aria_max = max(result.attempted, 1)
    for name in CHECK_NAMES:
        count = passed[name]
        label = _plain_name(name)
        rows.append(
            f"""<li class="check-row">
<div class="check-line">
<span class="check-name">{escape(label)} <code class="check-code">{escape(name)}</code></span>
<span class="check-score">{escape(str(count))} of {escape(str(result.attempted))}</span>
</div>
<div class="meter" role="progressbar" aria-label="{escape(label)} passed" aria-valuemin="0" aria-valuemax="{escape(str(aria_max))}" aria-valuenow="{escape(str(count))}"><span class="meter-fill" style="width:{_width(count, result.attempted)}"></span></div>
</li>"""
        )
    rows_html = "\n".join(rows)
    warning = _accepted_failure_alert(result)
    return f"""<section class="card results-section checks-card" aria-labelledby="checks-heading">
<div class="card-header">
<h2 class="card-title" id="checks-heading">Seven checks</h2>
<p class="card-description">How many attempted tasks passed each check.</p>
</div>
<div class="card-content">
<ul class="check-list">
{rows_html}
</ul>
{warning}
</div>
</section>"""


def _accepted_failure_alert(result: "GenerationResult") -> str:
    """A warning only when an accepted task somehow failed a check."""
    failures = []
    for task in result.accepted_tasks:
        names = [_plain_name(check.name) for check in task.checks if not check.passed]
        if names:
            failures.append(f"{task.task_id} ({', '.join(names)})")
    if not failures:
        return ""
    text = (
        "An accepted task failed a check: "
        + "; ".join(failures)
        + ". This should not happen; the task is still listed below."
    )
    return (
        f'<div class="alert alert-warning" role="alert">{ICONS["alert-triangle"]}'
        f"<p>{escape(text)}</p></div>"
    )


def _accepted_section(result: "GenerationResult") -> str:
    """The accepted heading with its count, then the responsive task grid."""
    tasks = sorted(result.accepted_tasks, key=lambda task: task.task_id)
    heading = (
        '<div class="section-head">'
        f'<h2 id="accepted-heading">Accepted tasks <span class="count">{escape(str(len(tasks)))}</span></h2>'
        "</div>"
    )
    if tasks:
        cards = "\n".join(_accepted_card(task, result.artifacts) for task in tasks)
        body = f'<ul class="task-grid">\n{cards}\n</ul>'
    else:
        body = f"""<div class="card empty-state">
<div class="card-content">
<p class="empty-line">{ICONS["info"]}<span>{escape(EMPTY_ACCEPTED_MESSAGE)}</span></p>
</div>
</div>"""
    return (
        '<section class="results-section" aria-labelledby="accepted-heading">\n'
        f"{heading}\n{body}\n</section>"
    )


def _rejected_section(result: "GenerationResult") -> str:
    """The rejected cards, or nothing when every task was accepted."""
    tasks = sorted(result.rejected_tasks, key=lambda task: task.task_id)
    if not tasks:
        return ""
    cards = "\n".join(_rejected_card(task, result.artifacts) for task in tasks)
    heading = (
        '<div class="section-head">'
        f'<h2 id="rejected-heading">Rejected tasks <span class="count">{escape(str(len(tasks)))}</span></h2>'
        "</div>"
    )
    return (
        '<section class="results-section" aria-labelledby="rejected-heading">\n'
        f'{heading}\n<ul class="task-grid">\n{cards}\n</ul>\n</section>'
    )


def _accepted_card(task: "TaskSummary", artifacts: Mapping[str, bytes]) -> str:
    """One accepted task: the chart, its question, exact answer and check strip."""
    payload = _task_payload(artifacts, "tasks", task.task_id)
    question = _text(payload.get("question"))
    answer = _text(payload.get("answer"))
    image = _image_tag(
        artifacts.get(f"tasks/{task.task_id}/image.png"),
        task.task_id,
        question,
    )
    media = f'<div class="task-media">{image}</div>' if image else ""
    checks = f"{task.passed_checks} of {task.total_checks} checks passed"
    meta = " / ".join((task.family, task.question_type, task.domain))
    heading = f'<h3 class="task-question">{escape(question)}</h3>\n' if question else ""
    return f"""<li class="card task-card">
{media}
<div class="task-body">
<p class="task-id"><code>{escape(task.task_id)}</code></p>
{heading}<div class="answer-box">
{_ICONS["check"]}
<div>
<span class="answer-label">Exact answer</span>
<p class="answer-value">{escape(answer)}</p>
</div>
</div>
<p class="task-meta">{escape(meta)}</p>
<div class="task-foot">
<p class="task-checks">{escape(checks)}</p>
<ul class="check-strip" aria-label="Seven checks">
{_checks_strip(task)}
</ul>
</div>
</div>
</li>"""


def _rejected_card(task: "TaskSummary", artifacts: Mapping[str, bytes]) -> str:
    """One rejected task: muted chart, failed check badges and the reasons."""
    payload = _task_payload(artifacts, "rejected", task.task_id)
    question = _text(payload.get("question"))
    image = _image_tag(
        artifacts.get(f"rejected/{task.task_id}/image.png"),
        task.task_id,
        question,
    )
    media = f'<div class="task-media">{image}</div>' if image else ""
    failed = task.failed_checks
    badges = "".join(
        f'<li class="badge badge-destructive">{_ICONS["x"]}'
        f"<span>{escape(_plain_name(name))}</span></li>"
        for name in failed
    )
    if not badges:
        badges = '<li class="badge badge-destructive">Unknown</li>'
    meta = " / ".join((task.family, task.question_type, task.domain))
    heading = f'<h3 class="task-question">{escape(question)}</h3>\n' if question else ""
    return f"""<li class="card task-card rejected-card">
{media}
<div class="task-body">
<p class="task-id"><code>{escape(task.task_id)}</code></p>
{heading}<p class="task-meta">{escape(meta)}</p>
<ul class="task-badges" aria-label="Failed checks">{badges}</ul>
{_reason_alert(task)}
</div>
</li>"""


def _reason_alert(task: "TaskSummary") -> str:
    """Every failed check's reason in one destructive alert."""
    items = []
    for check in task.checks:
        if check.passed:
            continue
        reason = check.reason if check.reason else "No reason recorded."
        items.append(
            f"<li><strong>{escape(_plain_name(check.name))}</strong>: "
            f"{escape(reason)}</li>"
        )
    if not items:
        items.append("<li>No reason recorded.</li>")
    return f"""<div class="alert alert-destructive" role="alert">
{ICONS["alert-triangle"]}
<div class="alert-text"><ul class="reason-list">{"".join(items)}</ul></div>
</div>"""


def _download_form(form: forms.ParsedForm | None) -> str:
    """The ZIP form, reposting the canonical form fields as hidden inputs."""
    hidden = _hidden_fields(form)
    return f"""<form method="post" action="/api/zip">
{hidden}
<button class="btn btn-primary" type="submit">{_ICONS["download"]}<span>Download ZIP</span></button>
<p class="hint">{escape(ZIP_NOTE)}</p>
</form>"""


def _hidden_fields(form: forms.ParsedForm | None) -> str:
    """The canonical form fields as hidden inputs, or nothing without a form."""
    if form is None:
        return ""
    lines = [
        _hidden("seed", str(form.seed)),
        _hidden("charts_per_type", str(form.charts_per_type)),
    ]
    lines.extend(_hidden("chart_types", name) for name in form.chart_types)
    lines.append(_hidden("topic", form.topic))
    lines.extend(_hidden("question_types", name) for name in form.question_types)
    lines.append(_hidden("difficulty", form.difficulty))
    if form.question_in_image:
        lines.append(_hidden("question_in_image", "on"))
    return "\n".join(lines)


def _hidden(name: str, value: str) -> str:
    """One hidden input with both attributes escaped."""
    return f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'


def _checks_strip(task: "TaskSummary") -> str:
    """Seven small marks: one per check, filled for a pass and red for a fail."""
    outcomes = _check_outcomes(task)
    marks = []
    for name in CHECK_NAMES:
        passed = outcomes.get(name, False)
        label = _plain_name(name)
        state = " passed" if passed else " failed"
        mark = "fail" if not passed else ""
        marks.append(
            f'<li class="{mark}"><span class="visually-hidden">'
            f"{escape(label)}{state}</span></li>"
        )
    return "\n".join(marks)


def _check_totals(result: "GenerationResult") -> dict[str, int]:
    """How many attempted tasks passed each of the seven named checks."""
    passed = dict.fromkeys(CHECK_NAMES, 0)
    for task in _all_tasks(result):
        for name, outcome in _check_outcomes(task).items():
            if outcome and name in passed:
                passed[name] += 1
    return passed


def _check_outcomes(task: "TaskSummary") -> dict[str, bool]:
    """Check outcomes by the seven canonical names, mapping the line names."""
    outcomes: dict[str, bool] = {}
    for check in task.checks:
        name = _CHECK_ALIASES.get(check.name, check.name)
        outcomes[name] = bool(check.passed)
    return outcomes


def _plain_name(name: str) -> str:
    """The plain English label for a check, or the raw name when it is unknown."""
    return CHECK_LABELS.get(_CHECK_ALIASES.get(name, name), name)


def _width(part: int, whole: int) -> str:
    """A CSS percentage for a bar, clamped to the 0..100 range."""
    if whole <= 0:
        return "0%"
    percent = min(max(part / whole * 100, 0.0), 100.0)
    return f"{percent:.1f}%"


def _all_tasks(result: "GenerationResult") -> tuple["TaskSummary", ...]:
    """Every attempted task: the accepted ones and the rejected ones."""
    return tuple(result.accepted_tasks) + tuple(result.rejected_tasks)


def _task_payload(
    artifacts: Mapping[str, bytes], folder: str, task_id: str
) -> dict[str, Any]:
    """The task.json payload of one package, or an empty dict when absent."""
    raw = artifacts.get(f"{folder}/{task_id}/task.json")
    if raw is None:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _image_tag(data: bytes | None, task_id: str, question: str) -> str:
    """A PNG data URI in an image tag, or nothing when the artifact is absent.

    The alt text is the task question, so a screen reader hears the same text
    the card shows. A missing question falls back to the task id.
    """
    if not data:
        return ""
    encoded = base64.b64encode(data).decode("ascii")
    alt = question.strip() or f"Chart for {task_id}"
    return (
        f'<img src="data:image/png;base64,{encoded}" '
        f'alt="{escape(alt)}" loading="lazy">'
    )


def _text(value: Any) -> str:
    """A string field, or the empty string for anything else."""
    return value if isinstance(value, str) else ""
