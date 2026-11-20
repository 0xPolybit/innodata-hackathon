"""Tests for taskfactory.pipeline and the ``tf run`` command.

Each test project copies the tourism domain and the blocklist into ``configs/``
with the repository's layout, so the loaders find them as they do in practice.

Most assertions do not need Tesseract: without it the OCR check fails, so every
package is rejected, and the counts, skips, index files and captions are still
checked. Only the assertions that need packages to pass are marked
``needs_tesseract``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from taskfactory import variation
from taskfactory.cli import main
from taskfactory.config import ConfigError, load_domain, load_run_config
from taskfactory.package import compute_config_hash
from taskfactory.pipeline import CHECK_NAMES, LINE_CHECK_NAMES, run_pipeline
from taskfactory.questions import make_questions
from taskfactory.sampler import sample_batch

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

RUN_CONFIG = """\
run_seed = 20261206
tasks_per_cell = 2
question_in_image = true
families = ["bar", "line"]
domains = ["tourism"]
question_types = ["value_lookup", "extremum", "rank_k"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
"""

# Seed 20261206 gives both line specs a top-two margin below 0.05 at their year, so
# no series_at_x task is asked of them. Seed 20261207 gives two askable line specs.
LINE_RUN_CONFIG = """\
run_seed = 20261207
tasks_per_cell = 2
question_in_image = true
families = ["line"]
domains = ["tourism"]
question_types = ["series_at_x"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
"""

MIXED_RUN_CONFIG = """\
run_seed = 20261207
tasks_per_cell = 2
question_in_image = true
families = ["bar", "line"]
domains = ["tourism"]
question_types = ["value_lookup", "series_at_x"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
"""


def _tesseract_command() -> str | None:
    """The executable the OCR check would use, or None when there is none."""
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd:
        return env_cmd
    if Path(DEFAULT_TESSERACT_CMD).is_file():
        return DEFAULT_TESSERACT_CMD
    return shutil.which("tesseract")


TESSERACT_CMD = _tesseract_command()
needs_tesseract = pytest.mark.skipif(
    TESSERACT_CMD is None,
    reason=(
        "Tesseract executable not found; set TESSERACT_CMD or install it at "
        f"{DEFAULT_TESSERACT_CMD}"
    ),
)


def _make_project(root: Path, run_config: str = RUN_CONFIG) -> Path:
    """Lay out ``configs/`` under ``root`` and write the run config as ``runs/test.toml``."""
    configs = root / "configs"
    (configs / "runs").mkdir(parents=True)
    (configs / "domains").mkdir()
    shutil.copyfile(
        REPO_ROOT / "configs" / "domains" / "tourism.toml",
        configs / "domains" / "tourism.toml",
    )
    shutil.copyfile(REPO_ROOT / "configs" / "blocklist.txt", configs / "blocklist.txt")
    (configs / "runs" / "test.toml").write_text(run_config, encoding="utf-8")
    return root


def _config_path(project: Path) -> Path:
    return project / "configs" / "runs" / "test.toml"


def _run(project: Path, run_id: str = "test1", *, overwrite: bool = False) -> dict[str, Any]:
    """Run the pipeline on ``project`` with the Tesseract command found above."""
    return run_pipeline(
        _config_path(project),
        project / "out",
        run_id,
        tesseract_cmd=TESSERACT_CMD,
        repo_dir=project,
        overwrite=overwrite,
    )


def _cli_args(project: Path, run_id: str, *extra: str) -> list[str]:
    """Arguments for ``tf run`` on ``project``, with --tesseract when it was found."""
    args = [
        "run",
        "--config",
        str(_config_path(project)),
        "--out",
        str(project / "out"),
        "--run-id",
        run_id,
        *extra,
    ]
    if TESSERACT_CMD is not None:
        args += ["--tesseract", TESSERACT_CMD]
    return args


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    """Every line of a JSONL file, or an empty list when the file is absent."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _packages(out: Path) -> list[Path]:
    """Every finished package folder, in tasks/ and rejected/."""
    return sorted(p for folder in ("tasks", "rejected") for p in (out / folder).iterdir())


def _caption_texts(package: Path) -> list[str]:
    """The text of every caption box in a package's text_boxes.json."""
    boxes = _read_json(package / "text_boxes.json")
    return [box["text"] for box in boxes if box["role"] == "caption"]


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One run of the test config, shared by the tests that only read its output."""
    project = _make_project(tmp_path_factory.mktemp("baseline"))
    metrics = _run(project)
    return {"project": project, "out": project / "out", "metrics": metrics}


def test_generates_value_lookup_and_extremum_for_each_spec(baseline: dict[str, Any]) -> None:
    metrics = baseline["metrics"]
    # rank_k and pair_compare were added to the implemented question types, so the
    # rank_k question in this config is now asked. Each of the 2 bar specs makes a
    # value_lookup and an extremum package. Only one of them makes a rank_k package:
    # questions.py skips rank_k when the chosen rank is within the margin of a
    # neighbouring value, which is the case for the other spec. pair_compare is
    # implemented but this config does not request it. The line specs ask none of
    # the listed types, so they make no package.
    assert metrics["generated"] == 5
    assert metrics["passed"] + metrics["rejected"] == metrics["generated"]
    assert 0 <= metrics["yield"] <= 1
    assert metrics["skipped"] == []
    assert metrics["run_id"] == "test1"
    assert metrics["config_hash"] == compute_config_hash(_config_path(baseline["project"]))


def test_per_check_counts_cover_every_check(baseline: dict[str, Any]) -> None:
    metrics = baseline["metrics"]
    assert set(metrics["per_check"]) == set(CHECK_NAMES)
    for counts in metrics["per_check"].values():
        assert counts["pass"] + counts["fail"] == metrics["generated"]


def test_writes_index_and_metrics_and_leaves_no_staging(baseline: dict[str, Any]) -> None:
    out = baseline["out"]
    assert not (out / "staging").exists()

    records = _read_jsonl(out / "validation.jsonl")
    assert len(records) == baseline["metrics"]["generated"]
    for record in records:
        assert set(record) == {"failed_checks", "package_id", "passed"}
    assert {record["package_id"] for record in records} == {p.name for p in _packages(out)}

    assert _read_json(out / "metrics.json") == baseline["metrics"]

    for package in _packages(out):
        assert sorted(p.name for p in package.iterdir()) == sorted(
            [
                "image.png",
                "manifest.json",
                "spec.json",
                "task.json",
                "text_boxes.json",
                "validation.json",
            ]
        )


def test_question_is_drawn_as_caption_in_every_package(baseline: dict[str, Any]) -> None:
    packages = _packages(baseline["out"])
    assert len(packages) == 5  # rank_k and pair_compare were added; see test above
    for package in packages:
        task = _read_json(package / "task.json")
        assert _caption_texts(package) == [task["question"]]


def test_second_run_without_overwrite_is_refused(baseline: dict[str, Any]) -> None:
    """Refusal is a ValueError, raised before anything is deleted or written."""
    before = sorted(p.name for p in _packages(baseline["out"]))
    with pytest.raises(ValueError, match="--overwrite"):
        _run(baseline["project"], run_id="again")
    assert sorted(p.name for p in _packages(baseline["out"])) == before
    assert _read_json(baseline["out"] / "metrics.json")["run_id"] == "test1"


def test_overwrite_replaces_the_previous_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, run_id="first")

    metrics = _run(project, run_id="second", overwrite=True)

    out = project / "out"
    assert metrics["run_id"] == "second"
    assert metrics["generated"] == 5  # rank_k and pair_compare were added; see above
    assert len(_read_jsonl(out / "validation.jsonl")) == 5
    kept = len(list((out / "tasks").iterdir()))
    assert len(_read_jsonl(out / "tasks.jsonl")) == kept


def test_blocklisted_domain_title_stops_the_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    domain = project / "configs" / "domains" / "tourism.toml"
    domain.write_text(
        domain.read_text(encoding="utf-8").replace(
            "International tourist arrivals", "Election arrivals"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="election"):
        _run(project)
    assert not (project / "out").exists()


def test_domain_that_does_not_enable_a_family_generates_nothing(tmp_path: Path) -> None:
    """A domain without the bar family yields no packages, with the reason recorded."""
    run_config = RUN_CONFIG.replace('domains = ["tourism"]', 'domains = ["tourism_line"]')
    project = _make_project(tmp_path, run_config=run_config)
    domain_text = (project / "configs" / "domains" / "tourism.toml").read_text(encoding="utf-8")
    (project / "configs" / "domains" / "tourism_line.toml").write_text(
        domain_text.replace('families = ["bar", "line"]', 'families = ["line"]'),
        encoding="utf-8",
    )

    metrics = _run(project)

    assert metrics["generated"] == 0
    assert metrics["passed"] == 0
    assert metrics["yield"] == 0.0
    assert metrics["skipped"] == ["domain tourism_line does not enable family bar"]
    assert (project / "out" / "validation.jsonl").read_bytes() == b""


def test_cli_run_prints_metrics_json_and_a_summary_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _make_project(tmp_path)

    assert main(_cli_args(project, "cli1")) == 0

    captured = capsys.readouterr()
    metrics = json.loads(captured.out)
    assert metrics["run_id"] == "cli1"
    assert metrics["generated"] == 5  # rank_k and pair_compare were added; see above
    assert captured.err.startswith("run cli1: generated 5, ")


def test_cli_refuses_existing_output_unless_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _make_project(tmp_path)
    assert main(_cli_args(project, "first")) == 0
    capsys.readouterr()

    assert main(_cli_args(project, "second")) == 2
    assert "--overwrite" in capsys.readouterr().err

    assert main(_cli_args(project, "second", "--overwrite")) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "second"


@needs_tesseract
def test_value_lookup_and_extremum_packages_pass_every_check(baseline: dict[str, Any]) -> None:
    out = baseline["out"]
    rejected = {
        package.name: [
            check["check"]
            for check in _read_json(package / "validation.json")["checks"]
            if not check["passed"]
        ]
        for package in (out / "rejected").iterdir()
    }
    assert rejected == {}, f"rejected packages and their failed checks: {rejected}"

    packages = sorted((out / "tasks").iterdir())
    assert len(packages) == 5  # rank_k and pair_compare were added; see the count test
    task_types = sorted(_read_json(p / "task.json")["task_type"] for p in packages)
    assert task_types == ["extremum", "extremum", "rank_k", "value_lookup", "value_lookup"]

    for package in packages:
        validation = _read_json(package / "validation.json")
        assert validation["passed"] is True
        assert validation["package_id"] == package.name
        assert [check["check"] for check in validation["checks"]] == list(CHECK_NAMES)
        assert all(check["passed"] for check in validation["checks"])
        task = _read_json(package / "task.json")
        assert _caption_texts(package) == [task["question"]]

    index = _read_jsonl(out / "tasks.jsonl")
    assert sorted(record["package_id"] for record in index) == [p.name for p in packages]


@needs_tesseract
def test_line_only_run_generates_series_at_x_and_every_package_passes(tmp_path: Path) -> None:
    project = _make_project(tmp_path, run_config=LINE_RUN_CONFIG)

    metrics = _run(project, overwrite=True)

    out = project / "out"
    assert metrics["generated"] >= 1
    assert metrics["skipped"] == []
    assert metrics["passed"] == metrics["generated"]
    assert metrics["rejected"] == 0
    assert set(metrics["per_check"]) == set(LINE_CHECK_NAMES)

    rejected = {
        package.name: [
            check["check"]
            for check in _read_json(package / "validation.json")["checks"]
            if not check["passed"]
        ]
        for package in (out / "rejected").iterdir()
    }
    assert rejected == {}, f"rejected packages and their failed checks: {rejected}"

    packages = sorted((out / "tasks").iterdir())
    assert len(packages) == metrics["generated"]
    for package in packages:
        task = _read_json(package / "task.json")
        assert task["family"] == "line"
        assert task["task_type"] == "series_at_x"
        validation = _read_json(package / "validation.json")
        assert validation["passed"] is True
        assert [check["check"] for check in validation["checks"]] == list(LINE_CHECK_NAMES)
        assert _caption_texts(package) == [task["question"]]

    index = _read_jsonl(out / "tasks.jsonl")
    assert sorted(record["package_id"] for record in index) == [p.name for p in packages]


def test_each_question_type_is_asked_only_of_its_family(tmp_path: Path) -> None:
    """value_lookup goes to the bar specs and series_at_x to the line specs, with no crash or skip."""
    project = _make_project(tmp_path, run_config=MIXED_RUN_CONFIG)

    metrics = _run(project)

    pairs = sorted(
        (task["family"], task["task_type"])
        for task in (_read_json(package / "task.json") for package in _packages(project / "out"))
    )
    assert metrics["skipped"] == []
    assert metrics["generated"] == len(pairs)
    assert set(pairs) <= {("bar", "value_lookup"), ("line", "series_at_x")}
    assert pairs.count(("bar", "value_lookup")) == 2  # one per bar spec; bar always has the question


# rank_k and pair_compare on bar specs. With this seed the four bar specs cover both
# orientations and charts of four to seven categories, so the bar check list runs on
# each shape.
RANK_PAIR_RUN_CONFIG = """\
run_seed = 20261206
tasks_per_cell = 4
question_in_image = true
families = ["bar"]
domains = ["tourism"]
question_types = ["rank_k", "pair_compare"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
"""


def test_rank_k_and_pair_compare_are_asked_and_not_skipped(tmp_path: Path) -> None:
    project = _make_project(tmp_path, run_config=RANK_PAIR_RUN_CONFIG)

    metrics = _run(project)

    task_types = {
        _read_json(package / "task.json")["task_type"] for package in _packages(project / "out")
    }
    assert metrics["skipped"] == []
    assert metrics["generated"] == metrics["passed"] + metrics["rejected"] > 0
    assert task_types == {"rank_k", "pair_compare"}


@needs_tesseract
def test_rank_k_and_pair_compare_packages_pass_every_check(tmp_path: Path) -> None:
    project = _make_project(tmp_path, run_config=RANK_PAIR_RUN_CONFIG)

    metrics = _run(project)

    out = project / "out"
    rejected = {
        package.name: [
            check["check"]
            for check in _read_json(package / "validation.json")["checks"]
            if not check["passed"]
        ]
        for package in (out / "rejected").iterdir()
    }
    assert rejected == {}, f"rejected packages and their failed checks: {rejected}"
    assert metrics["rejected"] == 0

    packages = sorted((out / "tasks").iterdir())
    assert len(packages) == metrics["generated"]
    for package in packages:
        task = _read_json(package / "task.json")
        assert task["task_type"] in {"rank_k", "pair_compare"}
        validation = _read_json(package / "validation.json")
        assert validation["passed"] is True
        assert [check["check"] for check in validation["checks"]] == list(CHECK_NAMES)
        assert _caption_texts(package) == [task["question"]]


# --- near-duplicate filter and variation metrics -------------------------------------

# The demo's families and question types with fewer specs per cell, and the
# near-duplicate limit written out.
DEMO_LIKE_CONFIG = """\
run_seed = 20261206
tasks_per_cell = 3
question_in_image = true
families = ["bar", "line"]
domains = ["tourism"]
question_types = ["value_lookup", "extremum", "rank_k", "pair_compare", "series_at_x"]

[checks]
ambiguity_min_margin = 0.05
min_font_px = 9
near_dup_phash_max = 6
"""

VARIATION_KEYS = {
    "cell_coverage",
    "near_duplicates_removed",
    "question_type_entropy",
    "reasoning_depth_histogram",
    "structural_difference",
}


def _candidates(project: Path) -> list[tuple[str, str, int]]:
    """(family, task type, spec index) of every candidate the run stages.

    Worked out from the sampler and the question templates alone, in the same
    order the pipeline uses, so the test does not depend on the pipeline's own
    bookkeeping.
    """
    run_cfg = load_run_config(_config_path(project))
    domain = load_domain(project / "configs" / "domains" / "tourism.toml")
    min_margin = run_cfg.checks.get("ambiguity_min_margin", 0.05)
    found: list[tuple[str, str, int]] = []
    for family in dict.fromkeys(run_cfg.families):
        if family not in domain.families:
            continue
        for spec in sample_batch(run_cfg, domain, family, run_cfg.tasks_per_cell):
            for task in make_questions(spec, min_margin=min_margin):
                if task["task_type"] in run_cfg.question_types:
                    found.append((family, task["task_type"], spec["index"]))
    return found


def _package_name(family: str, task_type: str, index: int) -> str:
    return f"{family}-tourism-{index:06d}-{task_type}"


def test_near_duplicates_are_removed_before_checks_and_never_packaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path, run_config=DEMO_LIKE_CONFIG)
    candidates = _candidates(project)
    groups = {(family, task_type) for family, task_type, _ in candidates}
    # Every picture hashes to the same value, so only the first candidate of each
    # family and task type can survive the filter.
    monkeypatch.setattr(variation, "phash", lambda png_path: 0)

    metrics = _run(project)

    out = project / "out"
    assert len(candidates) > len(groups)  # there really are candidates to remove
    assert metrics["near_duplicates_removed"] == len(candidates) - len(groups)
    assert metrics["generated"] == len(groups)
    assert metrics["passed"] + metrics["rejected"] == metrics["generated"]

    first_index = {
        group: min(index for family, task_type, index in candidates if (family, task_type) == group)
        for group in groups
    }
    expected = sorted(
        _package_name(family, task_type, index)
        for (family, task_type), index in first_index.items()
    )
    assert sorted(p.name for p in _packages(out)) == expected
    assert len(_read_jsonl(out / "validation.jsonl")) == len(groups)
    assert not (out / "staging").exists()

    assert metrics["variation"]["near_duplicates_removed"] == metrics["near_duplicates_removed"]
    assert set(metrics["variation"]) == VARIATION_KEYS
    assert _read_json(out / "metrics.json") == metrics


def test_default_near_duplicate_limit_applies_when_the_config_has_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path)  # RUN_CONFIG sets no near_dup_phash_max
    monkeypatch.setattr(variation, "phash", lambda png_path: 0)

    metrics = _run(project)

    groups = {(family, task_type) for family, task_type, _ in _candidates(project)}
    assert metrics["near_duplicates_removed"] > 0
    assert metrics["generated"] == len(groups)


def test_invalid_near_duplicate_limit_is_refused_before_anything_is_deleted(tmp_path: Path) -> None:
    project = _make_project(tmp_path, run_config=RUN_CONFIG + "near_dup_phash_max = -1\n")
    kept = project / "out" / "tasks" / "kept-package"
    kept.mkdir(parents=True)

    with pytest.raises(ConfigError, match="near_dup_phash_max"):
        _run(project, overwrite=True)

    assert kept.is_dir()
