"""Run one web generation in a throwaway folder and return its summaries.

One call builds the canonical run config, lays out a temporary ``configs/``
root, runs :func:`taskfactory.pipeline.run_pipeline` there with the commit the
site shows, reads the checks back and deletes the whole temporary folder before
returning. Nothing is stored permanently and no image is returned or kept; the
summary carries task ids, families, question types, domains, check outcomes
and the SHA-256 of each ``spec.json``.

Only one generation runs in a process at a time: the process-wide
:data:`GENERATION_LOCK` is taken without blocking, and a second caller gets
:class:`GenerationBusy` straight away.

Failure messages are the ones in docs/IMPLEMENTATION_PLAN.md section 9. An
unexpected exception writes its traceback to stderr and raises
:class:`GenerationFailed` with the generic message, so a traceback is never
shown to the user.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskfactory.web.build_config import build_config
from taskfactory.web.forms import ParsedForm, parse_form

__all__ = [
    "BUSY_MESSAGE",
    "FAILED_MESSAGE",
    "GENERATION_LOCK",
    "OUT_OF_MEMORY_MESSAGE",
    "TIMEOUT_MESSAGE",
    "CheckOutcome",
    "GenerationBusy",
    "GenerationFailed",
    "GenerationResult",
    "TaskSummary",
    "generate",
]

BUSY_MESSAGE = "The generator is busy. Try again in a minute."
FAILED_MESSAGE = "Generation failed. Try again, or choose fewer charts."
OUT_OF_MEMORY_MESSAGE = (
    "The generator ran out of memory. Choose fewer charts and try again."
)
TIMEOUT_MESSAGE = (
    "Generation took longer than the 300 second limit. Choose fewer charts and "
    "try again. The sample report still works."
)

# Process-wide: generation renders with matplotlib and OCR and is not cheap
# enough to run twice at once in the small hosted container.
GENERATION_LOCK = threading.Lock()
_LOCK = GENERATION_LOCK


class GenerationBusy(RuntimeError):
    """A generation is already running in this process."""

    @property
    def message(self) -> str:
        """The message to show, identical to ``str(error)``."""
        return str(self)


class GenerationFailed(RuntimeError):
    """A generation failed with a message that is safe to show to the user."""

    @property
    def message(self) -> str:
        """The message to show, identical to ``str(error)``."""
        return str(self)


@dataclass(frozen=True)
class CheckOutcome:
    """One check of one task, with a short reason when it failed."""

    name: str
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class TaskSummary:
    """One accepted or rejected task, without its image."""

    task_id: str
    family: str
    question_type: str
    domain: str
    checks: tuple[CheckOutcome, ...]
    spec_sha256: str = ""

    @property
    def passed_checks(self) -> int:
        """How many checks passed."""
        return sum(1 for check in self.checks if check.passed)

    @property
    def total_checks(self) -> int:
        """How many checks ran."""
        return len(self.checks)

    @property
    def failed_checks(self) -> tuple[str, ...]:
        """The names of the checks that failed, in run order."""
        return tuple(check.name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class GenerationResult:
    """The counts and per-task summaries of one generation."""

    run_id: str
    commit: str
    seed: int
    attempted: int
    accepted: int
    rejected: int
    yield_: float
    elapsed_seconds: float
    accepted_tasks: tuple[TaskSummary, ...]
    rejected_tasks: tuple[TaskSummary, ...]

    @property
    def yield_rate(self) -> float:
        """The accepted share, under a name that is not a Python keyword."""
        return self.yield_

    @property
    def yield_value(self) -> float:
        """The accepted share, under another name callers may use."""
        return self.yield_

    @property
    def elapsed(self) -> float:
        """The wall-clock seconds the call took."""
        return self.elapsed_seconds


def generate(
    form: ParsedForm | Mapping[str, Any],
    *,
    tesseract_cmd: str | None = None,
    repo_dir: Path | None = None,
) -> GenerationResult:
    """Generate, check and summarise one run, then delete its temporary folder.

    ``form`` is a parsed form, or a mapping that :func:`parse_form` accepts.
    ``tesseract_cmd`` is passed to the OCR check; when it is None the usual
    ``TESSERACT_CMD``, install-path and PATH lookup runs. ``repo_dir`` is the
    project root holding ``configs/``; by default it is the app's repository.

    Raises :class:`GenerationBusy` when another call holds the lock and
    :class:`GenerationFailed` with a section 9 message when the run fails.
    :class:`~taskfactory.web.forms.FormError` is raised before the lock is
    taken when a mapping does not validate.
    """
    if not isinstance(form, ParsedForm):
        form = parse_form(form)

    if not GENERATION_LOCK.acquire(blocking=False):
        raise GenerationBusy(BUSY_MESSAGE)

    started = time.perf_counter()
    temp_root: Path | None = None
    try:
        built = build_config(form)
        commit = _commit_sha()
        root = Path(repo_dir) if repo_dir is not None else _project_root()
        temp_root = Path(tempfile.mkdtemp(prefix="tf-"))
        config_path, out_root = _prepare_layout(
            temp_root, built.toml, built.run_id, root
        )

        with _temporary_environment(temp_root):
            metrics = run_pipeline(
                config_path,
                out_root,
                built.run_id,
                tesseract_cmd=tesseract_cmd,
                repo_dir=root,
                overwrite=True,
                git_sha=commit,
            )

        accepted, rejected = _read_summaries(out_root)
        return GenerationResult(
            run_id=built.run_id,
            commit=commit,
            seed=form.seed,
            attempted=int(metrics.get("generated", len(accepted) + len(rejected))),
            accepted=int(metrics.get("passed", len(accepted))),
            rejected=int(metrics.get("rejected", len(rejected))),
            yield_=float(metrics.get("yield", 0.0)),
            elapsed_seconds=time.perf_counter() - started,
            accepted_tasks=accepted,
            rejected_tasks=rejected,
        )
    except (MemoryError, TimeoutError, OSError) as exc:
        if isinstance(exc, TimeoutError):
            raise GenerationFailed(TIMEOUT_MESSAGE) from exc
        if _is_out_of_memory(exc):
            raise GenerationFailed(OUT_OF_MEMORY_MESSAGE) from exc
        _log_failure()
        raise GenerationFailed(FAILED_MESSAGE) from exc
    except Exception as exc:  # any unexpected failure gets the generic message
        _log_failure()
        raise GenerationFailed(FAILED_MESSAGE) from exc
    finally:
        try:
            if temp_root is not None:
                _remove_tree(temp_root)
        finally:
            GENERATION_LOCK.release()


def run_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Call :func:`taskfactory.pipeline.run_pipeline`, importing it on first use.

    The import stays here so matplotlib loads after ``MPLCONFIGDIR`` points
    inside the temporary folder, and the module-level name gives tests one
    place to replace the whole run.
    """
    from taskfactory.pipeline import run_pipeline as pipeline_run_pipeline

    return pipeline_run_pipeline(*args, **kwargs)


def _prepare_layout(
    temp_root: Path, toml_text: str, run_id: str, repo_dir: Path
) -> tuple[Path, Path]:
    """Write the temp ``configs/`` tree and return the config path and out root."""
    configs_dir = temp_root / "configs"
    runs_dir = configs_dir / "runs"
    runs_dir.mkdir(parents=True)
    shutil.copytree(repo_dir / "configs" / "domains", configs_dir / "domains")
    shutil.copyfile(repo_dir / "configs" / "blocklist.txt", configs_dir / "blocklist.txt")
    config_path = runs_dir / "request.toml"
    config_path.write_bytes(toml_text.encode("utf-8"))

    out_root = temp_root / "out" / run_id
    out_root.mkdir(parents=True)
    return config_path, out_root


@contextmanager
def _temporary_environment(temp_root: Path) -> Iterator[None]:
    """Point matplotlib and tempfile inside ``temp_root`` for the duration."""
    matplotlib_dir = temp_root / "mpl"
    tempfile_dir = temp_root / "tmp"
    matplotlib_dir.mkdir()
    tempfile_dir.mkdir()
    saved: dict[str, str | None] = {}
    for name, value in (
        ("MPLCONFIGDIR", str(matplotlib_dir)),
        ("TMPDIR", str(tempfile_dir)),
    ):
        saved[name] = os.environ.get(name)
        os.environ[name] = value
    # tempfile caches the directory it found on its first call; clearing the
    # cache makes nested temporary files land in this run's folder.
    saved_tempdir = tempfile.tempdir
    tempfile.tempdir = None
    try:
        yield
    finally:
        tempfile.tempdir = saved_tempdir
        for name, previous in saved.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


def _commit_sha() -> str:
    """The commit the site shows, imported from the app rather than copied."""
    from taskfactory.web.app import _commit_sha as app_commit_sha

    return app_commit_sha()


def _project_root() -> Path:
    """The folder holding ``pyproject.toml`` and ``configs/``."""
    from taskfactory.web.app import _repo_root

    return _repo_root()


def _read_summaries(
    out_root: Path,
) -> tuple[tuple[TaskSummary, ...], tuple[TaskSummary, ...]]:
    """Read accepted and rejected summaries, each sorted by package id."""
    return (
        _read_packages(out_root / "tasks"),
        _read_packages(out_root / "rejected"),
    )


def _read_packages(folder: Path) -> tuple[TaskSummary, ...]:
    """Read every package folder under ``folder``; an absent folder is empty."""
    if not folder.is_dir():
        return ()
    packages = sorted(
        (item for item in folder.iterdir() if item.is_dir()),
        key=lambda item: item.name,
    )
    return tuple(_read_package(package) for package in packages)


def _read_package(package: Path) -> TaskSummary:
    """Read the task and validation files of one package folder."""
    task = _read_json(package / "task.json")
    validation = _read_json(package / "validation.json")
    spec_bytes = _read_bytes(package / "spec.json")

    checks: list[CheckOutcome] = []
    raw_checks = validation.get("checks") if isinstance(validation, dict) else None
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict):
                checks.append(_read_check(item))

    task_type = task.get("task_type") if isinstance(task, dict) else None
    family = task.get("family") if isinstance(task, dict) else None
    domain = task.get("domain") if isinstance(task, dict) else None
    return TaskSummary(
        task_id=package.name,
        family=_text(family),
        question_type=_text(task_type),
        domain=_text(domain),
        checks=tuple(checks),
        spec_sha256=(
            hashlib.sha256(spec_bytes).hexdigest() if spec_bytes is not None else ""
        ),
    )


def _read_check(item: Mapping[str, Any]) -> CheckOutcome:
    """One validation record as a check outcome, with a reason when it failed."""
    name = _text(item.get("check"))
    passed = bool(item.get("passed"))
    reason = "" if passed else _reason(item.get("details"))
    return CheckOutcome(name=name, passed=passed, reason=reason)


def _reason(details: Any) -> str:
    """A short, safe reason from a failed check's details."""
    if not isinstance(details, dict):
        return ""
    error = details.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    messages: list[str] = []
    for key in ("failures", "malformed_boxes"):
        value = details.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                message = item.get("message")
                if isinstance(message, str) and message.strip():
                    messages.append(message.strip())
            elif isinstance(item, str) and item.strip():
                messages.append(item.strip())
    if messages:
        return "; ".join(dict.fromkeys(messages))

    rules = details.get("failed_rules")
    if isinstance(rules, list) and rules:
        return "failed rules: " + ", ".join(str(rule) for rule in rules)

    try:
        text = json.dumps(details, sort_keys=True)
    except (TypeError, ValueError):
        return ""
    return text[:240] + ("..." if len(text) > 240 else "")


def _read_json(path: Path) -> Any:
    """Read a JSON file, returning None when it is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_bytes(path: Path) -> bytes | None:
    """Read a file's bytes, or None when it is missing or unreadable."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def _text(value: Any) -> str:
    """A string field, or the empty string for anything else."""
    return value if isinstance(value, str) else ""


def _is_out_of_memory(exc: BaseException) -> bool:
    """True for a Python memory error or an OS out-of-memory error."""
    if isinstance(exc, MemoryError):
        return True
    return isinstance(exc, OSError) and exc.errno == errno.ENOMEM


def _log_failure() -> None:
    """Write the current traceback to stderr; the response never shows it."""
    traceback.print_exc(file=sys.stderr)


def _remove_tree(folder: Path) -> None:
    """Delete ``folder`` and everything in it, retrying briefly on Windows."""
    for attempt in range(3):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 2:
                shutil.rmtree(folder, ignore_errors=True)
                return
            time.sleep(0.05)
