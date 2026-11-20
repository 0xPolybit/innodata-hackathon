"""Tests for bar and line question templates and their ground-truth answers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from taskfactory.checks_layout import rank_from_question
from taskfactory.config import load_domain, load_run_config
from taskfactory.questions import make_questions, normalise_answer
from taskfactory.sampler import sample_batch, validate_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = REPO_ROOT / "configs" / "runs" / "demo.toml"
DOMAIN_PATH = REPO_ROOT / "configs" / "domains" / "tourism.toml"

TASK_KEYS = frozenset(
    {
        "task_type",
        "family",
        "domain",
        "spec_index",
        "question",
        "answer",
        "answer_value",
        "answer_category",
        "reasoning_steps",
        "answer_printed_in_image",
        "question_in_image",
    }
)

LINE_TASK_KEYS = TASK_KEYS | {"year"}

X_LABELS = ["France", "Spain", "Italy", "Japan"]
VALUES = [40_600_000, 82_700_000, 64_500_000, 31_100_000]
LABELS = ["40.6M", "82.7M", "64.5M", "31.1M"]

LINE_YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]
LINE_SERIES = [
    {
        "name": "France",
        "values": [50, 40, 30, 20, 10, 5],
        "labels": ["50", "40", "30", "20", "10", "5"],
    },
    {
        "name": "Spain",
        "values": [10, 30, 45, 25, 15, 12],
        "labels": ["10", "30", "45", "25", "15", "12"],
    },
    {
        "name": "Italy",
        "values": [20, 25, 35, 30, 12, 8],
        "labels": ["20", "25", "35", "30", "12", "8"],
    },
]


def bar_spec(
    *,
    seed: int = 5,
    index: int = 0,
    domain: str = "tourism",
    values: list[int] | None = None,
    labels: list[str] | None = None,
    x_labels: list[str] | None = None,
    question_in_image: bool = True,
) -> dict[str, Any]:
    """Build a hand-made bar spec with valid, distinct default data."""
    return {
        "spec_version": 1,
        "family": "bar",
        "domain": domain,
        "index": index,
        "seed": seed,
        "title": "International tourist arrivals (2024)",
        "x_labels": list(X_LABELS if x_labels is None else x_labels),
        "series": [
            {
                "name": "",
                "values": list(VALUES if values is None else values),
                "labels": list(LABELS if labels is None else labels),
            }
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": question_in_image,
    }


def line_spec(
    *,
    seed: int = 0,
    index: int = 0,
    domain: str = "tourism",
    series: list[dict[str, Any]] | None = None,
    question_in_image: bool = True,
) -> dict[str, Any]:
    """Build a hand-made three-series line spec over six consecutive years."""
    source = LINE_SERIES if series is None else series
    return {
        "spec_version": 1,
        "family": "line",
        "domain": domain,
        "index": index,
        "seed": seed,
        "title": "International tourist arrivals (2024)",
        "x_labels": list(LINE_YEARS),
        "series": [
            {
                "name": item["name"],
                "values": list(item["values"]),
                "labels": list(item["labels"]),
            }
            for item in source
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": question_in_image,
    }


def tasks_by_type(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map each task's type to the task itself."""
    return {task["task_type"]: task for task in make_questions(spec)}


@pytest.mark.parametrize("seed", [0, 5, 6, 7])
def test_value_lookup_uses_the_seeded_category(seed: int) -> None:
    spec = bar_spec(seed=seed)
    lookup = tasks_by_type(spec)["value_lookup"]
    position = seed % len(spec["x_labels"])

    assert lookup["question"] == f"What value is shown for {X_LABELS[position]}?"
    assert lookup["answer"] == LABELS[position]
    assert lookup["answer_value"] == VALUES[position]
    assert lookup["answer_category"] == X_LABELS[position]


def test_extremum_is_the_argmax_category() -> None:
    spec = bar_spec()
    extremum = tasks_by_type(spec)["extremum"]
    best = VALUES.index(max(VALUES))

    assert extremum["question"] == "Which category has the highest value?"
    assert extremum["answer"] == X_LABELS[best] == "Spain"
    assert extremum["answer_value"] == max(VALUES)
    assert extremum["answer_category"] == X_LABELS[best]


def test_task_shape_and_metadata() -> None:
    spec = bar_spec(index=17, domain="tourism")

    tasks = make_questions(spec)
    assert [task["task_type"] for task in tasks] == [
        "value_lookup",
        "extremum",
        "rank_k",
        "pair_compare",
    ]

    allowed_answers = set(LABELS) | set(X_LABELS)
    for task in tasks:
        assert set(task) == TASK_KEYS
        assert task["family"] == "bar"
        assert task["domain"] == spec["domain"]
        assert task["spec_index"] == spec["index"]
        assert task["answer"] in allowed_answers
        assert isinstance(task["answer"], str)
        assert isinstance(task["answer_value"], int)
        assert not isinstance(task["answer_value"], bool)
        assert task["answer_printed_in_image"] is True
        assert task["question_in_image"] is spec["question_in_image"]
        assert task["question"].endswith("?")


def test_rank_k_is_the_category_at_the_seeded_rank() -> None:
    """seed 5 with four categories asks for rank (5 % 2) + 2 == 3."""
    spec = bar_spec(seed=5)
    rank_k = tasks_by_type(spec)["rank_k"]

    assert rank_k["question"] == "Which category ranks third by value?"
    assert rank_k["answer"] == "France"
    assert rank_k["answer_value"] == 40_600_000
    assert rank_k["answer_category"] == "France"
    assert rank_k["reasoning_steps"] == len(spec["x_labels"]) == 4
    assert rank_k["answer_printed_in_image"] is True


def test_rank_k_gap_below_margin_is_skipped() -> None:
    spec = bar_spec(
        seed=0,
        values=[100, 50, 49, 10],
        labels=["100", "50", "49", "10"],
    )

    tasks = tasks_by_type(spec)

    # Rank 2 (50) is only 1/50 == 0.02 above rank 3 (49).
    assert "rank_k" not in tasks
    assert "pair_compare" in tasks


def test_pair_compare_answers_with_the_larger_value() -> None:
    spec = bar_spec()
    pair = tasks_by_type(spec)["pair_compare"]

    # 82.7M and 31.1M are the widest relative pair.
    assert pair["question"] == "Which is higher, Spain or Japan?"
    assert pair["answer"] == "Spain"
    assert pair["answer_value"] == 82_700_000
    assert pair["answer_category"] == "Spain"
    assert pair["reasoning_steps"] == 2
    assert pair["answer_printed_in_image"] is True


def test_pair_compare_gap_below_margin_is_skipped() -> None:
    spec = bar_spec(
        values=[100, 99, 98, 97],
        labels=["100", "99", "98", "97"],
    )

    tasks = tasks_by_type(spec)

    # The widest pair differs by only 3/100 == 0.03.
    assert "pair_compare" not in tasks
    assert "rank_k" not in tasks


def test_reasoning_steps_match_the_question_type() -> None:
    spec = bar_spec(
        x_labels=["A", "B", "C", "D", "E", "F"],
        values=[1, 2, 3, 4, 5, 6],
        labels=["1", "2", "3", "4", "5", "6"],
    )
    tasks = tasks_by_type(spec)

    assert tasks["value_lookup"]["reasoning_steps"] == 1
    assert tasks["extremum"]["reasoning_steps"] == len(spec["x_labels"]) == 6
    assert tasks["rank_k"]["reasoning_steps"] == len(spec["x_labels"]) == 6
    assert tasks["pair_compare"]["reasoning_steps"] == 2


def test_question_in_image_follows_the_spec() -> None:
    spec = bar_spec(question_in_image=False)

    for task in make_questions(spec):
        assert task["question_in_image"] is False


@pytest.mark.parametrize("family", ["floorplan", "pie"])
def test_unsupported_family_raises(family: str) -> None:
    spec = bar_spec()
    spec["family"] = family

    with pytest.raises(ValueError, match="bar"):
        make_questions(spec)


def test_series_at_x_uses_the_seeded_year() -> None:
    """seed 2 asks about 2022, where Spain is the highest series."""
    spec = line_spec(seed=2, index=41)

    tasks = make_questions(spec)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["task_type"] == "series_at_x"
    assert task["family"] == "line"
    assert task["domain"] == spec["domain"]
    assert task["spec_index"] == 41
    assert task["question"] == "Which series is highest in 2022?"
    assert task["year"] == "2022"
    assert task["answer"] == "Spain"
    assert task["answer_value"] == 45
    assert task["answer_category"] == "Spain"
    assert task["reasoning_steps"] == len(spec["series"]) == 3
    assert task["answer_printed_in_image"] is True
    assert task["question_in_image"] is True
    assert set(task) == LINE_TASK_KEYS


@pytest.mark.parametrize("seed", range(len(LINE_YEARS)))
def test_series_at_x_answers_with_the_highest_series(seed: int) -> None:
    spec = line_spec(seed=seed)
    position = spec["seed"] % len(spec["x_labels"])
    column = [item["values"][position] for item in spec["series"]]
    expected = spec["series"][column.index(max(column))]

    task = make_questions(spec)[0]

    assert task["year"] == spec["x_labels"][position]
    assert task["answer"] == expected["name"]
    assert task["answer_value"] == expected["values"][position]


def test_series_at_x_gap_below_margin_is_skipped() -> None:
    spec = line_spec(
        seed=0,
        series=[
            {"name": "France", "values": [100, 10, 10, 10, 10, 10], "labels": []},
            {"name": "Spain", "values": [98, 10, 10, 10, 10, 10], "labels": []},
            {"name": "Italy", "values": [5, 10, 10, 10, 10, 10], "labels": []},
        ],
    )

    # 100 and 98 differ by only 2/100 == 0.02.
    assert make_questions(spec) == []
    assert make_questions(spec, min_margin=0.01)[0]["answer"] == "France"


def test_series_at_x_shared_maximum_raises() -> None:
    spec = line_spec(
        seed=0,
        series=[
            {"name": "France", "values": [100, 1, 1, 1, 1, 1], "labels": []},
            {"name": "Spain", "values": [100, 1, 1, 1, 1, 1], "labels": []},
            {"name": "Italy", "values": [5, 1, 1, 1, 1, 1], "labels": []},
        ],
    )

    with pytest.raises(ValueError, match="not unique"):
        make_questions(spec)


def test_line_question_in_image_follows_the_spec() -> None:
    task = make_questions(line_spec(question_in_image=False))[0]

    assert task["question_in_image"] is False


def test_duplicate_maximum_raises() -> None:
    spec = bar_spec(
        values=[10, 30, 30, 5],
        labels=["10", "30", "30", "5"],
    )

    with pytest.raises(ValueError, match="not unique"):
        make_questions(spec)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Spain. ", "spain"),
        ("New   York", "new york"),
        ("40.6M", "40.6m"),
        ("\tFrance \n", "france"),
        ("already normalised", "already normalised"),
    ],
)
def test_normalise_answer(raw: str, expected: str) -> None:
    assert normalise_answer(raw) == expected


def test_sampled_bar_specs_all_get_ground_truth_answers() -> None:
    run_cfg = load_run_config(RUN_PATH)
    domain_cfg = load_domain(DOMAIN_PATH)
    specs = sample_batch(run_cfg, domain_cfg, "bar", 200)

    assert len(specs) == 200
    implemented = ["value_lookup", "extremum", "rank_k", "pair_compare"]
    seen_types: set[str] = set()
    for spec in specs:
        tasks = make_questions(spec)
        task_types = [task["task_type"] for task in tasks]
        assert task_types == [name for name in implemented if name in task_types]
        assert {"value_lookup", "extremum", "pair_compare"} <= set(task_types)
        seen_types.update(task_types)

        allowed_answers = set(spec["series"][0]["labels"]) | set(spec["x_labels"])
        for task in tasks:
            assert task["answer"] in allowed_answers
            if task["task_type"] in ("rank_k", "pair_compare"):
                assert task["answer"] in spec["x_labels"]
            assert task["domain"] == spec["domain"]
            assert task["spec_index"] == spec["index"]

    assert seen_types == set(implemented)


def test_sampled_line_specs_all_get_ground_truth_answers() -> None:
    run_cfg = load_run_config(RUN_PATH)
    domain_cfg = load_domain(DOMAIN_PATH)
    specs = sample_batch(run_cfg, domain_cfg, "line", 200)

    assert len(specs) == 200
    produced = 0
    for spec in specs:
        assert spec["family"] == "line"
        names = [series["name"] for series in spec["series"]]
        tasks = make_questions(spec)
        assert len(tasks) <= 1
        for task in tasks:
            assert task["task_type"] == "series_at_x"
            assert task["family"] == "line"
            assert task["domain"] == spec["domain"]
            assert task["spec_index"] == spec["index"]
            assert task["answer"] in names
            assert task["answer_category"] == task["answer"]
            assert task["year"] in spec["x_labels"]
            expected_year = spec["x_labels"][spec["seed"] % len(spec["x_labels"])]
            assert task["year"] == expected_year
            position = spec["x_labels"].index(task["year"])
            series = next(
                item for item in spec["series"] if item["name"] == task["answer"]
            )
            assert task["answer_value"] == series["values"][position]
            assert task["answer_value"] == max(
                item["values"][position] for item in spec["series"]
            )
            assert task["reasoning_steps"] == len(spec["series"])
            assert task["answer_printed_in_image"] is True
            assert task["question_in_image"] is spec["question_in_image"]
            assert task["question"].endswith("?")
            produced += 1

    assert produced >= 1


def test_rank_k_names_every_rank_up_to_nineteenth_and_layout_reads_it_back() -> None:
    """A 20-bar chart can ask for ranks second to nineteenth, and checks_layout reads each back."""
    x_labels = [f"Category {position:02d}" for position in range(20)]
    values = [round(1_000_000 * 0.93**position) for position in range(20)]
    labels = [f"{value:,}" for value in values]

    for rank in range(2, 20):
        spec = bar_spec(seed=rank - 2, x_labels=x_labels, values=values, labels=labels)
        validate_spec(spec)

        rank_k = tasks_by_type(spec)["rank_k"]

        assert rank_from_question(rank_k["question"]) == rank
        assert rank_k["answer"] == x_labels[rank - 1]
        assert rank_k["answer_value"] == values[rank - 1]
