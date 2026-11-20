"""Static HTML report for one pool run and one benchmark run.

:func:`build_report` writes ``index.html`` and one ``examples/<task type>.png`` per task type
into an output folder. It reads the files a run leaves behind and runs nothing:

- ``pool/metrics.json``: run id, git sha, config hash, funnel, per-check counts, variation
- ``pool/validation.jsonl``: one line per generated package, with the checks it failed
- ``pool/tasks/<package>/``: task.json, validation.json and image.png, for the examples
- ``eval/benchmark_metrics.json``: per-model counts, accuracy and error labels
- ``eval/items.jsonl`` and ``eval/items.summary.json``: the frozen eval set
- ``eval/results/<model>.jsonl``: per-item lines, read only for a date a line records
- an optional self-test JSON, as saved from :func:`taskfactory.selftest.run_selftest`

The page has one embedded stylesheet, no script and no link to anything outside its folder.
Every value read from a file is escaped with :func:`html.escape`. Rates are rounded to four
places and shown as percentages with one decimal. It imports only the standard library and
:func:`taskfactory.llm.safe_model_id`, so it runs without OpenCV, Pillow or matplotlib.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from taskfactory.llm import safe_model_id

__all__ = ["build_report"]

TITLE = "Synthetic chart and visual-reasoning benchmark (MVP)"
NA = "n/a"

HEADINGS = {
    "run": "1. Run and scope",
    "funnel": "2. Pool funnel",
    "checks": "3. Checks",
    "variation": "4. Variation",
    "selftest": "5. Self-test",
    "benchmark": "6. Benchmark",
    "examples": "7. Examples",
    "limits": "8. Limits",
}

# benchmark_metrics.json only holds models whose role is "evaluated" (benchmark.run_eval).
ROLE = "evaluated"
TASK_TYPE_ORDER = ("value_lookup", "extremum", "rank_k", "pair_compare", "series_at_x")
ERROR_LABEL_ORDER = ("empty", "refusal_or_long", "wrong_entity", "wrong_value", "other")
DEFECT_ORDER = ("wrong_answer", "hidden_label", "forced_tie", "mismatched_bar", "absent_entity")
DEFECT_DESCRIPTIONS = {
    "wrong_answer": "task.json names a different answer",
    "hidden_label": "a white box covers the printed text the answer depends on",
    "forced_tie": "the second-largest bar is raised to equal the largest",
    "mismatched_bar": "the shortest bar is painted white",
    "absent_entity": "the question names a category the chart does not have",
}

# The check names as the checks_*.py modules and pipeline.py write them.
SHARED_CHECKS = ("1_schema", "2_layout", "4_ocr")
BAR_CHECKS = ("3_ambiguity", "5_pixels", "6_counterfactual", "7_redraw")
LINE_CHECKS = ("3_line_ambiguity", "5_line_pixels", "6_line_counterfactual", "7_line_redraw")

# MVP targets from docs/PLAN.md section 4.8. They are goals; the report prints the actual values.
TARGET_CELL_COVERAGE = 0.90
TARGET_TYPE_ENTROPY = 0.90
TARGET_STRUCTURAL_DIFFERENCE = 0.95
TARGET_DEPTH_BINS = 3
DEPTH_BIN_PERCENT = 15
TARGET_SPREAD_POINTS = 20

LIMITS = (
    "The benchmark is an easy set: the three free models score 95 to 100 percent, so it does not separate them.",
    "The free OpenRouter model is capped at 50 requests a day, so its run is partial.",
    "One pool task was rejected by the counterfactual check because the redrawn label layout confused the pixel reader.",
    "The human audit has not been done.",
    "The three models are the best free-tier multimodal models available on the build day, not frontier models.",
    "Floor plans are out of the MVP.",
)

_DATE_FIELDS = ("created_at", "date", "produced_at")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f5f5f1;
  --panel: #ffffff;
  --text: #1c1c1a;
  --muted: #5c5c56;
  --rule: #d5d5ce;
  --track: #e4e4de;
  --fill: #2a6a8c;
  --met: #2d6a36;
  --unmet: #9a4a00;
  --code-bg: #eeeee8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #151614;
    --panel: #1d1e1b;
    --text: #ecebe6;
    --muted: #a7a7a0;
    --rule: #3b3c37;
    --track: #33342f;
    --fill: #6cb0d5;
    --met: #86c98f;
    --unmet: #f0b463;
    --code-bg: #2a2b27;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  overflow-wrap: anywhere;
}
main { max-width: 60rem; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 8px 0 6px; }
h2 { font-size: 1.2rem; margin: 0 0 8px; }
h3 { font-size: 1.02rem; margin: 18px 0 6px; }
p, li { max-width: 72ch; }
section {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: 10px;
  padding: 12px 16px;
  margin: 14px 0;
}
.lede { color: var(--muted); }
.small { color: var(--muted); font-size: 0.9rem; }
nav ul { display: flex; flex-wrap: wrap; gap: 6px 14px; list-style: none; margin: 10px 0 0; padding: 0; }
nav a { color: var(--fill); }
dl.facts { display: grid; grid-template-columns: minmax(8rem, max-content) 1fr; gap: 6px 14px; margin: 8px 0; }
dl.facts dt { color: var(--muted); }
dl.facts dd { margin: 0; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 10px; font-size: 0.95rem; }
th, td { text-align: left; vertical-align: top; padding: 6px 8px; border-bottom: 1px solid var(--rule); }
th { color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88em;
  background: var(--code-bg);
  padding: 0 4px;
  border-radius: 4px;
  overflow-wrap: anywhere;
}
.met { color: var(--met); font-weight: 600; }
.unmet { color: var(--unmet); font-weight: 600; }
.bar { height: 10px; min-width: 60px; background: var(--track); border-radius: 5px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--fill); }
figure { margin: 12px 0 18px; }
figure img {
  display: block;
  max-width: 100%;
  height: auto;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: #ffffff;
}
figcaption p { margin: 4px 0; }
@media (max-width: 40rem) {
  table.stack thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  table.stack, table.stack tbody, table.stack tr, table.stack td { display: block; width: 100%; }
  table.stack tr { border-bottom: 1px solid var(--rule); padding: 6px 0; }
  table.stack td { border: 0; padding: 2px 0; text-align: left; }
  table.stack td::before { content: attr(data-label); display: block; color: var(--muted); font-size: 0.85rem; }
  dl.facts { grid-template-columns: 1fr; }
}
"""


class _Html(str):
    """Markup this module wrote itself. Every other value is escaped on the way into the page."""


@dataclass(frozen=True)
class _Example:
    """The first passing package of one task type, by package name."""

    task_type: str
    package: str
    image: Path
    question: str
    answer: str
    checks: tuple[tuple[str, bool], ...] | None  # None when the package has no validation.json


def build_report(
    pool_dir: Path,
    eval_dir: Path,
    out_dir: Path,
    selftest_json: Path | None = None,
) -> Path:
    """Write ``out_dir/index.html`` and ``out_dir/examples/*.png``, and return the path of the page.

    ``pool_dir`` is the folder a ``tf run`` wrote, with metrics.json, validation.jsonl and tasks/.
    ``eval_dir`` is the folder a ``tf eval`` wrote, with benchmark_metrics.json and items.jsonl.
    ``selftest_json`` is a result saved from :func:`taskfactory.selftest.run_selftest`. Without
    it, the self-test section says that the self-test has not run yet and nothing else.

    A required file that is missing raises FileNotFoundError. A file that is not JSON raises
    ValueError. The examples are copied from ``pool_dir/tasks``, and only from packages that
    passed; for each task type the first such package by name is used.
    """
    pool = Path(pool_dir)
    evals = Path(eval_dir)
    out = Path(out_dir)

    pool_metrics = _load_json(_required(pool / "metrics.json"))
    passing, rejected = _read_validation(_required(pool / "validation.jsonl"))
    bench = _load_json(_required(evals / "benchmark_metrics.json"))
    items_summary_path = evals / "items.summary.json"
    items_summary = _load_json(items_summary_path) if items_summary_path.is_file() else None
    items_path = evals / "items.jsonl"
    digest_on_disk = hashlib.sha256(items_path.read_bytes()).hexdigest() if items_path.is_file() else None
    dates = _result_dates(evals, list(_models(bench)))
    selftest = _load_json(_required(Path(selftest_json))) if selftest_json is not None else None
    examples = _pick_examples(pool, passing)

    body = "".join(
        [
            _run_section(pool_metrics, bench),
            _funnel_section(pool_metrics, rejected),
            _checks_section(pool_metrics),
            _variation_section(pool_metrics, bench),
            _selftest_section(selftest),
            _benchmark_section(bench, items_summary, digest_on_disk, dates),
            _examples_section(examples),
            _limits_section(),
        ]
    )
    page = _document(_navigation() + body)

    out.mkdir(parents=True, exist_ok=True)
    _write_examples(out, examples)
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


# --- reading the run files ------------------------------------------------------------------


def _required(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    return path


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc.msg}") from None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {number} is not valid JSON: {exc.msg}") from None
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {number} is not a JSON object")
        rows.append(row)
    return rows


def _read_validation(path: Path) -> tuple[dict[str, bool], list[tuple[str, tuple[str, ...]]]]:
    """The pass flag of each package, and the packages that failed with the checks they failed."""
    passing: dict[str, bool] = {}
    rejected: list[tuple[str, tuple[str, ...]]] = []
    for row in _read_jsonl(path):
        package = str(row.get("package_id", ""))
        passed = bool(row.get("passed"))
        passing[package] = passed
        if not passed:
            failed = row.get("failed_checks") or []
            rejected.append((package, tuple(str(name) for name in failed)))
    return passing, rejected


def _models(bench: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    models = bench.get("models")
    if not isinstance(models, Mapping):
        return {}
    return {str(model_id): entry if isinstance(entry, Mapping) else {} for model_id, entry in models.items()}


def _pick_examples(pool: Path, passing: Mapping[str, bool]) -> dict[str, _Example]:
    """For each task type, the first passing package by name, with its picture and checks."""
    chosen: dict[str, _Example] = {}
    tasks = pool / "tasks"
    if not tasks.is_dir():
        return chosen
    for folder in sorted((path for path in tasks.iterdir() if path.is_dir()), key=lambda path: path.name):
        if not passing.get(folder.name, False):
            continue
        task_file = folder / "task.json"
        image = folder / "image.png"
        if not (task_file.is_file() and image.is_file()):
            continue
        task = _load_json(task_file)
        task_type = task.get("task_type") if isinstance(task, dict) else None
        if not isinstance(task_type, str) or task_type in chosen:
            continue
        chosen[task_type] = _Example(
            task_type=task_type,
            package=folder.name,
            image=image,
            question=str(task.get("question", "")),
            answer=str(task.get("answer", "")),
            checks=_checks_of(folder),
        )
    return chosen


def _checks_of(folder: Path) -> tuple[tuple[str, bool], ...] | None:
    validation = folder / "validation.json"
    if not validation.is_file():
        return None
    data = _load_json(validation)
    rows = data.get("checks", []) if isinstance(data, dict) else []
    return tuple(
        (str(row.get("check")), bool(row.get("passed")))
        for row in rows
        if isinstance(row, dict)
    )


def _result_dates(eval_dir: Path, model_ids: Sequence[str]) -> dict[str, str]:
    """The date range each model's results file records, or blank. Nothing is invented."""
    dates: dict[str, str] = {}
    for model_id in model_ids:
        try:
            name = safe_model_id(model_id)
        except ValueError:
            dates[model_id] = ""
            continue
        dates[model_id] = _recorded_dates(eval_dir / "results" / f"{name}.jsonl")
    return dates


def _recorded_dates(path: Path) -> str:
    if not path.is_file():
        return ""
    days: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        for field in _DATE_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and _ISO_DATE.match(value):
                days.append(value[:10])
                break
    if not days:
        return ""
    first, last = min(days), max(days)
    return first if first == last else f"{first} to {last}"


def _write_examples(out: Path, examples: Mapping[str, _Example]) -> None:
    folder = out / "examples"
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("*.png"):
        stale.unlink()
    for example in examples.values():
        shutil.copyfile(example.image, folder / f"{_stem(example.task_type)}.png")


def _stem(task_type: str) -> str:
    """A file-name-safe form of a task type."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", task_type)


# --- values and markup ----------------------------------------------------------------------


def _text(value: object) -> str:
    """Escape a value for HTML text or a quoted attribute. None is empty. Module markup passes through."""
    if isinstance(value, _Html):
        return str(value)
    return html.escape("" if value is None else str(value), quote=True)


def _code(value: object) -> _Html:
    return _Html(f"<code>{_text(NA if value is None else value)}</code>")


def _or_na(value: object) -> object:
    return NA if value is None else value


def _rounded(value: object) -> Decimal | None:
    """A number rounded to four places, as a Decimal. None when the value is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(round(float(value), 4)))


def _one_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _pct(value: object) -> str:
    """A rate as a percentage with one decimal, after rounding to four places."""
    rate = _rounded(value)
    if rate is None:
        return NA
    return f"{_one_decimal(rate * 100)}%"


def _share_pct(part: int, whole: int) -> str:
    """A count as a percentage of a whole, rounded once to one decimal. "n/a" when the whole is zero."""
    if not whole:
        return NA
    return f"{_one_decimal(Decimal(part) * 100 / Decimal(whole))}%"


def _points(gap: Decimal | None) -> str:
    return NA if gap is None else f"{_one_decimal(gap)} points"


def _dec4(value: object) -> str:
    rate = _rounded(value)
    return NA if rate is None else f"{rate:.4f}"


def _count(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return NA
    return f"{value:,}"


def _at_least(value: object, target: float) -> bool | None:
    rate = _rounded(value)
    if rate is None:
        return None
    return rate >= Decimal(str(target))


def _verdict(met: bool | None) -> object:
    if met is None:
        return NA
    if met:
        return _Html('<span class="met">met</span>')
    return _Html('<span class="unmet">not met</span>')


def _bar(fraction: object, label: str) -> _Html:
    rate = _rounded(fraction)
    if rate is None:
        return _Html(_text(NA))
    width = min(Decimal(100), max(Decimal(0), rate * 100))
    return _Html(
        f'<div class="bar" role="img" aria-label="{_text(label)}">'
        f'<span style="width:{_one_decimal(width)}%"></span></div>'
    )


def _align(index: int, numeric: Sequence[int]) -> str:
    return ' class="num"' if index in numeric else ""


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]], *, numeric: Sequence[int] = ()) -> str:
    head = "".join(
        f'<th scope="col"{_align(index, numeric)}>{_text(label)}</th>' for index, label in enumerate(headers)
    )
    body_rows: list[str] = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            label = _text(headers[index]) if index < len(headers) else ""
            cells.append(f'<td data-label="{label}"{_align(index, numeric)}>{_text(value)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body = "".join(body_rows)
    return (
        f'<table class="stack"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    )


def _facts(rows: Sequence[tuple[str, object]]) -> str:
    items = "".join(f"<dt>{_text(label)}</dt><dd>{_text(value)}</dd>" for label, value in rows)
    return f'<dl class="facts">{items}</dl>'


def _codes(names: Sequence[str]) -> str:
    return ", ".join(str(_code(name)) for name in names)


def _section(key: str, body: str) -> str:
    return f'<section id="{key}"><h2>{_text(HEADINGS[key])}</h2>{body}</section>'


def _navigation() -> str:
    links = "".join(f'<li><a href="#{key}">{_text(HEADINGS[key])}</a></li>' for key in HEADINGS)
    return (
        '<header><h1>' + _text(TITLE) + '</h1>'
        '<p class="lede">Static report, generated from the run files. Service cost: 0.</p>'
        '<nav aria-label="Sections"><ul>' + links + "</ul></nav></header>"
    )


def _document(body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_text(TITLE)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<main>{body}</main>\n"
        "</body>\n"
        "</html>\n"
    )


def _ordered(keys: Iterable[str], order: Sequence[str]) -> list[str]:
    present = set(keys)
    return [key for key in order if key in present] + sorted(present - set(order))


# --- section 1: run and scope ---------------------------------------------------------------


def _run_section(pool: Mapping[str, Any], bench: Mapping[str, Any]) -> str:
    body = (
        "<p>This report summarises one pool run (its generated, checked and packaged tasks), "
        "the self-test of its checks, and one benchmark run on a frozen eval set. "
        "It is not a leaderboard, not a human-audited dataset, and not evidence about frontier models.</p>"
        + _facts(
            [
                ("Pool run id", _or_na(pool.get("run_id"))),
                ("Git sha", _code(pool.get("git_sha"))),
                ("Config hash", _code(pool.get("config_hash"))),
                ("Service cost", "0 (free tiers only)"),
                (
                    "Benchmark run id",
                    "none recorded; the benchmark is identified by its eval set SHA-256 in section 6",
                ),
            ]
        )
    )
    return _section("run", body)


# --- section 2: pool funnel -----------------------------------------------------------------


def _funnel_section(pool: Mapping[str, Any], rejected: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    rows = [
        ["Generated", _count(pool.get("generated"))],
        ["Passed every check", _count(pool.get("passed"))],
        ["Rejected by a check", _count(pool.get("rejected"))],
        [
            "Near-duplicates removed before packaging (not counted in generated)",
            _count(pool.get("near_duplicates_removed")),
        ],
        ["Yield (passed / generated)", _pct(pool.get("yield"))],
    ]
    parts = [_table(["Stage", "Count"], rows, numeric=(1,))]

    skipped = pool.get("skipped") or []
    if skipped:
        items = "".join(f"<li>{_text(reason)}</li>" for reason in skipped)
        parts.append(f"<p>Skipped reasons:</p><ul>{items}</ul>")
    else:
        parts.append("<p>Skipped reasons: none.</p>")

    if rejected:
        items = []
        for package, checks in rejected:
            failed = ", ".join(checks) or "no check recorded"
            items.append(f"<li>{_code(package)} failed {_text(failed)}</li>")
        parts.append("<p>Rejected packages:</p><ul>" + "".join(items) + "</ul>")
    else:
        parts.append("<p>No package was rejected.</p>")
    return _section("funnel", "".join(parts))


# --- section 3: checks ----------------------------------------------------------------------


def _check_version(name: str) -> str:
    if name in SHARED_CHECKS:
        return "both families"
    if name in LINE_CHECKS or "line" in name.split("_"):
        return "line version"
    if name in BAR_CHECKS:
        return "bar version"
    return "not classified"


def _checks_section(pool: Mapping[str, Any]) -> str:
    per_check = pool.get("per_check") or {}
    rows = []
    for name in sorted(per_check):
        entry = per_check.get(name) or {}
        rows.append([name, _check_version(name), _count(entry.get("pass")), _count(entry.get("fail"))])
    if rows:
        table = _table(["Check", "Version", "Passed", "Failed"], rows, numeric=(2, 3))
    else:
        table = "<p>No per-check counts are recorded.</p>"
    legend = (
        '<p class="small">Bar version: ' + _codes(BAR_CHECKS) + ". Line version: " + _codes(LINE_CHECKS)
        + ". Both families: " + _codes(SHARED_CHECKS)
        + ". A bar package runs the bar names, a line package runs the line names.</p>"
    )
    return _section("checks", table + legend)


# --- section 4: variation -------------------------------------------------------------------


def _depth_bins(histogram: Mapping[str, Any]) -> list[tuple[int, int]]:
    bins: list[tuple[int, int]] = []
    for key, count in histogram.items():
        try:
            bins.append((int(key), int(count)))
        except (TypeError, ValueError):
            continue
    return sorted(bins)


def _spread(by_type: Mapping[str, Any]) -> Decimal | None:
    """The gap in points between the highest and lowest accuracy across task types, over attempted items."""
    rates: list[Decimal] = []
    for group in by_type.values():
        if not isinstance(group, Mapping):
            continue
        attempted = group.get("n_items_attempted")
        rate = _rounded(group.get("accuracy"))
        if rate is not None and isinstance(attempted, int) and attempted > 0:
            rates.append(rate)
    if len(rates) < 2:
        return None
    return (max(rates) - min(rates)) * 100


def _widest_spread(bench: Mapping[str, Any]) -> tuple[Decimal | None, str | None]:
    best: Decimal | None = None
    best_model: str | None = None
    for model_id, entry in _models(bench).items():
        gap = _spread(entry.get("accuracy_by_task_type") or {})
        if gap is not None and (best is None or gap > best):
            best, best_model = gap, model_id
    return best, best_model


def _variation_section(pool: Mapping[str, Any], bench: Mapping[str, Any]) -> str:
    variation = pool.get("variation") or {}
    bins = _depth_bins(variation.get("reasoning_depth_histogram") or {})
    total = sum(count for _, count in bins)
    biggest = max((count for _, count in bins), default=0)
    bins_at_target = sum(1 for _, count in bins if total and count * 100 >= DEPTH_BIN_PERCENT * total)
    spread, spread_model = _widest_spread(bench)
    removed = variation.get("near_duplicates_removed", pool.get("near_duplicates_removed"))
    spread_text = _points(spread) if spread_model is None else f"{_points(spread)} ({spread_model})"

    metrics = [
        [
            "Cell coverage",
            "share of feasible family x domain x question-type cells with at least 5 valid tasks",
            _pct(variation.get("cell_coverage")),
            ">= 90%",
            _verdict(_at_least(variation.get("cell_coverage"), TARGET_CELL_COVERAGE)),
        ],
        [
            "Question-type balance",
            "normalised Shannon entropy of the question types",
            _dec4(variation.get("question_type_entropy")),
            ">= 0.9",
            _verdict(_at_least(variation.get("question_type_entropy"), TARGET_TYPE_ENTROPY)),
        ],
        [
            "Structural difference",
            "share of nearest-neighbour pairs (by pHash) differing in at least one structural knob",
            _pct(variation.get("structural_difference")),
            ">= 95%",
            _verdict(_at_least(variation.get("structural_difference"), TARGET_STRUCTURAL_DIFFERENCE)),
        ],
        [
            "Near-duplicates removed",
            "pHash distance <= 6 or identical rounded spec, removed before packaging",
            _count(removed),
            "0 left after the filter; count reported",
            "count reported",
        ],
        [
            "Reasoning depth",
            "reasoning-step bins holding at least 15% of the packages",
            f"{bins_at_target} of {len(bins)} bins" if bins else NA,
            ">= 3 bins with at least 15% each",
            _verdict(bins_at_target >= TARGET_DEPTH_BINS if bins else None),
        ],
        [
            "Difficulty spread",
            "widest gap in accuracy between question types, over the evaluated models",
            spread_text,
            ">= 20 points",
            _verdict(None if spread is None else spread >= TARGET_SPREAD_POINTS),
        ],
    ]
    parts = [
        "<p>Targets are goals from the plan. The values shown are the ones this run produced.</p>",
        _table(["Metric", "What it measures", "Actual", "MVP target", "Status"], metrics),
    ]

    histogram_rows = []
    for step, count in bins:
        histogram_rows.append(
            [
                str(step),
                _count(count),
                _share_pct(count, total),
                _bar(count / biggest if biggest else None, f"{count} packages"),
            ]
        )
    parts.append("<h3>Reasoning depth</h3>")
    parts.append(
        _table(["Reasoning steps", "Packages", "Share", "Bar (scaled to the largest bin)"], histogram_rows, numeric=(1, 2))
        if bins
        else "<p>No reasoning-depth histogram is recorded.</p>"
    )
    parts.append(
        f'<p class="small">Histogram total: {_text(_count(total) if bins else NA)} packages. '
        "Each share is the bin's count divided by that total.</p>"
    )
    return _section("variation", "".join(parts))


# --- section 5: self-test -------------------------------------------------------------------


def _selftest_section(data: Mapping[str, Any] | None) -> str:
    if data is None:
        return _section("selftest", "<p>Self-test not run yet</p>")

    parts = [
        f"<p>Clean packages: {_text(_count(data.get('clean_passed')))} of "
        f"{_text(_count(data.get('clean_total')))} passed every check before any defect was injected. "
        "Only those packages were injected into.</p>",
        '<p class="small">Full checks run every check of the family, including the redraw check. '
        "Content only leaves the redraw check out. Both columns use the same injected copies.</p>",
    ]
    if data.get("content_only") is True:
        parts.append('<p class="small">This run used the content checks alone, so both column groups hold the same counts.</p>')

    selection = data.get("selection")
    if isinstance(selection, Mapping):
        parts.append(
            f'<p class="small">Sample: {_text(selection.get("sample_size"))} of '
            f"{_text(selection.get('pool_packages'))} pool packages. Rule: {_text(selection.get('rule'))}.</p>"
        )

    per_class = data.get("per_class") or {}
    content = data.get("content_only_per_class") or {}
    rows = []
    for name in _ordered(per_class.keys(), DEFECT_ORDER):
        full = per_class.get(name) or {}
        only = content.get(name) or {}
        rows.append(
            [
                name,
                DEFECT_DESCRIPTIONS.get(name, ""),
                _count(full.get("injected")),
                _count(full.get("caught")),
                _pct(full.get("catch_rate")),
                _count(only.get("caught")),
                _pct(only.get("catch_rate")),
            ]
        )
    if rows:
        parts.append(
            _table(
                [
                    "Defect class",
                    "What the defect does",
                    "Injected",
                    "Caught, full checks",
                    "Catch rate, full checks",
                    "Caught, content only",
                    "Catch rate, content only",
                ],
                rows,
                numeric=(2, 3, 4, 5, 6),
            )
        )
    else:
        parts.append("<p>No defect class is recorded.</p>")

    details = data.get("details") or []
    missed = [item for item in details if isinstance(item, Mapping) and not item.get("caught")]
    if missed:
        items = "".join(
            f"<li>{_code(item.get('class'))} on {_code(item.get('package'))}: {_text(item.get('description'))}</li>"
            for item in missed
        )
        parts.append(f"<p>Injected defects that the full checks did not catch:</p><ul>{items}</ul>")
    else:
        parts.append("<p>Every injected defect was caught by the full checks.</p>")
    return _section("selftest", "".join(parts))


# --- section 6: benchmark -------------------------------------------------------------------


def _eval_set_rows(
    bench: Mapping[str, Any],
    items_summary: Mapping[str, Any] | None,
    digest_on_disk: str | None,
) -> list[tuple[str, object]]:
    recorded = bench.get("eval_set_sha256")
    rows: list[tuple[str, object]] = [
        ("Eval set SHA-256", _code(recorded)),
        ("Items in the set", _count(bench.get("eval_set_items"))),
    ]
    if digest_on_disk is None:
        rows.append(("items.jsonl on disk", "not found"))
    elif digest_on_disk == recorded:
        rows.append(("items.jsonl on disk", "matches the recorded SHA-256"))
    else:
        rows.append(("items.jsonl on disk", "differs from the recorded SHA-256; the set has changed since the run"))
    if items_summary is not None:
        rows.append(("Pool packages the set was drawn from", _count(items_summary.get("pool_packages"))))
        seed = items_summary.get("seed")
        rows.append(("Sampling seed", NA if seed is None else str(seed)))
        if items_summary.get("sha256") != recorded:
            rows.append(("items.summary.json", "records a different SHA-256"))
    return rows


def _strata_table(strata: Mapping[str, Any]) -> str:
    rows = [
        [name, _count(entry.get("available")), _count(entry.get("selected"))]
        for name, entry in sorted(strata.items())
        if isinstance(entry, Mapping)
    ]
    return _table(["Stratum (family/question type)", "Available", "Selected"], rows, numeric=(1, 2))


def _group_table(title: str, groups: Mapping[str, Any]) -> str:
    rows = []
    for name in sorted(groups):
        group = groups.get(name) or {}
        rate = group.get("accuracy")
        rows.append(
            [
                name,
                f"{_count(group.get('n_correct'))} / {_count(group.get('n_items_attempted'))}",
                _pct(rate),
                _bar(rate, f"{name}: {_pct(rate)}"),
            ]
        )
    if not rows:
        return "<p>Not recorded.</p>"
    return _table([title, "Correct / attempted", "Accuracy", "Accuracy bar"], rows, numeric=(1, 2))


def _labels_table(counts: Mapping[str, Any]) -> str:
    rows = [[label, _count(counts.get(label, 0))] for label in _ordered(counts.keys(), ERROR_LABEL_ORDER)]
    if not rows:
        return "<p>Not recorded.</p>"
    return _table(["Error label (wrong answers only)", "Count"], rows, numeric=(1,))


def _benchmark_section(
    bench: Mapping[str, Any],
    items_summary: Mapping[str, Any] | None,
    digest_on_disk: str | None,
    dates: Mapping[str, str],
) -> str:
    models = _models(bench)
    parts = [
        "<h3>Eval set</h3>",
        _facts(_eval_set_rows(bench, items_summary, digest_on_disk)),
    ]
    if items_summary is not None and isinstance(items_summary.get("strata"), Mapping):
        parts.append(_strata_table(items_summary["strata"]))

    summary_rows = []
    for model_id in sorted(models):
        entry = models[model_id]
        summary_rows.append(
            [
                model_id,
                _or_na(entry.get("provider")),
                ROLE,
                _pct(entry.get("accuracy")),
                f"{_count(entry.get('n_correct'))} / {_count(entry.get('n_items_attempted'))}",
                _count(entry.get("n_items_not_attempted")),
                entry.get("stopped_reason") or "none",
                _count(entry.get("provider_error_count")),
                dates.get(model_id, ""),
            ]
        )
    if summary_rows:
        parts.append(
            "<h3>Models</h3>"
            + _table(
                [
                    "Model ID",
                    "Provider",
                    "Role",
                    "Accuracy (attempted items)",
                    "Correct / attempted",
                    "Not attempted",
                    "Stopped reason",
                    "Provider errors",
                    "Results dated",
                ],
                summary_rows,
                numeric=(3, 4, 5, 7),
            )
        )
        parts.append(
            '<p class="small">Accuracy is correct answers divided by items attempted; items not attempted '
            "are left out of both counts. The results-date column is blank where a model's results file "
            "records no date.</p>"
        )
    else:
        parts.append("<p>No model results are recorded.</p>")

    for index, model_id in enumerate(sorted(models), start=1):
        entry = models[model_id]
        by_type = entry.get("accuracy_by_task_type") or {}
        gap = _spread(by_type)
        parts.append(f'<h3 id="model-{index}">{_text(model_id)}</h3>')
        parts.append("<h4>Accuracy by family</h4>" + _group_table("Family", entry.get("accuracy_by_family") or {}))
        parts.append("<h4>Accuracy by task type</h4>" + _group_table("Task type", by_type))
        parts.append("<h4>Error labels</h4>" + _labels_table(entry.get("error_label_counts") or {}))
        parts.append(
            f'<p class="small">Difficulty spread across task types, over attempted items: {_text(_points(gap))}.</p>'
        )
    return _section("benchmark", "".join(parts))


# --- section 7: examples --------------------------------------------------------------------


def _checks_text(checks: tuple[tuple[str, bool], ...] | None) -> str:
    if checks is None:
        return "not recorded"
    passed = [name for name, ok in checks if ok]
    return f"{len(passed)} of {len(checks)} checks passed ({', '.join(passed)})"


def _examples_section(examples: Mapping[str, _Example]) -> str:
    if not examples:
        return _section("examples", "<p>No passing package was found in the pool, so there are no examples.</p>")
    figures = []
    for task_type in _ordered(examples.keys(), TASK_TYPE_ORDER):
        example = examples[task_type]
        source = f"examples/{_stem(task_type)}.png"
        alt = _text(f"Example image for {task_type}: {example.question}")
        figures.append(
            "<figure>"
            f'<a href="{_text(source)}"><img src="{_text(source)}" alt="{alt}" loading="lazy"></a>'
            "<figcaption>"
            f"<p><strong>{_text(task_type)}</strong>, package {_code(example.package)}</p>"
            f"<p>Question: {_text(example.question)}</p>"
            f"<p>Answer: {_text(example.answer)}</p>"
            f"<p>Checks: {_text(_checks_text(example.checks))}</p>"
            "</figcaption>"
            "</figure>"
        )
    return _section("examples", "".join(figures))


# --- section 8: limits ----------------------------------------------------------------------


def _limits_section() -> str:
    items = "".join(f"<li>{_text(item)}</li>" for item in LIMITS)
    return _section("limits", f"<ul>{items}</ul>")
