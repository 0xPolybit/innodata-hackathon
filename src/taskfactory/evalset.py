"""Frozen evaluation set: a stratified, seeded sample of valid pool packages.

:func:`build_eval_set` reads every package folder in a pool tasks folder that holds
``task.json`` and ``image.png``, groups the packages by (family, task_type) and draws
``n`` of them with ``random.Random(seed)``. The items go to a JSON Lines file. A summary
next to it records the counts per stratum and the SHA-256 of the file, so a later run can
prove that it used the same items. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskfactory.llm import image_sha256

__all__ = [
    "DEFAULT_N",
    "DEFAULT_SEED",
    "ITEM_FIELDS",
    "allocate_strata",
    "build_eval_set",
    "load_eval_set",
    "read_json_object",
    "summary_path",
    "write_atomic",
]

DEFAULT_N = 200
DEFAULT_SEED = 20261211
ITEM_FIELDS = (
    "answer",
    "answer_category",
    "domain",
    "family",
    "image_sha256",
    "item_id",
    "package_dir",
    "question",
    "task_type",
)
_REQUIRED_TASK_TEXT = ("answer", "answer_category", "domain", "family", "question", "task_type")

Stratum = tuple[str, str]


@dataclass(frozen=True)
class _Package:
    item_id: str  # the package folder name
    folder: Path  # absolute
    task: dict[str, Any]


def summary_path(out_path: str | Path) -> Path:
    """The summary that belongs to a frozen set: items.jsonl becomes items.summary.json."""
    return Path(out_path).with_suffix(".summary.json")


def allocate_strata(sizes: Mapping[Stratum, int], n: int) -> dict[Stratum, int]:
    """Split n picks over strata, dealing one pick at a time in sorted stratum order.

    Each stratum gets floor(n / strata) picks, or one more while it has items. A stratum
    with fewer items than its share keeps all of them, and the rest go to the strata that
    still have items. Raises ValueError when n is negative or larger than the total.
    """
    if n < 0:
        raise ValueError(f"n must not be negative, got {n}")
    total = sum(sizes.values())
    if n > total:
        raise ValueError(f"cannot draw n={n} items: the pool has only {total} valid packages")
    keys = sorted(sizes)
    allocation = dict.fromkeys(keys, 0)
    remaining = n
    while remaining > 0:
        for key in keys:
            if remaining == 0:
                break
            if allocation[key] < sizes[key]:
                allocation[key] += 1
                remaining -= 1
    return allocation


def build_eval_set(
    pool_tasks_dir: Path,
    out_path: Path,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Write the frozen set to ``out_path`` and its summary beside it, and return the summary.

    ``out_path`` holds one sorted-key JSON object per item. The lines are in the order the
    picks were dealt, so any prefix covers the strata as evenly as the counts allow.
    ``package_dir`` is relative to the folder that holds ``out_path``.

    Raises ValueError when n is below 1 or above the number of valid packages, when a
    task.json is malformed, and when the files already at ``out_path`` and its summary would
    change. A changed pool or seed must not silently replace a frozen set, so choose another
    ``out_path`` (or delete the old files first).
    """
    if n < 1:
        raise ValueError(f"n must be at least 1, got {n}")
    out_file = Path(out_path)
    packages = _discover(Path(pool_tasks_dir))
    if not packages:
        raise ValueError(f"{pool_tasks_dir}: no package folder has both task.json and image.png")

    strata: dict[Stratum, list[_Package]] = {}
    for package in packages:
        strata.setdefault(_stratum(package.task), []).append(package)
    sizes = {key: len(members) for key, members in strata.items()}
    allocation = allocate_strata(sizes, n)

    base = out_file.resolve().parent
    items = [_item(package, base) for package in _deal(strata, allocation, seed)]
    body = "".join(json.dumps(item, sort_keys=True) + "\n" for item in items).encode("utf-8")
    summary: dict[str, Any] = {
        "file": out_file.name,
        "items": len(items),
        "n": n,
        "pool_packages": len(packages),
        "seed": seed,
        "sha256": hashlib.sha256(body).hexdigest(),
        "strata": {
            f"{family}/{task_type}": {
                "available": sizes[(family, task_type)],
                "selected": allocation[(family, task_type)],
            }
            for family, task_type in sorted(sizes)
        },
    }
    summary_file = summary_path(out_file)
    summary_bytes = _json_bytes(summary)
    _refuse_changed((out_file, body), (summary_file, summary_bytes))
    write_atomic(out_file, body)
    write_atomic(summary_file, summary_bytes)
    return summary


def load_eval_set(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Read a frozen set and return ``(items, SHA-256 of the file)``.

    Raises ValueError for a line that is not an item, for a duplicate item_id, and when the
    file's SHA-256 differs from the one its summary records (the set changed after freezing).
    """
    items_file = Path(path)
    body = items_file.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    summary_file = summary_path(items_file)
    if summary_file.is_file():
        recorded = read_json_object(summary_file).get("sha256")
        if recorded != digest:
            raise ValueError(
                f"{items_file} changed after it was frozen: its SHA-256 is {digest}, "
                f"but {summary_file.name} records {recorded}"
            )

    lines = body.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        try:
            item = json.loads(line)
        except ValueError:
            raise ValueError(f"{items_file}:{number}: not a JSON line") from None
        if not isinstance(item, dict) or set(item) != set(ITEM_FIELDS):
            raise ValueError(f"{items_file}:{number}: an item needs exactly the fields {', '.join(ITEM_FIELDS)}")
        item_id = item["item_id"]
        if item_id in seen:
            raise ValueError(f"{items_file}:{number}: duplicate item_id {item_id!r}")
        seen.add(item_id)
        items.append(item)
    if not items:
        raise ValueError(f"{items_file}: the eval set has no items")
    return items, digest


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON file that must hold an object. Raises ValueError otherwise."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot read JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def write_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a temporary file, so an interrupted write never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def _discover(pool_dir: Path) -> list[_Package]:
    if not pool_dir.is_dir():
        raise ValueError(f"{pool_dir}: not a folder of package folders")
    packages: list[_Package] = []
    for folder in sorted(pool_dir.iterdir(), key=lambda path: path.name):
        task_file = folder / "task.json"
        if folder.is_dir() and task_file.is_file() and (folder / "image.png").is_file():
            packages.append(_Package(folder.name, folder.resolve(), _read_task(task_file)))
    return packages


def _read_task(path: Path) -> dict[str, Any]:
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot read task.json: {exc}") from None
    if not isinstance(task, dict):
        raise ValueError(f"{path}: task.json must hold a JSON object")
    for field in _REQUIRED_TASK_TEXT:
        value = task.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: {field!r} must be a non-empty string")
    return task


def _stratum(task: Mapping[str, Any]) -> Stratum:
    return (str(task["family"]), str(task["task_type"]))


def _item_id(package: _Package) -> str:
    return package.item_id


def _deal(
    strata: Mapping[Stratum, Sequence[_Package]],
    allocation: Mapping[Stratum, int],
    seed: int,
) -> list[_Package]:
    """Pick each stratum's packages with a fresh ``random.Random(seed)``, then deal them round-robin."""
    keys = sorted(strata)
    picks = {
        key: random.Random(seed).sample(sorted(strata[key], key=_item_id), allocation[key])
        for key in keys
    }
    dealt: list[_Package] = []
    for round_index in range(max(allocation.values(), default=0)):
        for key in keys:
            if round_index < allocation[key]:
                dealt.append(picks[key][round_index])
    return dealt


def _item(package: _Package, base: Path) -> dict[str, Any]:
    task = package.task
    return {
        "item_id": package.item_id,
        "package_dir": _relative_ref(package.folder, base),
        "family": task["family"],
        "task_type": task["task_type"],
        "question": task["question"],
        "answer": task["answer"],
        "answer_category": task["answer_category"],
        "domain": task["domain"],
        "image_sha256": image_sha256(package.folder / "image.png"),
    }


def _relative_ref(target: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(target, base)).as_posix()
    except ValueError:  # Windows: the two paths are on different drives
        return target.as_posix()


def _refuse_changed(*files: tuple[Path, bytes]) -> None:
    """Refuse when a rebuild would change an existing frozen file, the summary included."""
    for path, data in files:
        if path.is_file() and path.read_bytes() != data:
            raise ValueError(
                f"{path} already holds different content, so the eval set would change "
                "(the pool, seed or n changed). Delete the frozen files or choose another output path."
            )


def _json_bytes(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
