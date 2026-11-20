"""Self-contained HTML for the error pages and the table-only summary fallback.

Every value that reaches the page is escaped. The pages load no script and no
external resource, so they render on a phone with no network access beyond the
one response.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from taskfactory.web import forms
from taskfactory.web.theme import ICONS, page_shell

if TYPE_CHECKING:  # avoids importing the generator at page-render time
    from taskfactory.web.generate import GenerationResult, TaskSummary

__all__ = ["back_href", "form_query", "render_message", "render_results"]


def form_query(form: forms.ParsedForm) -> str:
    """The query string that pre-fills the form with ``form``'s choices."""
    pairs: list[tuple[str, str]] = [
        ("seed", str(form.seed)),
        ("charts_per_type", str(form.charts_per_type)),
    ]
    pairs.extend(("chart_types", name) for name in form.chart_types)
    pairs.append(("topic", form.topic))
    pairs.extend(("question_types", name) for name in form.question_types)
    pairs.append(("difficulty", form.difficulty))
    pairs.append(("question_in_image", "on" if form.question_in_image else "off"))
    return urlencode(pairs)


def back_href(form: forms.ParsedForm | None = None) -> str:
    """The form page carrying ``form``'s choices, or plain ``/`` without a form."""
    if form is None:
        return "/"
    return f"/?{form_query(form)}"


_STYLE = """
.summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; margin: 0; }
.summary div { min-width: 0; padding: 12px 0; border-bottom: 1px solid var(--border); }
.summary dt { color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; }
.summary dd { margin: 2px 0 0; font-size: 15px; font-weight: 500; overflow-wrap: anywhere; }
.summary dd code, td code { font-family: var(--mono); font-size: 12px; }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-control); overflow: hidden; font-size: 14px; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
th { color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; font-weight: 400; }
tr:last-child td { border-bottom: 0; }
td code { overflow-wrap: anywhere; }
.empty { color: var(--muted-foreground); }
.results-section { margin-top: 40px; }
.section-head { margin: 0 0 12px; }
.section-head h2 { display: flex; align-items: baseline; gap: 8px; margin: 0; font-size: 20px; font-weight: 500; letter-spacing: -0.01em; }
.count { color: var(--muted-foreground); font-family: var(--mono); font-size: 12px; font-weight: 400; }
.foot { margin-top: 24px; }
@media (min-width: 720px) {
  .summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  thead { display: none; }
  table, tbody, tr, td { display: block; }
  table { border: 0; background: transparent; }
  tr { padding: 12px 0; border-bottom: 1px solid var(--border); }
  td { display: grid; grid-template-columns: 7rem 1fr; gap: 8px; padding: 4px 0; border: 0; }
  td::before { content: attr(data-label); color: var(--muted-foreground); font-family: var(--mono); font-size: 11px; }
}
"""


def render_results(result: "GenerationResult") -> str:
    """The summary fallback: totals, accepted tasks and rejected tasks."""
    accepted_rows = "".join(_accepted_row(task) for task in result.accepted_tasks)
    if not accepted_rows:
        accepted_rows = '<tr><td class="empty" colspan="5">No tasks were accepted.</td></tr>'

    rejected_rows = "".join(_rejected_row(task) for task in result.rejected_tasks)
    if not rejected_rows:
        rejected_rows = '<tr><td class="empty" colspan="6">No tasks were rejected.</td></tr>'

    body = f"""<style>{_STYLE}</style>
<section class="hero">
<h1>Results</h1>
<p>TaskFactory results for this run. Accepted and rejected tasks are listed below.</p>
</section>

<section class="card" aria-labelledby="summary-heading">
<div class="card-header">
<h2 class="card-title" id="summary-heading">Run summary</h2>
</div>
<div class="card-content">
<dl class="summary">
  <div><dt>Run ID</dt><dd><code>{escape(result.run_id)}</code></dd></div>
  <div><dt>Commit</dt><dd><code>{escape(result.commit)}</code></dd></div>
  <div><dt>Seed</dt><dd><code>{escape(str(result.seed))}</code></dd></div>
  <div><dt>Attempted</dt><dd>{escape(str(result.attempted))}</dd></div>
  <div><dt>Accepted</dt><dd>{escape(str(result.accepted))}</dd></div>
  <div><dt>Rejected</dt><dd>{escape(str(result.rejected))}</dd></div>
  <div><dt>Yield</dt><dd>{escape(f"{result.yield_ * 100:.1f}%")}</dd></div>
  <div><dt>Time</dt><dd>{escape(f"{result.elapsed_seconds:.1f} s")}</dd></div>
</dl>
</div>
</section>

<section class="results-section" aria-labelledby="accepted-heading">
<div class="section-head">
<h2 id="accepted-heading">Accepted tasks <span class="count">{escape(str(result.accepted))}</span></h2>
</div>
<table>
<thead><tr><th>Task</th><th>Family</th><th>Question type</th><th>Domain</th><th>Checks</th></tr></thead>
<tbody>{accepted_rows}</tbody>
</table>
</section>

<section class="results-section" aria-labelledby="rejected-heading">
<div class="section-head">
<h2 id="rejected-heading">Rejected tasks <span class="count">{escape(str(result.rejected))}</span></h2>
</div>
<table>
<thead><tr><th>Task</th><th>Family</th><th>Question type</th><th>Domain</th><th>Failed checks</th><th>Reason</th></tr></thead>
<tbody>{rejected_rows}</tbody>
</table>
</section>

<p class="foot"><a class="btn btn-outline" href="/">{ICONS["arrow-left"]}<span>Back to the form</span></a></p>"""
    return page_shell("Results", body)


def render_message(
    title: str,
    message: str,
    form: forms.ParsedForm | None = None,
) -> str:
    """A designed page for a validation, busy or generation failure.

    The words are the caller's, unchanged and escaped. A busy generator and a
    spent compute allowance are warnings; every other failure is destructive.
    ``form`` carries the settings a retry should start from; without one the
    Back link is plain ``/``.
    """
    warning = title in {"Generator busy", "Compute limit reached"}
    kind = "warning" if warning else "destructive"
    icon = "info" if warning else "alert-triangle"
    href = back_href(form)
    body = f"""<div class="error-card page-enter delay-1">
<h1 class="error-title">{escape(title)}</h1>
<div class="alert alert-{kind}" role="alert">{ICONS[icon]}<p>{escape(message)}</p></div>
<div class="error-actions">
<a class="btn btn-outline" href="{href}">{ICONS["arrow-left"]}<span>Back to the form</span></a>
</div>
</div>"""
    return page_shell(title, body)


def _accepted_row(task: "TaskSummary") -> str:
    """One accepted task as a table row."""
    checks = f"{task.passed_checks} of {task.total_checks} checks passed"
    return (
        "<tr>"
        f'<td data-label="Task"><code>{escape(task.task_id)}</code></td>'
        f'<td data-label="Family">{escape(task.family)}</td>'
        f'<td data-label="Question type">{escape(task.question_type)}</td>'
        f'<td data-label="Domain">{escape(task.domain)}</td>'
        f'<td data-label="Checks">{escape(checks)}</td>'
        "</tr>"
    )


def _rejected_row(task: "TaskSummary") -> str:
    """One rejected task as a table row, with every failed check and its reason."""
    failed = task.failed_checks
    failed_names = ", ".join(failed) if failed else "unknown"
    reasons: list[str] = []
    for check in task.checks:
        if check.passed:
            continue
        reasons.append(f"{check.name}: {check.reason}" if check.reason else check.name)
    if not reasons:
        reasons.append("no reason recorded")
    reason_html = "<br>".join(escape(reason) for reason in reasons)
    return (
        "<tr>"
        f'<td data-label="Task"><code>{escape(task.task_id)}</code></td>'
        f'<td data-label="Family">{escape(task.family)}</td>'
        f'<td data-label="Question type">{escape(task.question_type)}</td>'
        f'<td data-label="Domain">{escape(task.domain)}</td>'
        f'<td data-label="Failed checks">{escape(failed_names)}</td>'
        f'<td data-label="Reason">{reason_html}</td>'
        "</tr>"
    )
