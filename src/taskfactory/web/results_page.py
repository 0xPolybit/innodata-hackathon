"""The self-contained results page: summary, seven checks, cards and rejects.

The page is built from a :class:`~taskfactory.web.generate.GenerationResult`
whose ``artifacts`` hold the run's files. Every image is embedded as a base64
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
from taskfactory.web.results_summary import render_message

if TYPE_CHECKING:  # avoids importing the generator at page-render time
    from taskfactory.web.generate import GenerationResult, TaskSummary

__all__ = ["CHECK_NAMES", "MAX_PAGE_BYTES", "render_results_page"]

# The seven checks, in the order the bar pipeline runs them. The line checks
# carry a family prefix (``5_line_pixels``); _check_outcomes maps them back to
# these names so one table covers every task.
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

MAX_PAGE_BYTES = 4_000_000

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
h3 { font-size: 1rem; margin: 0; }
.lead { margin: 0 0 1.2rem; font-size: 1.05rem; }
.note {
  background: #fff7e6;
  border: 1px solid #e8c98a;
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  margin: 0.7rem 0;
  font-size: 0.95rem;
}
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
thead th { background: #eef2f7; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.02em; }
tbody th { width: 13rem; color: #52606d; font-weight: 600; }
tr:last-child td, tr:last-child th { border-bottom: 0; }
.summary .main-count td, .summary .main-count th { font-size: 1.08rem; color: #1f2933; }
.summary .main-count strong { font-size: 1.35rem; }
.cards { list-style: none; margin: 0; padding: 0; display: grid; gap: 1rem; }
.card {
  background: #ffffff;
  border: 1px solid #d9dee5;
  border-radius: 10px;
  padding: 1rem;
}
.card.rejected { border-left: 4px solid #c0392b; }
.card-head { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: baseline; justify-content: space-between; }
.card img {
  display: block;
  width: 100%;
  max-width: 720px;
  height: auto;
  margin: 0.75rem 0;
  border: 1px solid #e4e8ee;
  border-radius: 6px;
}
.question { margin: 0.4rem 0 0.25rem; }
.answer { margin: 0 0 0.4rem; }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.35rem 1rem; margin: 0.6rem 0; }
.meta dt { color: #52606d; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.02em; }
.meta dd { margin: 0; font-weight: 600; }
.checks-summary { margin: 0.4rem 0 0.3rem; color: #52606d; font-size: 0.9rem; }
.chips { list-style: none; display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0; padding: 0; }
.chip { border-radius: 999px; padding: 0.18rem 0.55rem; font-size: 0.82rem; border: 1px solid; }
.chip.passed { background: #e8f5ec; border-color: #9fd3ad; color: #1e6b33; }
.chip.failed { background: #fdecea; border-color: #e6a7a0; color: #8c1d12; }
.failures { margin: 0.5rem 0 0; padding-left: 1.2rem; }
.download { margin-top: 1.6rem; }
button {
  margin-top: 0.5rem;
  padding: 0.7rem 1.1rem;
  border: 0;
  border-radius: 7px;
  background: #1a5fb4;
  color: #ffffff;
  font: inherit;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
}
button:hover { background: #164d92; }
.foot { margin-top: 1.4rem; font-size: 0.95rem; }
a { color: #1a5fb4; }
code { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 0.9em; }
@media (prefers-color-scheme: dark) {
  body { background: #14171c; color: #e6e9ee; }
  .card, table { background: #1c2027; border-color: #333a45; }
  thead th { background: #232933; }
  th, td { border-color: #333a45; }
  tbody th, .checks-summary, .meta dt { color: #a7b0bd; }
  .summary .main-count td, .summary .main-count th { color: #e6e9ee; }
  .card img { border-color: #333a45; }
  .note { background: #2a2417; border-color: #6b5a32; }
  .chip.passed { background: #173322; border-color: #2f6b44; color: #a7e0b8; }
  .chip.failed { background: #3a1b17; border-color: #7a3a33; color: #f3b8b0; }
  a { color: #7cb0f0; }
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
        return render_message("Result too large", RESULT_TOO_LARGE_MESSAGE)
    return page


def _page(result: "GenerationResult", form: forms.ParsedForm | None) -> str:
    """Build the page text without the size check."""
    summary = _summary_table(result, form)
    checks = _checks_table(result)
    accepted = _accepted_section(result)
    rejected = _rejected_section(result)
    download = _download_section(form)
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
<p class="lead">One generation of chart questions: each task below shows its chart, question, exact answer and all seven checks.</p>

<h2>Run summary</h2>
{summary}

<h2>Seven checks</h2>
{checks}

<h2>Accepted tasks</h2>
{accepted}

{rejected}
{download}

<p class="foot"><a href="/">Back to the form</a></p>
</main>
</body>
</html>
"""


def _summary_table(result: "GenerationResult", form: forms.ParsedForm | None) -> str:
    """The run summary table, with attempted shown as the main count."""
    rows = [
        ("Run id", f"<code>{escape(result.run_id)}</code>"),
        ("Commit", f"<code>{escape(result.commit)}</code>"),
        ("Seed", escape(str(result.seed))),
        (
            "Attempted",
            f'<strong>{escape(str(result.attempted))}</strong> tasks attempted',
        ),
        ("Accepted", escape(str(result.accepted))),
        ("Rejected", escape(str(result.rejected))),
        ("Yield", escape(f"{result.yield_ * 100:.1f}%")),
        ("Elapsed", escape(f"{result.elapsed_seconds:.1f} s")),
    ]
    body = []
    for label, value in rows:
        row_class = ' class="main-count"' if label == "Attempted" else ""
        body.append(f"<tr{row_class}><th>{escape(label)}</th><td>{value}</td></tr>")

    planned_note = _planned_note(result, form)
    return (
        '<table class="summary">\n<tbody>\n'
        + "\n".join(body)
        + "\n</tbody>\n</table>\n"
        + planned_note
    )


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
    return f'<p class="note">{escape(text)}</p>\n'


def _checks_table(result: "GenerationResult") -> str:
    """One row per check name: how many attempted tasks passed it."""
    passed = dict.fromkeys(CHECK_NAMES, 0)
    for task in _all_tasks(result):
        for name, outcome in _check_outcomes(task).items():
            if outcome and name in passed:
                passed[name] += 1

    rows = "".join(
        "<tr>"
        f"<td><code>{escape(name)}</code></td>"
        f"<td>{escape(str(passed[name]))} of {escape(str(result.attempted))} tasks</td>"
        "</tr>"
        for name in CHECK_NAMES
    )
    return (
        "<table>\n"
        "<thead><tr><th>Check</th><th>Passed</th></tr></thead>\n"
        f"<tbody>{rows}</tbody>\n</table>"
    )


def _accepted_section(result: "GenerationResult") -> str:
    """One card per accepted task, in task-id order."""
    tasks = sorted(result.accepted_tasks, key=lambda task: task.task_id)
    if not tasks:
        return '<p class="empty">No tasks were accepted.</p>'
    cards = "\n".join(_accepted_card(task, result.artifacts) for task in tasks)
    return f'<ul class="cards">\n{cards}\n</ul>'


def _rejected_section(result: "GenerationResult") -> str:
    """The rejected cards, or nothing when every task was accepted."""
    tasks = sorted(result.rejected_tasks, key=lambda task: task.task_id)
    if not tasks:
        return ""
    cards = "\n".join(_rejected_card(task, result.artifacts) for task in tasks)
    return f'<h2>Rejected tasks</h2>\n<ul class="cards">\n{cards}\n</ul>'


def _accepted_card(task: "TaskSummary", artifacts: Mapping[str, bytes]) -> str:
    """One accepted task: chart, question, answer, fields and seven chips."""
    payload = _task_payload(artifacts, "tasks", task.task_id)
    question = _text(payload.get("question"))
    answer = _text(payload.get("answer"))
    image = _image_tag(artifacts.get(f"tasks/{task.task_id}/image.png"), task.task_id)
    chips = _chips(task)
    checks = f"{task.passed_checks} of {task.total_checks} checks passed"
    return f"""<li class="card">
<div class="card-head"><h3><code>{escape(task.task_id)}</code></h3></div>
{image}
<p class="question"><strong>Question:</strong> {escape(question)}</p>
<p class="answer"><strong>Exact answer:</strong> {escape(answer)}</p>
<dl class="meta">
<div><dt>Question type</dt><dd>{escape(task.question_type)}</dd></div>
<div><dt>Domain</dt><dd>{escape(task.domain)}</dd></div>
<div><dt>Family</dt><dd>{escape(task.family)}</dd></div>
</dl>
<p class="checks-summary">{escape(checks)}</p>
<ul class="chips">{chips}</ul>
</li>"""


def _rejected_card(task: "TaskSummary", artifacts: Mapping[str, bytes]) -> str:
    """One rejected task: chart, failed check names and their reasons."""
    image = _image_tag(
        artifacts.get(f"rejected/{task.task_id}/image.png"), task.task_id
    )
    failed = task.failed_checks
    names = ", ".join(failed) if failed else "unknown"
    items = []
    for check in task.checks:
        if check.passed:
            continue
        reason = check.reason if check.reason else "no reason recorded"
        items.append(
            "<li>"
            f"<code>{escape(check.name)}</code>: {escape(reason)}"
            "</li>"
        )
    if not items:
        items.append("<li>no reason recorded</li>")
    return f"""<li class="card rejected">
<div class="card-head"><h3><code>{escape(task.task_id)}</code></h3></div>
{image}
<p><strong>Failed checks:</strong> {escape(names)}</p>
<ul class="failures">{"".join(items)}</ul>
</li>"""


def _download_section(form: forms.ParsedForm | None) -> str:
    """The ZIP form, reposting the canonical form fields as hidden inputs."""
    hidden = _hidden_fields(form)
    return f"""<section class="download">
<h2>Download</h2>
<p>The ZIP holds the same pictures and files plus the indices, metrics and run details.</p>
<form method="post" action="/api/zip">
{hidden}
<button type="submit">Download ZIP</button>
</form>
</section>"""


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
    return (
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
    )


def _chips(task: "TaskSummary") -> str:
    """One passed/failed chip for every one of the seven checks."""
    outcomes = _check_outcomes(task)
    chips = []
    for name in CHECK_NAMES:
        passed = outcomes.get(name, False)
        state = "passed" if passed else "failed"
        chips.append(
            f'<li class="chip {state}">{escape(name)} {state}</li>'
        )
    return "".join(chips)


def _check_outcomes(task: "TaskSummary") -> dict[str, bool]:
    """Check outcomes by the seven canonical names, mapping the line names."""
    outcomes: dict[str, bool] = {}
    for check in task.checks:
        name = _CHECK_ALIASES.get(check.name, check.name)
        outcomes[name] = bool(check.passed)
    return outcomes


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


def _image_tag(data: bytes | None, task_id: str) -> str:
    """A PNG data URI in an image tag, or nothing when the artifact is absent."""
    if not data:
        return ""
    encoded = base64.b64encode(data).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{encoded}" '
        f'alt="Chart for {escape(task_id)}">'
    )


def _text(value: Any) -> str:
    """A string field, or the empty string for anything else."""
    return value if isinstance(value, str) else ""
