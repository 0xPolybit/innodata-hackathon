"""Tests for ``tf diff``, run on two fake run folders built in ``tmp_path``.

No pipeline run is made. A fake run holds the folders the comparison reads: ``tasks/`` and
``rejected/`` with one folder per package, and an optional ``tasks.jsonl``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from taskfactory.cli import main
from taskfactory.diff import NAME_LIMIT

PACKAGE = "bar-tourism-000001-value_lookup"
OTHER = "bar-tourism-000002-rank_k"
REPORT_KEYS = {
    "tasks_a",
    "tasks_b",
    "added",
    "removed",
    "changed",
    "rejected_a",
    "rejected_b",
    "changed_files_total",
}

# The six files every package folder holds, with small fake contents.
PACKAGE_FILES = {
    "image.png": b"\x89PNG fake picture bytes",
    "manifest.json": b'{"files": {}}\n',
    "spec.json": b'{"family": "bar"}\n',
    "task.json": b'{"answer": "82.7M"}\n',
    "text_boxes.json": b"[]\n",
    "validation.json": b'{"passed": true}\n',
}


def make_run(
    run: Path,
    accepted: Iterable[str] = (PACKAGE,),
    rejected: Iterable[str] = (),
    index: bytes | None = None,
) -> Path:
    """Write a fake run folder; each named package gets the same six files."""
    for bucket, names in (("tasks", accepted), ("rejected", rejected)):
        (run / bucket).mkdir(parents=True, exist_ok=True)
        for name in names:
            package = run / bucket / name
            package.mkdir()
            for file_name, data in PACKAGE_FILES.items():
                (package / file_name).write_bytes(data)
    if index is not None:
        (run / "tasks.jsonl").write_bytes(index)
    return run


def run_diff(
    capsys: pytest.CaptureFixture[str], run_a: Path, run_b: Path
) -> tuple[int, dict[str, Any], str]:
    """Run ``tf diff`` on two folders; return the exit code, the parsed stdout and the stderr."""
    code = main(["diff", str(run_a), str(run_b)])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_identical_runs_exit_zero_with_zero_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index = f'{{"package_id": "{PACKAGE}"}}\n'.encode()
    run_a = make_run(tmp_path / "a", rejected=[OTHER], index=index)
    run_b = make_run(tmp_path / "b", rejected=[OTHER], index=index)

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 0
    for key in ("added", "removed", "changed"):
        assert report[key] == {"count": 0, "names": [], "truncated": False}
    assert report["changed_files_total"] == 0
    assert report["tasks_a"]["count"] == report["tasks_b"]["count"] == 1
    assert report["rejected_a"] == report["rejected_b"] == 1


def test_one_changed_image_gives_changed_one_and_exit_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a")
    run_b = make_run(tmp_path / "b")
    (run_b / "tasks" / PACKAGE / "image.png").write_bytes(b"\x89PNG a different picture")

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["changed"] == {"count": 1, "names": [PACKAGE], "truncated": False}
    assert report["changed_files_total"] == 1
    assert report["added"]["count"] == 0
    assert report["removed"]["count"] == 0


def test_package_only_in_run_b_is_added(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", accepted=[PACKAGE])
    run_b = make_run(tmp_path / "b", accepted=[PACKAGE, OTHER])

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["added"] == {"count": 1, "names": [OTHER], "truncated": False}
    assert report["removed"]["count"] == 0
    assert report["changed"]["count"] == 0


def test_package_only_in_run_a_is_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", accepted=[PACKAGE, OTHER])
    run_b = make_run(tmp_path / "b", accepted=[PACKAGE])

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["removed"] == {"count": 1, "names": [OTHER], "truncated": False}
    assert report["added"]["count"] == 0


def test_missing_run_folder_exits_two_with_no_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a")

    code = main(["diff", str(run_a), str(tmp_path / "missing")])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "folder not found" in captured.err


def test_run_without_its_tasks_folder_exits_two(tmp_path: Path) -> None:
    run_a = make_run(tmp_path / "a")
    run_b = make_run(tmp_path / "b")
    shutil.rmtree(run_b / "tasks")

    assert main(["diff", str(run_a), str(run_b)]) == 2


def test_every_changed_file_counts_toward_the_total(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a")
    run_b = make_run(tmp_path / "b")
    (run_b / "tasks" / PACKAGE / "image.png").write_bytes(b"other picture")
    (run_b / "tasks" / PACKAGE / "manifest.json").write_bytes(b'{"files": {"x": {}}}\n')

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["changed"]["count"] == 1
    assert report["changed_files_total"] == 2


def test_a_file_on_one_side_only_makes_its_package_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a")
    run_b = make_run(tmp_path / "b")
    (run_b / "tasks" / PACKAGE / "validation.json").unlink()

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["changed"]["names"] == [PACKAGE]
    assert report["changed_files_total"] == 1


def test_index_lines_are_compared_by_content_not_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", index=b'{"n": 1}\n{"n": 2}\n')
    run_b = make_run(tmp_path / "b", index=b'{"n": 2}\n\n{"n": 1}\n')

    code, _, _ = run_diff(capsys, run_a, run_b)

    assert code == 0


def test_a_differing_index_line_exits_one_although_packages_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", index=b'{"n": 1}\n')
    run_b = make_run(tmp_path / "b", index=b'{"n": 2}\n')

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["added"]["count"] == report["removed"]["count"] == 0
    assert report["changed"]["count"] == 0


def test_index_present_in_one_run_only_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", index=b'{"n": 1}\n')
    run_b = make_run(tmp_path / "b")

    code, _, _ = run_diff(capsys, run_a, run_b)

    assert code == 1


def test_name_lists_are_sorted_and_capped_with_a_truncated_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names = [f"bar-tourism-{number:06d}-value_lookup" for number in range(NAME_LIMIT + 5)]
    run_a = make_run(tmp_path / "a", accepted=[])
    run_b = make_run(tmp_path / "b", accepted=reversed(names))

    code, report, _ = run_diff(capsys, run_a, run_b)

    assert code == 1
    assert report["added"] == {
        "count": NAME_LIMIT + 5,
        "names": names[:NAME_LIMIT],
        "truncated": True,
    }


def test_rejected_packages_are_counted_without_changing_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a", rejected=[])
    run_b = make_run(tmp_path / "b", rejected=[OTHER])

    code, report, err = run_diff(capsys, run_a, run_b)

    assert code == 0
    assert report["rejected_a"] == 0
    assert report["rejected_b"] == 1
    assert "rejected 0 vs 1 (1 differing)" in err


def test_stdout_is_the_report_and_stderr_is_one_summary_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_a = make_run(tmp_path / "a")
    run_b = make_run(tmp_path / "b")

    _, report, err = run_diff(capsys, run_a, run_b)

    assert set(report) == REPORT_KEYS
    assert err.startswith("tf diff: ")
    assert err.count("\n") == 1
    assert err.strip().endswith(": match")


def test_both_run_folders_are_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["diff", str(tmp_path)])
    assert excinfo.value.code == 2
