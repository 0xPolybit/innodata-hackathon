"""Write one task package per task, plus the run-level JSONL index.

A package lives at ``<run_root>/tasks/<package_id>/`` and holds the rendered
``image.png``, ``spec.json``, ``text_boxes.json``, ``task.json`` and a
``manifest.json`` with a SHA-256 and byte count for every one of those files.

Every JSON file is written with sorted keys and a fixed indentation, and the
manifest carries no timestamp, so rerunning a generation over the same inputs
produces byte-identical files.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

__all__ = [
    "append_index",
    "compute_config_hash",
    "get_git_sha",
    "write_task_package",
]

_IMAGE_NAME = "image.png"
_SPEC_NAME = "spec.json"
_TEXT_BOXES_NAME = "text_boxes.json"
_TASK_NAME = "task.json"
_MANIFEST_NAME = "manifest.json"
_INDEX_NAME = "tasks.jsonl"

_PACKAGE_FILES = (_IMAGE_NAME, _SPEC_NAME, _TEXT_BOXES_NAME, _TASK_NAME)
_GIT_SHA_LENGTH = 40


def write_task_package(
    run_root: str | Path,
    spec: dict[str, Any],
    question_task: dict[str, Any],
    png_bytes_path: str | Path,
    text_boxes: list[dict[str, Any]],
    config_hash: str,
    git_sha: str | None,
) -> Path:
    """Write one task package under ``run_root/tasks`` and return its folder.

    The package id is ``family-domain-index-task_type`` with the index padded
    to six digits.  The PNG is copied with :func:`shutil.copyfile`; the other
    payloads are serialised as sorted-key, two-space-indented UTF-8 JSON.

    If the package folder already exists and its manifest lists the same file
    hashes, the folder is left untouched and returned.  If the hashes differ,
    :class:`FileExistsError` is raised rather than overwriting a package built
    from different content.
    """
    run_root = Path(run_root)
    package_id = (
        f"{spec['family']}-{spec['domain']}-{spec['index']:06d}-"
        f"{question_task['task_type']}"
    )
    package_dir = run_root / "tasks" / package_id

    png_bytes_path = Path(png_bytes_path)
    payloads = {
        _IMAGE_NAME: png_bytes_path.read_bytes(),
        _SPEC_NAME: _json_bytes(spec),
        _TEXT_BOXES_NAME: _json_bytes(text_boxes),
        _TASK_NAME: _json_bytes(question_task),
    }
    files = {name: _file_record(payloads[name]) for name in _PACKAGE_FILES}

    if package_dir.exists():
        _check_existing_package(package_dir, files)
        return package_dir

    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(png_bytes_path, package_dir / _IMAGE_NAME)
    for name in (_SPEC_NAME, _TEXT_BOXES_NAME, _TASK_NAME):
        (package_dir / name).write_bytes(payloads[name])

    manifest = {
        "package_id": package_id,
        "files": files,
        "config_hash": config_hash,
        "git_sha": git_sha or "none",
        "versions": {
            "python": platform.python_version(),
            "matplotlib": _distribution_version("matplotlib"),
            "pillow": _distribution_version("pillow"),
            "numpy": _distribution_version("numpy"),
        },
    }
    (package_dir / _MANIFEST_NAME).write_bytes(_json_bytes(manifest))
    return package_dir


def append_index(
    run_root: str | Path,
    package_id: str,
    task_type: str,
    answer: str,
    family: str,
    domain: str,
    index: int,
    *,
    question: str | None = None,
    answer_category: str | None = None,
) -> None:
    """Append one task to ``<run_root>/tasks.jsonl`` unless it is already there.

    A package id appears at most once in the index.  ``question`` and
    ``answer_category`` are taken from the package's ``task.json`` when the
    caller does not pass them.
    """
    run_root = Path(run_root)
    index_path = run_root / _INDEX_NAME
    if _index_has_package(index_path, package_id):
        return

    if question is None or answer_category is None:
        task = _package_task(run_root, package_id)
        if question is None:
            question = task.get("question", "")
        if answer_category is None:
            answer_category = task.get("answer_category", "")

    record = {
        "package_id": package_id,
        "task_type": task_type,
        "family": family,
        "domain": domain,
        "spec_index": index,
        "question": question,
        "answer": answer,
        "answer_category": answer_category,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def compute_config_hash(path: str | Path) -> str:
    """Return the SHA-256 hex digest of the bytes of ``path``."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get_git_sha(repo_dir: str | Path) -> str:
    """Return the current commit sha for ``repo_dir``, or ``"none"``.

    A missing git executable, a directory that is not a repository, and a
    repository with no commits all return ``"none"`` instead of raising.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "none"

    if result.returncode != 0:
        return "none"
    sha = result.stdout.strip()
    if len(sha) != _GIT_SHA_LENGTH or any(c not in "0123456789abcdef" for c in sha):
        return "none"
    return sha


def _json_bytes(value: Any) -> bytes:
    """Serialise ``value`` the one way every package file uses."""
    return json.dumps(value, indent=2, sort_keys=True).encode("utf-8")


def _file_record(data: bytes) -> dict[str, Any]:
    """Hash and size record for one package file."""
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _distribution_version(name: str) -> str:
    """Installed version of a distribution, or ``"unknown"`` when absent."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _check_existing_package(package_dir: Path, files: dict[str, Any]) -> None:
    """Refuse to overwrite a package whose manifest hashes match a different build."""
    manifest_path = package_dir / _MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FileExistsError(
            f"package folder already exists without a readable manifest: {package_dir}"
        ) from exc

    if not isinstance(manifest, dict) or manifest.get("files") != files:
        raise FileExistsError(
            f"package folder already exists with different content: {package_dir}"
        )


def _index_has_package(index_path: Path, package_id: str) -> bool:
    """Return True when ``package_id`` already has a line in the index."""
    if not index_path.exists():
        return False
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("package_id") == package_id:
                return True
    return False


def _package_task(run_root: Path, package_id: str) -> dict[str, Any]:
    """Read the package's ``task.json``, returning an empty dict if it is absent."""
    task_path = run_root / "tasks" / package_id / _TASK_NAME
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return task if isinstance(task, dict) else {}
