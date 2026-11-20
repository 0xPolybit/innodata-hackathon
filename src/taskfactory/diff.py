"""Compare two pipeline runs package by package, file by file and line by line.

:func:`compare_runs` reads two run folders as :func:`taskfactory.pipeline.run_pipeline` writes
them and reports the accepted packages in ``tasks/`` that were added, removed or changed:

- a package is matched by its folder name;
- a package is *changed* when a file under it has a different SHA-256 in the two runs, or when a
  file exists in only one of them. Every file is compared, ``manifest.json`` included. Only the
  bytes are read, so an ``image.png`` is never decoded.

``tasks.jsonl`` is compared by content: the non-blank lines of each run are counted, and the runs
match when both hold the same lines in any order. A file present in only one run counts all of its
lines as differing.

``rejected/`` is compared by folder name and file hash in the same way, but only its package counts
are reported. Its differences appear in the summary line and do not change the exit code.

:class:`RunDiff` holds the result. :meth:`RunDiff.to_json` is the object ``tf diff`` prints, and
:attr:`RunDiff.exit_code` is 0 when the accepted packages and ``tasks.jsonl`` match, 1 otherwise.
A run folder that is missing, or lacks its ``tasks/`` or ``rejected/`` folder, raises
:class:`FileNotFoundError`.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

__all__ = ["NAME_LIMIT", "RunDiff", "compare_runs"]

NAME_LIMIT = 50

_TASKS = "tasks"
_REJECTED = "rejected"
_TASK_INDEX = "tasks.jsonl"
_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class RunDiff:
    """What two runs hold and how their accepted packages and index differ."""

    tasks_a: tuple[str, ...]
    tasks_b: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    changed_files_total: int
    rejected_a: int
    rejected_b: int
    rejected_differing: int
    index_lines_differing: int

    @property
    def identical(self) -> bool:
        """True when the accepted packages and ``tasks.jsonl`` match."""
        return not (self.added or self.removed or self.changed or self.index_lines_differing)

    @property
    def exit_code(self) -> int:
        """0 when the accepted packages and ``tasks.jsonl`` match, 1 otherwise."""
        return 0 if self.identical else 1

    def to_json(self) -> dict[str, Any]:
        """The object printed on stdout: name lists capped at :data:`NAME_LIMIT`, and counts."""
        return {
            "tasks_a": _name_list(self.tasks_a),
            "tasks_b": _name_list(self.tasks_b),
            "added": _name_list(self.added),
            "removed": _name_list(self.removed),
            "changed": _name_list(self.changed),
            "rejected_a": self.rejected_a,
            "rejected_b": self.rejected_b,
            "changed_files_total": self.changed_files_total,
        }

    def summary(self) -> str:
        """The one-line summary printed on stderr."""
        verdict = "match" if self.identical else "differ"
        return (
            f"tf diff: tasks {len(self.tasks_a)} vs {len(self.tasks_b)}, "
            f"added {len(self.added)}, removed {len(self.removed)}, "
            f"changed {len(self.changed)} ({self.changed_files_total} files), "
            f"tasks.jsonl lines differing {self.index_lines_differing}, "
            f"rejected {self.rejected_a} vs {self.rejected_b} "
            f"({self.rejected_differing} differing): {verdict}"
        )


class _Packages(NamedTuple):
    """The package folders of two runs and how they differ."""

    names_a: tuple[str, ...]
    names_b: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    changed_files: int


def compare_runs(run_a: str | Path, run_b: str | Path) -> RunDiff:
    """Compare two run folders and return what differs between them.

    Raises :class:`FileNotFoundError` when a run folder, or its ``tasks`` or ``rejected``
    folder, does not exist.
    """
    run_a = Path(run_a)
    run_b = Path(run_b)
    for run in (run_a, run_b):
        for folder in (run, run / _TASKS, run / _REJECTED):
            if not folder.is_dir():
                raise FileNotFoundError(f"folder not found: {folder}")

    accepted = _compare_packages(run_a / _TASKS, run_b / _TASKS)
    rejected = _compare_packages(run_a / _REJECTED, run_b / _REJECTED)
    return RunDiff(
        tasks_a=accepted.names_a,
        tasks_b=accepted.names_b,
        added=accepted.added,
        removed=accepted.removed,
        changed=accepted.changed,
        changed_files_total=accepted.changed_files,
        rejected_a=len(rejected.names_a),
        rejected_b=len(rejected.names_b),
        rejected_differing=len(rejected.added) + len(rejected.removed) + len(rejected.changed),
        index_lines_differing=_differing_index_lines(run_a / _TASK_INDEX, run_b / _TASK_INDEX),
    )


def _compare_packages(folder_a: Path, folder_b: Path) -> _Packages:
    """Match the package folders of two runs by name, then compare the files of each shared one."""
    names_a = _package_names(folder_a)
    names_b = _package_names(folder_b)
    changed: list[str] = []
    changed_files = 0
    for name in sorted(names_a & names_b):
        differing = _differing_files(folder_a / name, folder_b / name)
        if differing:
            changed.append(name)
            changed_files += differing
    return _Packages(
        names_a=tuple(sorted(names_a)),
        names_b=tuple(sorted(names_b)),
        added=tuple(sorted(names_b - names_a)),
        removed=tuple(sorted(names_a - names_b)),
        changed=tuple(changed),
        changed_files=changed_files,
    )


def _package_names(folder: Path) -> set[str]:
    """Names of the package folders directly inside ``folder``; loose files are not packages."""
    return {entry.name for entry in folder.iterdir() if entry.is_dir()}


def _differing_files(package_a: Path, package_b: Path) -> int:
    """How many files differ between two package folders; a file on one side only differs."""
    digests_a = _file_digests(package_a)
    digests_b = _file_digests(package_b)
    paths = digests_a.keys() | digests_b.keys()
    return sum(1 for path in paths if digests_a.get(path) != digests_b.get(path))


def _file_digests(package: Path) -> dict[str, str]:
    """SHA-256 of every file under ``package``, keyed by its path relative to it in POSIX form."""
    return {
        path.relative_to(package).as_posix(): _sha256(path)
        for path in package.rglob("*")
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    """SHA-256 hex digest of the bytes of ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _differing_index_lines(path_a: Path, path_b: Path) -> int:
    """How many ``tasks.jsonl`` lines differ, comparing content in any order.

    A file that is missing counts as having no lines, so every line of the other run differs.
    """
    lines_a = _index_lines(path_a)
    lines_b = _index_lines(path_b)
    return sum(((lines_a - lines_b) + (lines_b - lines_a)).values())


def _index_lines(path: Path) -> Counter[bytes]:
    """The non-blank lines of a ``tasks.jsonl`` file, trimmed; empty when the file is absent."""
    if not path.is_file():
        return Counter()
    return Counter(line.strip() for line in path.read_bytes().splitlines() if line.strip())


def _name_list(names: Sequence[str]) -> dict[str, Any]:
    """The count, the first :data:`NAME_LIMIT` names in sorted order, and whether any were cut."""
    ordered = sorted(names)
    return {
        "count": len(ordered),
        "names": ordered[:NAME_LIMIT],
        "truncated": len(ordered) > NAME_LIMIT,
    }
