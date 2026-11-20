"""Run one run config end to end: sample, render, ask, check and package.

:func:`run_pipeline` loads a run config and its domains, works out which
families and question types this build implements, and then turns every
remaining cell into task packages. Each package is staged, checked and moved
either to ``tasks/`` (every check passed) or to ``rejected/``::

    out_root/
        staging/<package_id>/    built and checked here, moved out before the run ends
        tasks/<package_id>/      every check passed
        rejected/<package_id>/   at least one check failed
        tasks.jsonl              one line per kept task (append_index)
        validation.jsonl         one line per generated package
        metrics.json             run totals, per-check counts, near-duplicates removed,
                                 variation metrics and skipped requests

A candidate is hashed (:func:`taskfactory.variation.phash`) after it is rendered and
before its checks run. If its hash lies within ``checks.near_dup_phash_max`` bits of a
candidate already kept for the same family and task type, its staging folder is deleted
and it is counted in ``metrics["near_duplicates_removed"]``. It is neither a package nor
a check failure, so it appears in none of the folders above.

Only the families in :data:`FAMILIES_IMPLEMENTED` and the question types in
:data:`QUESTION_TYPES_IMPLEMENTED` are generated. Every other request in the
run config is listed in ``metrics["skipped"]`` with the reason. A question type
is asked only of the spec family it belongs to (``series_at_x`` of a line spec,
``value_lookup``, ``extremum``, ``rank_k`` and ``pair_compare`` of a bar spec); a
spec with no task of a requested type, such as a line spec whose top two values
are too close, makes no package for it. ``metrics["per_check"]`` has one entry
for each check that ran.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from taskfactory import variation
from taskfactory.checks_counterfactual import check_6_counterfactual
from taskfactory.checks_layout import (
    check_1_schema,
    check_2_layout,
    run_layout_checks,
)
from taskfactory.checks_line import (
    CHECK_3,
    CHECK_5,
    CHECK_6,
    CHECK_7,
    check_3_line_ambiguity,
    check_5_line_pixels,
    check_6_line_counterfactual,
    check_7_line_redraw,
)
from taskfactory.checks_ocr import check_4_ocr
from taskfactory.checks_pixels import check_5_pixels
from taskfactory.config import (
    ConfigError,
    DomainConfig,
    RunConfig,
    check_blocklist,
    load_blocklist,
    load_domain,
    load_run_config,
)
from taskfactory.package import (
    append_index,
    compute_config_hash,
    get_git_sha,
    write_task_package,
)
from taskfactory.questions import make_questions
from taskfactory.render import render_bar
from taskfactory.render_line import render_line
from taskfactory.sampler import sample_batch

__all__ = [
    "CHECK_NAMES",
    "FAMILIES_IMPLEMENTED",
    "LINE_CHECK_NAMES",
    "QUESTION_TYPES_IMPLEMENTED",
    "run_pipeline",
]

FAMILIES_IMPLEMENTED = ("bar", "line")
# Every question type questions.py writes. rank_k and pair_compare are bar questions
# that run through the bar check list: check 1 and check 5 read their rank or names
# from the question text, and check 6 alters the categories the answer depends on.
QUESTION_TYPES_IMPLEMENTED = ("value_lookup", "extremum", "series_at_x", "rank_k", "pair_compare")

# The checks of a bar package, in the order _run_checks runs them.
CHECK_NAMES = (
    "1_schema",
    "2_layout",
    "3_ambiguity",
    "7_redraw",
    "4_ocr",
    "5_pixels",
    "6_counterfactual",
)

# The checks of a line package, in the order _run_checks runs them.
LINE_CHECK_NAMES = (
    "1_schema",
    "2_layout",
    CHECK_3,
    "4_ocr",
    CHECK_5,
    CHECK_6,
    CHECK_7,
)

_DEFAULT_MIN_MARGIN = 0.05
_DEFAULT_MIN_FONT_PX = 9
_DEFAULT_NEAR_DUP_PHASH_MAX = 6

_STAGING = "staging"
_TASKS = "tasks"
_REJECTED = "rejected"
_TASK_INDEX = "tasks.jsonl"
_VALIDATION_INDEX = "validation.jsonl"
_METRICS = "metrics.json"
_OUTPUT_FILES = (_TASK_INDEX, _VALIDATION_INDEX, _METRICS)
_VALIDATION = "validation.json"
_RENDER_NAME = "render.png"
_PACKAGE_IMAGE = "image.png"


class _Plan(NamedTuple):
    """What a run generates, and what it skips with a reason."""

    cells: list[tuple[DomainConfig, list[str]]]  # each domain with the families to run
    question_types: list[str]
    skipped: list[str]


def run_pipeline(
    run_config_path: Path,
    out_root: Path,
    run_id: str,
    tesseract_cmd: str | None = None,
    repo_dir: Path = Path("."),
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate and check every implemented task of one run config.

    The config folder's parent is the configs root: ``configs/runs/demo.toml``
    loads ``configs/domains/<name>.toml`` and ``configs/blocklist.txt``.
    ``tesseract_cmd`` is passed to the OCR check; ``repo_dir`` is where the git
    sha is read from.

    Returns the metrics dict that is also written to ``out_root/metrics.json``.
    ``skipped`` holds one entry per distinct reason.

    Raises :class:`ValueError` when ``run_id`` is empty, and
    :class:`~taskfactory.config.ConfigError` (a ``ValueError``) when the run
    config or a domain is invalid or a domain title or category holds a
    blocklisted term. Raises :class:`ValueError` too when ``out_root/tasks`` or
    ``out_root/rejected`` already holds packages and ``overwrite`` is False. With
    ``overwrite`` True those folders, ``staging`` and the three summary files
    are deleted first. Nothing is deleted when the config is refused.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id: expected a non-empty string")
    run_config_path = Path(run_config_path)
    out_root = Path(out_root)

    run_cfg = load_run_config(run_config_path)
    configs_dir = run_config_path.resolve().parent.parent
    plan = _plan(run_cfg, _load_domains(configs_dir, run_cfg.domains))
    near_dup_max = _near_dup_max(run_cfg)  # read before anything is deleted

    _prepare_out_root(out_root, overwrite)
    config_hash = compute_config_hash(run_config_path)
    git_sha = get_git_sha(repo_dir)
    min_margin = run_cfg.checks.get("ambiguity_min_margin", _DEFAULT_MIN_MARGIN)
    min_font_px = run_cfg.checks.get("min_font_px", _DEFAULT_MIN_FONT_PX)

    staging_root = out_root / _STAGING
    tasks_root = out_root / _TASKS
    rejected_root = out_root / _REJECTED
    tasks_root.mkdir(parents=True, exist_ok=True)
    rejected_root.mkdir(parents=True, exist_ok=True)

    per_check: dict[str, dict[str, int]] = {}
    records: list[dict[str, Any]] = []
    candidates: list[variation.Candidate] = []
    kept_hashes: dict[tuple[str, str], list[int]] = {}  # (family, task_type) -> kept pHashes
    near_duplicates = 0
    for domain, families in plan.cells:
        for family in families:
            for spec in sample_batch(run_cfg, domain, family, run_cfg.tasks_per_cell):
                by_type = {
                    task["task_type"]: task
                    for task in make_questions(spec, min_margin=min_margin)
                }
                for question_type in plan.question_types:
                    task = by_type.get(question_type)
                    if task is None:
                        # Not a question of this family, or too close to ask: no package.
                        continue
                    staged = _stage_package(staging_root, spec, task, config_hash, git_sha)
                    picture_hash = variation.phash(staged / _PACKAGE_IMAGE)
                    kept = kept_hashes.setdefault((family, task["task_type"]), [])
                    if _is_near_duplicate(picture_hash, kept, near_dup_max):
                        # Removed before the checks: not a package and not a check failure.
                        _remove_tree(staged)
                        near_duplicates += 1
                        continue
                    kept.append(picture_hash)

                    results = _run_checks(
                        staged, family, min_margin, min_font_px, tesseract_cmd
                    )
                    passed = _write_validation(staged, results)

                    for result in results:
                        counts = per_check.setdefault(result["check"], {"fail": 0, "pass": 0})
                        counts["pass" if result["passed"] else "fail"] += 1
                    records.append(
                        {
                            "failed_checks": [r["check"] for r in results if not r["passed"]],
                            "package_id": staged.name,
                            "passed": passed,
                        }
                    )
                    candidates.append(
                        variation.Candidate(
                            package_id=staged.name,
                            family=family,
                            domain=spec["domain"],
                            task_type=task["task_type"],
                            phash=picture_hash,
                            structure=variation.structure_signature(spec),
                            reasoning_steps=task["reasoning_steps"],
                            passed=passed,
                        )
                    )

                    if passed:
                        _move_package(staged, tasks_root)
                        append_index(
                            out_root,
                            staged.name,
                            task["task_type"],
                            task["answer"],
                            spec["family"],
                            spec["domain"],
                            spec["index"],
                            question=task["question"],
                            answer_category=task["answer_category"],
                        )
                    else:
                        _move_package(staged, rejected_root)

    _remove_tree(staging_root)
    generated = len(records)
    passed_count = sum(1 for record in records if record["passed"])
    metrics: dict[str, Any] = {
        "config_hash": config_hash,
        "generated": generated,
        "git_sha": git_sha,
        "near_duplicates_removed": near_duplicates,
        "passed": passed_count,
        "per_check": per_check,
        "rejected": generated - passed_count,
        "run_id": run_id,
        "skipped": plan.skipped,
        "variation": variation.variation_metrics(candidates, near_duplicates),
        "yield": round(passed_count / generated, 4) if generated else 0.0,
    }

    validation_lines = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    _write_text(out_root / _VALIDATION_INDEX, validation_lines)
    _write_text(out_root / _METRICS, _json_text(metrics))
    return metrics


def _load_domains(configs_dir: Path, names: list[str]) -> list[DomainConfig]:
    """Load each named domain and refuse one whose title or categories hold a blocklisted term."""
    blocklist = load_blocklist(configs_dir / "blocklist.txt")
    domains: list[DomainConfig] = []
    for name in dict.fromkeys(names):
        domain = load_domain(configs_dir / "domains" / f"{name}.toml")
        check_blocklist([domain.title, *domain.categories], blocklist)
        domains.append(domain)
    return domains


def _plan(run_cfg: RunConfig, domains: list[DomainConfig]) -> _Plan:
    """Intersect the requested families and question types with what is implemented."""
    skipped: list[str] = []
    families = list(dict.fromkeys(run_cfg.families))
    for family in families:
        if family not in FAMILIES_IMPLEMENTED:
            _add_reason(skipped, f"family {family} not implemented yet")

    question_types: list[str] = []
    for question_type in dict.fromkeys(run_cfg.question_types):
        if question_type in QUESTION_TYPES_IMPLEMENTED:
            question_types.append(question_type)
        else:
            _add_reason(skipped, f"question type {question_type} not implemented yet")

    implemented = [family for family in families if family in FAMILIES_IMPLEMENTED]
    cells: list[tuple[DomainConfig, list[str]]] = []
    for domain in domains:
        domain_families: list[str] = []
        for family in implemented:
            if family in domain.families:
                domain_families.append(family)
            else:
                _add_reason(skipped, f"domain {domain.name} does not enable family {family}")
        cells.append((domain, domain_families))
    return _Plan(cells=cells, question_types=question_types, skipped=skipped)


def _add_reason(reasons: list[str], reason: str) -> None:
    """Append ``reason`` once, keeping the order in which reasons were found."""
    if reason not in reasons:
        reasons.append(reason)


def _near_dup_max(run_cfg: RunConfig) -> int:
    """The largest pHash Hamming distance at which two candidates count as near-duplicates."""
    limit = run_cfg.checks.get("near_dup_phash_max", _DEFAULT_NEAR_DUP_PHASH_MAX)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ConfigError(
            f"checks.near_dup_phash_max: expected a non-negative integer, got {limit!r}"
        )
    return limit


def _is_near_duplicate(picture_hash: int, kept: Sequence[int], limit: int) -> bool:
    """True when ``picture_hash`` lies within ``limit`` bits of a hash already kept."""
    return any(variation.hamming(picture_hash, other) <= limit for other in kept)


def _prepare_out_root(out_root: Path, overwrite: bool) -> None:
    """Refuse to add packages to an earlier run unless ``overwrite``; with it, clear them.

    Without ``overwrite`` the run stops when ``tasks/`` or ``rejected/`` already
    holds packages. Either way a ``staging/`` folder left by an interrupted run
    is removed, and so is a ``tasks.jsonl`` whose packages are gone.
    """
    if overwrite:
        for name in (_STAGING, _TASKS, _REJECTED):
            _remove_tree(out_root / name)
        for name in _OUTPUT_FILES:
            (out_root / name).unlink(missing_ok=True)
        return

    occupied = [name for name in (_TASKS, _REJECTED) if _has_entries(out_root / name)]
    if occupied:
        raise ValueError(
            f"{out_root} already holds packages in {' and '.join(occupied)}; "
            "rerun with --overwrite to replace them"
        )
    _remove_tree(out_root / _STAGING)
    (out_root / _TASK_INDEX).unlink(missing_ok=True)


def _stage_package(
    staging_root: Path,
    spec: dict[str, Any],
    task: dict[str, Any],
    config_hash: str,
    git_sha: str,
) -> Path:
    """Render ``spec`` for ``task`` and stage its package at ``staging_root/<package_id>``.

    The question is printed in the picture only when the spec asks for it, so
    the caption box carries the task question exactly as the render drew it.
    ``write_task_package`` nests every package under ``<run_root>/tasks``, so it
    writes under ``staging_root`` and the package is then moved up one level.
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    render_png = staging_root / _RENDER_NAME
    question = task["question"] if spec["question_in_image"] else None
    try:
        text_boxes = _render(spec, render_png, question)
        written = write_task_package(
            staging_root, spec, task, render_png, text_boxes, config_hash, git_sha
        )
    finally:
        render_png.unlink(missing_ok=True)
    staged = staging_root / written.name
    written.rename(staged)
    return staged


def _render(spec: dict[str, Any], png_path: Path, question: str | None) -> list[dict[str, Any]]:
    """Draw ``spec`` with the renderer of its family and return the text boxes it drew."""
    if spec["family"] == "bar":
        return render_bar(spec, png_path, question=question)
    if spec["family"] == "line":
        return render_line(spec, png_path, question=question)
    raise ValueError(f"no renderer for family {spec['family']!r}")


def _run_checks(
    package: Path,
    family: str,
    min_margin: float,
    min_font_px: int,
    tesseract_cmd: str | None,
) -> list[dict[str, Any]]:
    """Run the checks of ``family`` on one staged package and return their results in order.

    This is the only place that names each family's checks. Bar packages run
    checks 1 to 7 in their bar form; line packages run the line form of checks
    3, 5, 6 and 7, with checks 1, 2 and 4 shared.
    """
    if family == "bar":
        results = run_layout_checks(package, min_margin=min_margin, min_font_px=min_font_px)
        results.append(check_4_ocr(package, tesseract_cmd))
        results.append(check_5_pixels(package))
        results.append(check_6_counterfactual(package))
        return results
    if family == "line":
        return [
            check_1_schema(package),
            check_2_layout(package, min_font_px=min_font_px),
            check_3_line_ambiguity(package, min_margin=min_margin),
            check_4_ocr(package, tesseract_cmd),
            check_5_line_pixels(package),
            check_6_line_counterfactual(package),
            check_7_line_redraw(package),
        ]
    raise ValueError(f"no checks for family {family!r}")


def _write_validation(package: Path, results: list[dict[str, Any]]) -> bool:
    """Write ``validation.json`` into a staged package; return True when every check passed."""
    passed = all(result["passed"] for result in results)
    payload = {"checks": results, "package_id": package.name, "passed": passed}
    _write_text(package / _VALIDATION, _json_text(payload))
    return passed


def _move_package(staged: Path, destination_root: Path) -> None:
    """Move a finished package out of staging. Never merge it into an existing folder."""
    destination = destination_root / staged.name
    if destination.exists():
        raise FileExistsError(f"cannot move {staged.name}: {destination} already exists")
    staged.rename(destination)


def _has_entries(folder: Path) -> bool:
    """True when ``folder`` exists and holds at least one entry."""
    return folder.is_dir() and any(folder.iterdir())


def _remove_tree(folder: Path) -> None:
    """Delete ``folder`` and everything in it when it exists."""
    if folder.exists():
        shutil.rmtree(folder)


def _json_text(value: Any) -> str:
    """Sorted-key, two-space-indented JSON with a trailing newline."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 bytes without newline translation, so output is byte-stable on Windows."""
    path.write_bytes(text.encode("utf-8"))
