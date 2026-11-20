"""Self-contained HTML for the generation result and its error pages.

Every value that reaches the page is escaped. The pages load no script and no
external resource, so they render on a phone with no network access beyond the
one response. No image is shown yet; the accepted and rejected tasks are plain
tables.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from taskfactory.web.theme import ICONS, page_shell

if TYPE_CHECKING:  # avoids importing the generator at page-render time
    from taskfactory.web.generate import GenerationResult, TaskSummary

__all__ = ["render_message", "render_results"]

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f6f7f9;
  color: #1f2933;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.45;
}
main { max-width: 960px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.7rem; margin: 0 0 0.3rem; }
h2 { font-size: 1.2rem; margin: 1.6rem 0 0.5rem; }
.lead { margin: 0 0 1.2rem; font-size: 1.05rem; }
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0.5rem 1rem;
  margin: 0;
  padding: 1rem;
  background: #ffffff;
  border: 1px solid #d9dee5;
  border-radius: 10px;
}
.summary div { margin: 0; }
.summary dt { color: #52606d; font-size: 0.85rem; }
.summary dd { margin: 0.1rem 0 0; font-weight: 600; }
table {
  width: 100%;
  border-collapse: collapse;
  background: #ffffff;
  border: 1px solid #d9dee5;
  border-radius: 10px;
  overflow: hidden;
  font-size: 0.92rem;
}
th, td {
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid #e4e8ee;
  text-align: left;
  vertical-align: top;
}
th { background: #eef2f7; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.02em; }
tr:last-child td { border-bottom: 0; }
.empty { color: #52606d; padding: 0.7rem 0.6rem; }
.foot { margin-top: 1.4rem; font-size: 0.95rem; }
a { color: #1a5fb4; }
code { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 0.9em; }
.notice {
  background: #ffffff;
  border: 1px solid #d9dee5;
  border-radius: 10px;
  padding: 1.25rem;
}
.notice p { margin: 0 0 0.8rem; }
@media (prefers-color-scheme: dark) {
  body { background: #14171c; color: #e6e9ee; }
  .summary, table, .notice { background: #1c2027; border-color: #333a45; }
  th { background: #232933; }
  th, td { border-color: #333a45; }
  .summary dt, .empty { color: #a7b0bd; }
  a { color: #7cb0f0; }
}
"""


def render_results(result: "GenerationResult") -> str:
    """The whole success page: totals, accepted tasks and rejected tasks."""
    accepted_rows = "".join(_accepted_row(task) for task in result.accepted_tasks)
    if not accepted_rows:
        accepted_rows = '<tr><td class="empty" colspan="5">No tasks were accepted.</td></tr>'

    rejected_rows = "".join(_rejected_row(task) for task in result.rejected_tasks)
    if not rejected_rows:
        rejected_rows = '<tr><td class="empty" colspan="6">No tasks were rejected.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TaskFactory results</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<h1>TaskFactory results</h1>
<p class="lead">These tasks were generated and checked. The images and the ZIP come next.</p>
<dl class="summary">
  <div><dt>Run ID</dt><dd><code>{escape(result.run_id)}</code></dd></div>
  <div><dt>Commit</dt><dd><code>{escape(result.commit)}</code></dd></div>
  <div><dt>Seed</dt><dd>{escape(str(result.seed))}</dd></div>
  <div><dt>Attempted</dt><dd>{escape(str(result.attempted))}</dd></div>
  <div><dt>Accepted</dt><dd>{escape(str(result.accepted))}</dd></div>
  <div><dt>Rejected</dt><dd>{escape(str(result.rejected))}</dd></div>
  <div><dt>Yield</dt><dd>{escape(f"{result.yield_:.4f}")}</dd></div>
  <div><dt>Time</dt><dd>{escape(f"{result.elapsed_seconds:.1f} s")}</dd></div>
</dl>

<h2>Accepted tasks</h2>
<table>
<thead><tr><th>Task</th><th>Family</th><th>Question type</th><th>Domain</th><th>Checks</th></tr></thead>
<tbody>{accepted_rows}</tbody>
</table>

<h2>Rejected tasks</h2>
<table>
<thead><tr><th>Task</th><th>Family</th><th>Question type</th><th>Domain</th><th>Failed checks</th><th>Reason</th></tr></thead>
<tbody>{rejected_rows}</tbody>
</table>

<p class="foot"><a href="/">Back to the form</a></p>
</main>
</body>
</html>
"""


def render_message(title: str, message: str) -> str:
    """A designed page for a validation, busy or generation failure.

    The words are the caller's, unchanged and escaped. A busy generator and a
    spent compute allowance are warnings; every other failure is destructive.
    """
    warning = title in {"Generator busy", "Compute limit reached"}
    kind = "warning" if warning else "destructive"
    icon = "info" if warning else "alert-triangle"
    body = f"""<div class="card error-card delay-1">
<div class="card-header">
<h1 class="card-title">{escape(title)}</h1>
</div>
<div class="card-content">
<div class="alert alert-{kind}" role="alert">{ICONS[icon]}<p>{escape(message)}</p></div>
<div class="error-actions">
<a class="btn btn-outline" href="/">{ICONS["arrow-left"]}<span>Back to the form</span></a>
</div>
</div>
</div>"""
    return page_shell(title, body)


def _accepted_row(task: "TaskSummary") -> str:
    """One accepted task as a table row."""
    checks = f"{task.passed_checks} of {task.total_checks} checks passed"
    return (
        "<tr>"
        f"<td><code>{escape(task.task_id)}</code></td>"
        f"<td>{escape(task.family)}</td>"
        f"<td>{escape(task.question_type)}</td>"
        f"<td>{escape(task.domain)}</td>"
        f"<td>{escape(checks)}</td>"
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
        f"<td><code>{escape(task.task_id)}</code></td>"
        f"<td>{escape(task.family)}</td>"
        f"<td>{escape(task.question_type)}</td>"
        f"<td>{escape(task.domain)}</td>"
        f"<td>{escape(failed_names)}</td>"
        f"<td>{reason_html}</td>"
        "</tr>"
    )
