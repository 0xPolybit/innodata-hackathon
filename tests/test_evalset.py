"""Tests for taskfactory.evalset. Offline: the pool is a synthetic folder built in tmp_path."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from taskfactory.evalset import (
    ITEM_FIELDS,
    allocate_strata,
    build_eval_set,
    load_eval_set,
    summary_path,
)

# Stratum sizes of the real pool (out/pool/tasks, 564 valid packages).
REAL_POOL_SIZES = {
    ("bar", "extremum"): 120,
    ("bar", "pair_compare"): 120,
    ("bar", "rank_k"): 91,
    ("bar", "value_lookup"): 119,
    ("line", "series_at_x"): 114,
}
FIVE_TYPES = [(family, task_type) for family, task_type in REAL_POOL_SIZES]


def make_task(family: str, task_type: str, index: int) -> dict[str, Any]:
    return {
        "answer": f"answer {index}",
        "answer_category": f"category {index}",
        "answer_printed_in_image": True,
        "domain": "energy",
        "family": family,
        "question": f"Question {index} for {task_type}?",
        "question_in_image": True,
        "reasoning_steps": 1,
        "spec_index": index,
        "task_type": task_type,
    }


def make_pool(root: Path, sizes: dict[tuple[str, str], int]) -> Path:
    """A pool folder with ``count`` valid packages for each (family, task_type)."""
    pool = root / "pool" / "tasks"
    for (family, task_type), count in sizes.items():
        for index in range(count):
            folder = pool / f"{family}-{task_type}-{index:06d}"
            folder.mkdir(parents=True)
            (folder / "task.json").write_text(
                json.dumps(make_task(family, task_type, index), sort_keys=True), encoding="utf-8"
            )
            (folder / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + folder.name.encode("ascii"))
    return pool


def read_items(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").split("\n") if line]


SMALL_SIZES = {key: 12 for key in FIVE_TYPES}


# --- allocation ----------------------------------------------------------------------------


def test_allocate_strata_gives_every_real_stratum_an_equal_share_of_200() -> None:
    allocation = allocate_strata(REAL_POOL_SIZES, 200)
    assert sum(allocation.values()) == 200
    assert set(allocation.values()) == {40}


def test_allocate_strata_gives_the_remainder_to_the_first_strata_in_sorted_order() -> None:
    sizes = {("a", "x"): 9, ("b", "x"): 9, ("c", "x"): 9}
    assert allocate_strata(sizes, 7) == {("a", "x"): 3, ("b", "x"): 2, ("c", "x"): 2}


def test_allocate_strata_passes_a_short_strata_share_to_the_strata_with_more() -> None:
    sizes = {("a", "x"): 2, ("b", "x"): 30, ("c", "x"): 30}
    assert allocate_strata(sizes, 20) == {("a", "x"): 2, ("b", "x"): 9, ("c", "x"): 9}


def test_allocate_strata_refuses_more_items_than_exist() -> None:
    with pytest.raises(ValueError, match="only 2 valid packages"):
        allocate_strata({("a", "x"): 2}, 3)
    with pytest.raises(ValueError, match="must not be negative"):
        allocate_strata({("a", "x"): 2}, -1)


def test_item_fields_are_the_documented_ones() -> None:
    assert set(ITEM_FIELDS) == {
        "item_id",
        "package_dir",
        "family",
        "task_type",
        "question",
        "answer",
        "answer_category",
        "domain",
        "image_sha256",
    }


# --- building the frozen set ---------------------------------------------------------------


def test_build_returns_n_items_with_a_balanced_allocation(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"

    summary = build_eval_set(pool, out, n=20, seed=7)

    assert summary["items"] == 20
    assert summary["n"] == 20
    assert summary["seed"] == 7
    assert {entry["selected"] for entry in summary["strata"].values()} == {4}
    items = read_items(out)
    assert len(items) == 20
    assert Counter((item["family"], item["task_type"]) for item in items) == Counter(
        {key: 4 for key in FIVE_TYPES}
    )


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"

    first = build_eval_set(pool, out, n=20, seed=3)
    items_bytes = out.read_bytes()
    summary_bytes = summary_path(out).read_bytes()

    second = build_eval_set(pool, out, n=20, seed=3)

    assert out.read_bytes() == items_bytes
    assert summary_path(out).read_bytes() == summary_bytes
    assert first == second
    assert first["sha256"] == hashlib.sha256(items_bytes).hexdigest()


def test_each_line_is_a_sorted_key_object_with_the_documented_fields(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, out, n=20, seed=3)

    lines = out.read_bytes().decode("utf-8").split("\n")
    assert lines[-1] == ""  # the file ends with a newline
    for line in lines[:-1]:
        item = json.loads(line)
        assert set(item) == set(ITEM_FIELDS)
        assert line == json.dumps(item, sort_keys=True)


def test_package_dir_points_at_the_package_and_the_image_sha_matches(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, out, n=20, seed=3)

    for item in read_items(out):
        assert "\\" not in item["package_dir"]
        folder = (out.parent / item["package_dir"]).resolve()
        assert folder == (pool / item["item_id"]).resolve()
        assert item["image_sha256"] == hashlib.sha256((folder / "image.png").read_bytes()).hexdigest()


def test_summary_records_seed_n_strata_and_the_file_sha(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"

    summary = build_eval_set(pool, out, n=20, seed=7)

    assert summary_path(out).name == "items.summary.json"
    assert json.loads(summary_path(out).read_text(encoding="utf-8")) == summary
    assert summary["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert summary["pool_packages"] == 60
    assert summary["strata"]["bar/extremum"] == {"available": 12, "selected": 4}
    assert summary["strata"]["line/series_at_x"] == {"available": 12, "selected": 4}


def test_the_first_lines_already_cover_every_stratum(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, out, n=20, seed=3)

    first_five = read_items(out)[:5]
    assert len({(item["family"], item["task_type"]) for item in first_five}) == 5


def test_a_different_seed_draws_a_different_set(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    build_eval_set(pool, tmp_path / "a" / "items.jsonl", n=20, seed=1)
    build_eval_set(pool, tmp_path / "b" / "items.jsonl", n=20, seed=2)

    ids_a = {item["item_id"] for item in read_items(tmp_path / "a" / "items.jsonl")}
    ids_b = {item["item_id"] for item in read_items(tmp_path / "b" / "items.jsonl")}
    assert ids_a != ids_b


def test_folders_without_both_files_are_left_out(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, {("bar", "extremum"): 3, ("line", "series_at_x"): 3})
    (pool / "no-image").mkdir()
    (pool / "no-image" / "task.json").write_text(json.dumps(make_task("bar", "extremum", 99)), encoding="utf-8")
    (pool / "no-task").mkdir()
    (pool / "no-task" / "image.png").write_bytes(b"not a task")
    (pool / "stray.txt").write_text("not a package", encoding="utf-8")
    out = tmp_path / "eval" / "items.jsonl"

    summary = build_eval_set(pool, out, n=6, seed=1)

    complete = {
        path.name
        for path in pool.iterdir()
        if (path / "task.json").is_file() and (path / "image.png").is_file()
    }
    assert len(complete) == 6
    assert summary["pool_packages"] == 6
    assert {item["item_id"] for item in read_items(out)} == complete


def test_a_malformed_task_json_is_an_error(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, {("bar", "extremum"): 2})
    (pool / "bar-extremum-000000" / "task.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="task.json"):
        build_eval_set(pool, tmp_path / "items.jsonl", n=1)


def test_n_larger_than_the_pool_writes_nothing(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, {("bar", "extremum"): 2, ("line", "series_at_x"): 2})
    out = tmp_path / "items.jsonl"

    with pytest.raises(ValueError, match="only 4 valid packages"):
        build_eval_set(pool, out, n=5)
    assert not out.exists()
    assert not summary_path(out).exists()


def test_n_below_one_is_an_error(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, {("bar", "extremum"): 2})
    with pytest.raises(ValueError, match="at least 1"):
        build_eval_set(pool, tmp_path / "items.jsonl", n=0)


def test_a_changed_pool_does_not_overwrite_the_frozen_set(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, out, n=20, seed=7)
    before = out.read_bytes()
    summary_before = summary_path(out).read_bytes()

    extra = pool / "bar-extremum-000100"
    extra.mkdir()
    (extra / "task.json").write_text(json.dumps(make_task("bar", "extremum", 100)), encoding="utf-8")
    (extra / "image.png").write_bytes(b"\x89PNG extra")

    with pytest.raises(ValueError, match="already holds different content"):
        build_eval_set(pool, out, n=20, seed=7)
    assert out.read_bytes() == before
    assert summary_path(out).read_bytes() == summary_before


# --- loading the frozen set ----------------------------------------------------------------


def test_load_eval_set_returns_the_items_and_the_file_sha(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    summary = build_eval_set(pool, out, n=20, seed=7)

    items, digest = load_eval_set(out)

    assert len(items) == 20
    assert digest == summary["sha256"]
    assert items == read_items(out)


def test_load_eval_set_refuses_a_file_that_changed_after_freezing(tmp_path: Path) -> None:
    pool = make_pool(tmp_path, SMALL_SIZES)
    out = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, out, n=20, seed=7)
    out.write_bytes(out.read_bytes().replace(b"Question", b"Qvestion", 1))

    with pytest.raises(ValueError, match="changed after it was frozen"):
        load_eval_set(out)


def test_load_eval_set_rejects_duplicate_item_ids(tmp_path: Path) -> None:
    line = json.dumps({field: "x" for field in ITEM_FIELDS}, sort_keys=True)
    items_path = tmp_path / "duplicates.jsonl"
    items_path.write_text(line + "\n" + line + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate item_id"):
        load_eval_set(items_path)
