"""Tests for taskfactory.variation: the perceptual hash, Hamming distance and variation metrics.

The hash tests draw real bar charts with render.render_bar. The metric tests build
Candidate records by hand, so each expected value can be worked out on paper.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from taskfactory.render import render_bar
from taskfactory.variation import (
    Candidate,
    hamming,
    phash,
    structure_signature,
    variation_metrics,
)

CATEGORIES = ["France", "Spain", "Italy", "Japan"]
VALUES = [45_200_000, 81_100_000, 67_600_000, 30_800_000]
METRIC_KEYS = {
    "cell_coverage",
    "near_duplicates_removed",
    "question_type_entropy",
    "reasoning_depth_histogram",
    "structural_difference",
}


def make_spec(
    categories: list[str] = CATEGORIES,
    values: list[int] = VALUES,
    orientation: str = "vertical",
    rotation: int = 0,
    title: str = "International tourist arrivals (2022)",
) -> dict[str, Any]:
    """A hand-made single-series bar spec whose labels print the values in millions."""
    return {
        "spec_version": 1,
        "family": "bar",
        "domain": "tourism",
        "index": 0,
        "seed": 1,
        "title": title,
        "x_labels": list(categories),
        "series": [
            {
                "name": "",
                "values": list(values),
                "labels": [f"{value / 1_000_000:.1f}M" for value in values],
            }
        ],
        "orientation": orientation,
        "x_label_rotation": rotation,
        "question_in_image": True,
    }


def draw(spec: dict[str, Any], path: Path) -> Path:
    render_bar(spec, path, question="What value is shown for Italy?")
    return path


def candidate(
    package_id: str,
    phash_value: int,
    *,
    structure: tuple[Any, ...] = ("S1",),
    task_type: str = "value_lookup",
    family: str = "bar",
    domain: str = "tourism",
    reasoning_steps: int = 1,
    passed: bool = True,
) -> Candidate:
    return Candidate(
        package_id=package_id,
        family=family,
        domain=domain,
        task_type=task_type,
        phash=phash_value,
        structure=structure,
        reasoning_steps=reasoning_steps,
        passed=passed,
    )


def test_phash_of_the_same_png_twice_is_equal(tmp_path: Path) -> None:
    path = draw(make_spec(), tmp_path / "chart.png")

    assert phash(path) == phash(path)


def test_phash_of_the_same_spec_rendered_twice_is_equal(tmp_path: Path) -> None:
    first = draw(make_spec(), tmp_path / "first.png")
    second = draw(make_spec(), tmp_path / "second.png")

    assert phash(first) == phash(second)


def test_phash_of_a_different_chart_differs_by_more_than_six_bits(tmp_path: Path) -> None:
    original = draw(make_spec(), tmp_path / "original.png")
    other = draw(
        make_spec(
            categories=["Mexico", "Turkey", "Germany", "Thailand", "Japan", "Spain"],
            values=[12_000_000, 55_000_000, 33_000_000, 70_000_000, 8_000_000, 40_000_000],
            orientation="horizontal",
        ),
        tmp_path / "other.png",
    )

    assert hamming(phash(original), phash(other)) > 6


def test_phash_is_a_64_bit_integer_with_a_zero_dc_bit(tmp_path: Path) -> None:
    value = phash(draw(make_spec(), tmp_path / "chart.png"))

    assert isinstance(value, int)
    assert 0 <= value < 2**64
    assert value & 1 == 0  # bit 0 is the DC term, which is never a hash bit


def test_hamming_counts_the_differing_bits() -> None:
    assert hamming(0, 0) == 0
    assert hamming(5, 5) == 0
    assert hamming(0b1011, 0b0010) == 2
    assert hamming(3, 0) == hamming(0, 3) == 2
    assert hamming(0, 2**64 - 1) == 64


def test_structure_signature_compares_the_structural_fields() -> None:
    base = structure_signature(make_spec(values=[5, 9, 7, 3]))

    # Same order of values with different numbers, different names and title: same structure.
    assert structure_signature(make_spec(values=[50, 90, 70, 30])) == base
    assert structure_signature(make_spec(values=[5, 9, 7, 3], title="Other")) == base
    assert (
        structure_signature(make_spec(categories=["A", "B", "C", "D"], values=[5, 9, 7, 3]))
        == base
    )

    assert structure_signature(make_spec(values=[9, 5, 7, 3])) != base  # different sorted order
    assert structure_signature(make_spec(values=[5, 9, 7, 3], orientation="horizontal")) != base
    assert structure_signature(make_spec(values=[5, 9, 7, 3], rotation=30)) != base
    assert (
        structure_signature(
            make_spec(categories=["A", "B", "C", "D", "E"], values=[5, 9, 7, 3, 1])
        )
        != base
    )


def test_cell_coverage_counts_cells_with_five_passed_tasks_over_attempted_cells() -> None:
    candidates = [
        *[candidate(f"v{i}", i, task_type="value_lookup") for i in range(5)],  # covered
        *[candidate(f"e{i}", 100 + i, task_type="extremum") for i in range(4)],  # four passed
        candidate("e4", 200, task_type="extremum", passed=False),
        candidate("s0", 300, family="line", task_type="series_at_x", passed=False),
    ]

    metrics = variation_metrics(candidates, near_duplicates_removed=0)

    # Three attempted cells, one of them covered: 1 / 3.
    assert metrics["cell_coverage"] == 0.3333


def test_cell_coverage_is_zero_when_no_cell_was_attempted() -> None:
    assert variation_metrics([], near_duplicates_removed=0)["cell_coverage"] == 0.0


def test_question_type_entropy_is_normalised_over_the_types_present() -> None:
    even = [
        candidate("a", 1, task_type="value_lookup"),
        candidate("b", 2, task_type="value_lookup"),
        candidate("c", 3, task_type="extremum"),
        candidate("d", 4, task_type="extremum"),
    ]
    assert variation_metrics(even, 0)["question_type_entropy"] == 1.0

    uneven = [
        candidate("a", 1, task_type="value_lookup"),
        candidate("b", 2, task_type="extremum"),
        candidate("c", 3, task_type="rank_k"),
        candidate("d", 4, task_type="rank_k"),
    ]
    shares = [0.25, 0.25, 0.5]
    expected = -sum(p * math.log(p) for p in shares) / math.log(3)
    assert variation_metrics(uneven, 0)["question_type_entropy"] == round(expected, 4)


def test_question_type_entropy_is_zero_for_one_type_and_ignores_rejected_tasks() -> None:
    single = [candidate("a", 1), candidate("b", 2)]
    assert variation_metrics(single, 0)["question_type_entropy"] == 0.0

    mixed = [candidate("a", 1), candidate("b", 2), candidate("c", 3, task_type="extremum", passed=False)]
    assert variation_metrics(mixed, 0)["question_type_entropy"] == 0.0  # only value_lookup passed


def test_structural_difference_counts_nearest_neighbour_pairs_that_differ() -> None:
    candidates = [
        candidate("a", 0x00, structure=("S1",)),
        candidate("b", 0x01, structure=("S1",)),  # nearest to a, same structure
        candidate("c", 0xF0, structure=("S2",)),  # nearest to a (4 bits), other structure
        candidate("d", 0x00, structure=("S2",), passed=False),  # rejected: not a final task
        candidate("e", 0x00, structure=("S2",), family="line", task_type="value_lookup"),
    ]

    metrics = variation_metrics(candidates, 0)

    # Pairs are {a, b} and {a, c}; the second differs, so the share is 1 / 2.
    assert metrics["structural_difference"] == 0.5


def test_structural_difference_is_one_below_two_items() -> None:
    assert variation_metrics([], 0)["structural_difference"] == 1.0
    assert variation_metrics([candidate("a", 1)], 0)["structural_difference"] == 1.0

    # Two tasks of different types have no neighbour within their own type.
    different_types = [candidate("a", 1), candidate("b", 2, task_type="extremum")]
    assert variation_metrics(different_types, 0)["structural_difference"] == 1.0


def test_reasoning_depth_histogram_counts_passed_tasks_only() -> None:
    candidates = [
        candidate("a", 1, reasoning_steps=1),
        candidate("b", 2, reasoning_steps=1),
        candidate("c", 3, reasoning_steps=2),
        candidate("d", 4, reasoning_steps=8),
        candidate("e", 5, reasoning_steps=3, passed=False),
    ]

    histogram = variation_metrics(candidates, 0)["reasoning_depth_histogram"]

    assert histogram == {"1": 2, "2": 1, "8": 1}
    assert list(histogram) == ["1", "2", "8"]


def test_variation_metrics_carry_the_documented_keys_and_removed_count() -> None:
    metrics = variation_metrics([candidate("a", 1)], near_duplicates_removed=7)

    assert set(metrics) == METRIC_KEYS
    assert metrics["near_duplicates_removed"] == 7
    for value in (metrics["cell_coverage"], metrics["question_type_entropy"], metrics["structural_difference"]):
        assert isinstance(value, float)
        assert value == round(value, 4)
