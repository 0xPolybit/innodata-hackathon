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

_MONO = 'ui-monospace, "Cascadia Mono", Consolas, monospace'


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
.breadcrumb { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin: 0 0 1rem; color: var(--muted-foreground); font-size: 0.85rem; }
.breadcrumb a { display: inline-flex; align-items: center; gap: 0.35rem; margin-left: -0.45rem; padding: 0.25rem 0.45rem; border-radius: calc(var(--radius) - 2px); font-weight: 500; }
.breadcrumb a:hover { background: var(--accent); color: var(--foreground); text-decoration: none; }
.breadcrumb-sep { opacity: 0.55; }
.page-head { margin-bottom: 1.5rem; }
.page-head h1 { margin: 0 0 0.4rem; font-size: clamp(1.75rem, 5vw, 2.35rem); line-height: 1.1; letter-spacing: -0.02em; }
.page-lead { margin: 0; max-width: 44rem; color: var(--muted-foreground); }
.stat-tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.75rem; }
.stat-tile { min-width: 0; padding: 0.85rem 1rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 2px); background: var(--background); }
.stat-label { display: flex; align-items: center; gap: 0.4rem; margin: 0; color: var(--muted-foreground); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
.stat-value { margin: 0.3rem 0 0; font-size: 1.7rem; font-weight: 700; line-height: 1.1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.meter { height: 4px; margin-top: 0.55rem; border-radius: 999px; background: var(--muted); overflow: hidden; }
.meter-fill { display: block; height: 100%; border-radius: 999px; background: var(--success); }
.meter-yield .meter-fill { background: var(--primary); }
.run-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.9rem; margin: 0.9rem 0 0; color: var(--muted-foreground); font-size: 0.85rem; }
.meta-label { margin-right: 0.15rem; color: var(--muted-foreground); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
.run-meta code, .commit-details code, .task-title code, .check-code { font-family: __MONO__; }
.run-meta code { font-size: 0.8rem; overflow-wrap: anywhere; }
.commit-details { margin-top: 0.7rem; font-size: 0.85rem; }
.commit-details summary { display: inline-flex; cursor: pointer; border-radius: calc(var(--radius) - 3px); color: var(--muted-foreground); font-size: 0.8rem; font-weight: 600; }
.commit-details summary:hover { color: var(--foreground); }
.commit-details p { margin: 0.4rem 0 0; }
.commit-details code { font-size: 0.8rem; overflow-wrap: anywhere; }
.band-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.65rem; margin-top: 1.1rem; }
.band-actions form { margin: 0; }
.results-section { margin-top: 2rem; }
.section-head h2 { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin: 0 0 0.9rem; font-size: 1.3rem; letter-spacing: -0.01em; }
.check-list { list-style: none; display: grid; gap: 0.95rem; margin: 0; padding: 0; }
.check-row { min-width: 0; }
.check-line { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 0.2rem 0.75rem; }
.check-name { font-size: 0.9rem; font-weight: 600; }
.check-code { color: var(--muted-foreground); font-size: 0.75rem; font-weight: 400; }
.check-score { color: var(--muted-foreground); font-size: 0.8rem; font-variant-numeric: tabular-nums; }
.check-row .meter { margin-top: 0.35rem; }
.checks-card .alert { margin-top: 1rem; }
.task-grid { list-style: none; display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem; margin: 0; padding: 0; }
.task-card { display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.task-media { padding: 0.6rem 0.6rem 0; }
.task-media img { display: block; width: 100%; height: auto; border: 1px solid var(--border); border-radius: calc(var(--radius) - 2px); }
.rejected-card .task-media img { opacity: 0.8; }
.task-body { display: flex; flex: 1; flex-direction: column; gap: 0.55rem; min-width: 0; padding: 0.75rem 1rem 1rem; }
.task-title { margin: 0; color: var(--muted-foreground); font-size: 0.72rem; font-weight: 600; overflow-wrap: anywhere; }
.task-title code { font-size: 0.74rem; }
.task-question { margin: 0; font-size: 0.95rem; line-height: 1.45; overflow-wrap: anywhere; }
.answer-box { display: flex; align-items: flex-start; gap: 0.5rem; padding: 0.55rem 0.7rem; border: 1px solid color-mix(in srgb, var(--success) 28%, var(--border)); border-radius: calc(var(--radius) - 2px); background: color-mix(in srgb, var(--success) 8%, var(--card)); }
.answer-box > .icon { margin-top: 0.15rem; color: color-mix(in srgb, var(--success) 75%, var(--foreground)); }
.answer-label { display: block; color: var(--muted-foreground); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.answer-value { margin: 0.05rem 0 0; font-weight: 600; overflow-wrap: anywhere; }
.task-badges, .check-chips { list-style: none; display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0; padding: 0; }
.task-badges .badge { font-size: 0.7rem; font-weight: 600; }
.task-checks { margin: 0; color: var(--muted-foreground); font-size: 0.78rem; }
.check-chips { gap: 0.28rem; }
.check-chips .badge { gap: 0.25rem; padding: 0.12rem 0.45rem; font-size: 0.68rem; }
.check-chips .icon { width: 0.95em; height: 0.95em; }
.alert-text { min-width: 0; }
.alert-text ul { margin: 0; padding-left: 1rem; }
.reason-list li { overflow-wrap: anywhere; }
.empty-line { display: flex; align-items: flex-start; gap: 0.6rem; margin: 0; color: var(--muted-foreground); font-size: 0.9rem; }
.empty-line .icon { margin-top: 0.15rem; }
.visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (min-width: 720px) {
  .stat-tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (min-width: 1040px) {
  .task-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: no-preference) {
  @keyframes result-card-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }
  .task-card {
    animation: result-card-in 320ms ease-out both;
    transition: transform 160ms ease, box-shadow 160ms ease;
  }
  @media (hover: hover) {
    .task-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 24px rgb(0 0 0 / 0.12);
    }
  }
}
@media (prefers-color-scheme: dark) and (prefers-reduced-motion: no-preference) and (hover: hover) {
  .task-card:hover { box-shadow: 0 10px 24px rgb(0 0 0 / 0.55); }
}
""".replace("__MONO__", _MONO)


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
<p class="page-lead">TaskFactory results for your settings: every chart below carries its question, exact answer and all seven checks.</p>
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
    """The four stat tiles, the run line, the full commit and the two actions."""
    rate = min(max(result.yield_ * 100, 0.0), 100.0)
    rate_text = f"{rate:.1f}"
    elapsed = f"{result.elapsed_seconds:.1f} s"
    return f"""<section class="card results-band" aria-labelledby="summary-heading">
<div class="card-header">
<h2 class="card-title" id="summary-heading">{ICONS["file-text"]}<span>Run summary</span></h2>
<p class="card-description">Totals for this run. The ZIP holds the same charts and files.</p>
</div>
<div class="card-content">
<div class="stat-tiles">
{_stat_tile("list-checks", "Attempted", str(result.attempted))}
{_stat_tile("check-circle", "Accepted", str(result.accepted))}
{_stat_tile("x-circle", "Rejected", str(result.rejected))}
<div class="stat-tile">
<p class="stat-label">{ICONS["gauge"]}<span>Yield</span></p>
<p class="stat-value">{escape(rate_text)}%</p>
<div class="meter meter-yield" role="progressbar" aria-label="Yield" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{escape(rate_text)}"><span class="meter-fill" style="width:{escape(rate_text)}%"></span></div>
</div>
</div>
<p class="run-meta">
<span><span class="meta-label">Run</span> <code>{escape(result.run_id)}</code></span>
<span><span class="meta-label">Seed</span> <strong>{escape(str(result.seed))}</strong></span>
<span><span class="meta-label">Elapsed</span> <strong>{escape(elapsed)}</strong></span>
<span class="badge badge-muted">Commit {escape(result.commit[:7])}</span>
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


def _stat_tile(icon: str, label: str, value: str) -> str:
    """One small labelled total with a shared icon."""
    return f"""<div class="stat-tile">
<p class="stat-label">{ICONS[icon]}<span>{escape(label)}</span></p>
<p class="stat-value">{escape(value)}</p>
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
    for name in CHECK_NAMES:
        count = passed[name]
        label = _plain_name(name)
        rows.append(
            f"""<li class="check-row">
<div class="check-line">
<span class="check-name">{escape(label)} <code class="check-code">{escape(name)}</code></span>
<span class="check-score">{escape(str(count))} of {escape(str(result.attempted))}</span>
</div>
<div class="meter" role="progressbar" aria-label="{escape(label)} passed" aria-valuemin="0" aria-valuemax="{escape(str(result.attempted))}" aria-valuenow="{escape(str(count))}"><span class="meter-fill" style="width:{_width(count, result.attempted)}"></span></div>
</li>"""
        )
    rows_html = "\n".join(rows)
    warning = _accepted_failure_alert(result)
    return f"""<section class="card results-section checks-card" aria-labelledby="checks-heading">
<div class="card-header">
<h2 class="card-title" id="checks-heading">{ICONS["list-checks"]}<span>Seven checks</span></h2>
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
        f'<h2 id="accepted-heading">Accepted tasks <span class="badge badge-success">{escape(str(len(tasks)))}</span></h2>'
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
        f'<h2 id="rejected-heading">Rejected tasks <span class="badge badge-destructive">{escape(str(len(tasks)))}</span></h2>'
        "</div>"
    )
    return (
        '<section class="results-section" aria-labelledby="rejected-heading">\n'
        f'{heading}\n<ul class="task-grid">\n{cards}\n</ul>\n</section>'
    )


def _accepted_card(task: "TaskSummary", artifacts: Mapping[str, bytes]) -> str:
    """One accepted task: image, question, exact answer, badges and seven chips."""
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
    return f"""<li class="card task-card">
{media}
<div class="task-body">
<h3 class="task-title"><code>{escape(task.task_id)}</code></h3>
<p class="task-question">{escape(question)}</p>
<div class="answer-box">
{_ICONS["check"]}
<div>
<span class="answer-label">Exact answer</span>
<p class="answer-value">{escape(answer)}</p>
</div>
</div>
<ul class="task-badges" aria-label="Task attributes">
<li class="badge badge-muted">{escape(task.family)}</li>
<li class="badge badge-muted">{escape(task.question_type)}</li>
<li class="badge badge-muted">{escape(task.domain)}</li>
</ul>
<p class="task-checks">{escape(checks)}</p>
<ul class="check-chips" aria-label="Seven checks">
{_chips(task)}
</ul>
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
    return f"""<li class="card task-card rejected-card">
{media}
<div class="task-body">
<h3 class="task-title"><code>{escape(task.task_id)}</code></h3>
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


def _chips(task: "TaskSummary") -> str:
    """One pass/fail chip for every one of the seven checks."""
    outcomes = _check_outcomes(task)
    chips = []
    for name in CHECK_NAMES:
        passed = outcomes.get(name, False)
        label = _plain_name(name)
        if passed:
            chips.append(
                f'<li class="badge badge-success">{_ICONS["check"]}'
                f'<span>{escape(label)}</span>'
                '<span class="visually-hidden"> passed</span></li>'
            )
        else:
            chips.append(
                f'<li class="badge badge-destructive">{_ICONS["x"]}'
                f'<span>{escape(label)}</span>'
                '<span class="visually-hidden"> failed</span></li>'
            )
    return "\n".join(chips)


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
