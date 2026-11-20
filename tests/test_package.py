"""Tests for the task package writer and the run-level JSONL index."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from taskfactory.package import (
    append_index,
    compute_config_hash,
    get_git_sha,
    write_task_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PNG_BYTES = b"\x89PNG\r\n\x1a\nnot really a png, just deterministic bytes"

CONFIG_HASH = "0123456789abcdef" * 4
GIT_SHA = "fedcba9876543210" * 2 + "fedcba98"

TEXT_BOXES: list[dict[str, Any]] = [
    {
        "role": "title",
        "text": "International tourist arrivals (2024)",
        "bbox": [40, 26, 420, 60],
        "font_px": 31,
    },
    {
        "role": "category",
        "text": "Spain",
        "bbox": [120, 500, 190, 520],
        "font_px": 19,
    },
]


def make_spec(index: int = 0) -> dict[str, Any]:
    """Hand-made bar spec with valid, distinct values."""
    return {
        "spec_version": 1,
        "family": "bar",
        "domain": "tourism",
        "index": index,
        "seed": 12345,
        "title": "International tourist arrivals (2024)",
        "x_labels": ["France", "Spain", "Italy"],
        "series": [
            {
                "name": "",
                "values": [40_600_000, 82_700_000, 64_500_000],
                "labels": ["40.6M", "82.7M", "64.5M"],
            }
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }


def make_question_task(spec: dict[str, Any]) -> dict[str, Any]:
    """Hand-made value_lookup task keyed to ``spec``."""
    return {
        "task_type": "value_lookup",
        "family": "bar",
        "domain": "tourism",
        "spec_index": spec["index"],
        "question": "What value is shown for Spain?",
        "answer": "82.7M",
        "answer_value": 82_700_000,
        "answer_category": "Spain",
        "reasoning_steps": 1,
        "answer_printed_in_image": True,
        "question_in_image": True,
    }


def package_id_for(spec: dict[str, Any], task: dict[str, Any]) -> str:
    return f"{spec['family']}-{spec['domain']}-{spec['index']:06d}-{task['task_type']}"


def write_package(
    run_root: Path,
    png_path: Path,
    spec: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    text_boxes: list[dict[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Write one package with hand-made defaults and return path, spec and task."""
    spec = make_spec() if spec is None else spec
    task = make_question_task(spec) if task is None else task
    result = write_task_package(
        run_root,
        spec,
        task,
        png_path,
        TEXT_BOXES if text_boxes is None else text_boxes,
        CONFIG_HASH,
        GIT_SHA,
    )
    return result, spec, task


@pytest.fixture
def png_path(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    path.write_bytes(PNG_BYTES)
    return path


def test_writes_the_expected_layout(tmp_path: Path, png_path: Path) -> None:
    package_dir, spec, task = write_package(tmp_path / "run", png_path)
    package_id = package_id_for(spec, task)

    assert package_dir == tmp_path / "run" / "tasks" / package_id
    assert package_dir.is_dir()
    assert {child.name for child in package_dir.iterdir()} == {
        "image.png",
        "spec.json",
        "text_boxes.json",
        "task.json",
        "manifest.json",
    }
    assert (package_dir / "image.png").read_bytes() == PNG_BYTES
    assert json.loads((package_dir / "spec.json").read_text(encoding="utf-8")) == spec
    assert (
        json.loads((package_dir / "text_boxes.json").read_text(encoding="utf-8"))
        == TEXT_BOXES
    )
    assert json.loads((package_dir / "task.json").read_text(encoding="utf-8")) == task


def test_manifest_hashes_match_the_files(tmp_path: Path, png_path: Path) -> None:
    package_dir, spec, task = write_package(tmp_path / "run", png_path)
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

    assert set(manifest) == {
        "package_id",
        "files",
        "config_hash",
        "git_sha",
        "versions",
    }
    assert manifest["package_id"] == package_id_for(spec, task)
    assert manifest["config_hash"] == CONFIG_HASH
    assert manifest["git_sha"] == GIT_SHA
    assert "created_utc" not in manifest
    assert not any("timestamp" in key or "date" in key for key in manifest)

    assert set(manifest["files"]) == {
        "image.png",
        "spec.json",
        "text_boxes.json",
        "task.json",
    }
    for name, record in manifest["files"].items():
        data = (package_dir / name).read_bytes()
        assert record == {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    assert set(manifest["versions"]) == {"python", "matplotlib", "pillow", "numpy"}
    assert manifest["versions"]["python"] == platform.python_version()
    for version in manifest["versions"].values():
        assert isinstance(version, str) and version


def test_writing_twice_gives_identical_manifest_bytes(
    tmp_path: Path, png_path: Path
) -> None:
    run_root = tmp_path / "run"
    first, _, _ = write_package(run_root, png_path)
    first_manifest = (first / "manifest.json").read_bytes()

    second, _, _ = write_package(run_root, png_path)

    assert second == first
    assert (second / "manifest.json").read_bytes() == first_manifest


def test_different_content_for_the_same_package_id_raises(
    tmp_path: Path, png_path: Path
) -> None:
    run_root = tmp_path / "run"
    package_dir, _, _ = write_package(run_root, png_path)
    manifest_before = (package_dir / "manifest.json").read_bytes()

    changed = make_spec()
    changed["title"] = "A different chart title"
    with pytest.raises(FileExistsError, match="different content"):
        write_package(run_root, png_path, spec=changed)

    assert (package_dir / "manifest.json").read_bytes() == manifest_before


def test_append_index_does_not_duplicate_a_package_id(
    tmp_path: Path, png_path: Path
) -> None:
    run_root = tmp_path / "run"
    package_dir, spec, task = write_package(run_root, png_path)
    package_id = package_id_for(spec, task)
    args = (
        run_root,
        package_id,
        task["task_type"],
        task["answer"],
        task["family"],
        task["domain"],
        task["spec_index"],
    )

    append_index(*args)
    append_index(*args)

    lines = (run_root / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "package_id": package_id,
        "task_type": task["task_type"],
        "family": task["family"],
        "domain": task["domain"],
        "spec_index": task["spec_index"],
        "question": task["question"],
        "answer": task["answer"],
        "answer_category": task["answer_category"],
    }
    assert list(record) == sorted(record)
    assert package_dir.is_dir()


def test_append_index_adds_one_line_per_package(
    tmp_path: Path, png_path: Path
) -> None:
    run_root = tmp_path / "run"
    package_dir, spec, task = write_package(run_root, png_path)
    package_id = package_id_for(spec, task)

    append_index(
        run_root,
        package_id,
        task["task_type"],
        task["answer"],
        task["family"],
        task["domain"],
        task["spec_index"],
    )
    append_index(
        run_root,
        "bar-tourism-000001-extremum",
        "extremum",
        "Spain",
        "bar",
        "tourism",
        1,
    )

    lines = (run_root / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["package_id"] == package_id
    assert json.loads(lines[1])["package_id"] == "bar-tourism-000001-extremum"
    assert package_dir.is_dir()


def test_compute_config_hash_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "demo.toml"
    data = "run_seed = 20261206\nquestion_in_image = true\n".encode("utf-8")
    path.write_bytes(data)

    assert compute_config_hash(path) == hashlib.sha256(data).hexdigest()


def test_get_git_sha_returns_none_or_a_commit_sha() -> None:
    sha = get_git_sha(REPO_ROOT)

    assert sha == "none" or (
        len(sha) == 40 and all(char in "0123456789abcdef" for char in sha)
    )


def test_get_git_sha_returns_none_when_git_cannot_run(tmp_path: Path) -> None:
    assert get_git_sha(tmp_path / "missing-directory") == "none"
