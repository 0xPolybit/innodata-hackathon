"""Render the single-page TaskFactory form as one self-contained HTML document."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from taskfactory.web.forms import MAX_TASKS, default_task_count, render_form_fields

REPO_URL = "https://github.com/0xPolybit/innodata-hackathon"

# A note on the form, not an error: the container may need to boot before the
# first request is answered. The 60 seconds is the plan's estimate.
COLD_START_MESSAGE = (
    "Starting the demo. The first request can take up to 60 seconds."
)

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
main { max-width: 640px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.8rem; margin: 0 0 0.4rem; }
.intro { margin: 0 0 1.6rem; font-size: 1.05rem; }
form {
  background: #ffffff;
  border: 1px solid #d9dee5;
  border-radius: 10px;
  padding: 1.25rem;
}
.field { border: 0; margin: 0 0 1.15rem; padding: 0; }
legend, label { font-weight: 600; }
legend { margin-bottom: 0.35rem; padding: 0; }
input[type="number"] {
  display: block;
  width: 100%;
  margin-top: 0.3rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid #b8c0cc;
  border-radius: 6px;
  background: #ffffff;
  color: inherit;
  font: inherit;
  font-size: 1rem;
}
.choice {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.3rem 0;
  font-weight: 400;
}
.choice input { width: 1.1rem; height: 1.1rem; margin: 0; }
.hint { margin: 0.35rem 0 0; color: #52606d; font-size: 0.9rem; }
button {
  width: 100%;
  margin-top: 0.4rem;
  padding: 0.75rem 1rem;
  border: 0;
  border-radius: 7px;
  background: #1a5fb4;
  color: #ffffff;
  font: inherit;
  font-size: 1.05rem;
  font-weight: 600;
  cursor: pointer;
}
button:hover { background: #164d92; }
.foot { margin-top: 1.1rem; font-size: 0.95rem; }
a { color: #1a5fb4; }
@media (min-width: 560px) {
  main { padding-top: 2.5rem; }
  fieldset.field:has(.choice) { display: grid; grid-template-columns: 1fr 1fr; }
  fieldset.field:has(.choice) legend,
  fieldset.field:has(.choice) .hint { grid-column: 1 / -1; }
  button { width: auto; min-width: 12rem; }
}
@media (prefers-color-scheme: dark) {
  body { background: #14171c; color: #e6e9ee; }
  form { background: #1c2027; border-color: #333a45; }
  input[type="number"] { background: #14171c; border-color: #4b5563; }
  .hint { color: #a7b0bd; }
  a { color: #7cb0f0; }
}
"""


def render_page(values: Mapping[str, Any] | None = None) -> str:
    """The whole page: intro, form and the link to the sample report."""
    fields = render_form_fields(values)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TaskFactory</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<h1>TaskFactory</h1>
<p class="intro">TaskFactory builds chart questions with exact answers, ready to check and use for benchmarking vision models.</p>
<p class="hint">About {default_task_count()} tasks with these defaults. A choice above {MAX_TASKS} tasks is refused.</p>
<form method="post" action="/api/generate">
{fields}
<button type="submit">Generate</button>
</form>
<p class="foot">{escape(COLD_START_MESSAGE)}</p>
<p class="foot"><a href="{REPO_URL}">Sample report</a></p>
</main>
</body>
</html>
"""
