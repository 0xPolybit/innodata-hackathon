"""Tests for the seeded bar and line spec sampler."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from taskfactory.config import DomainConfig, RunConfig, load_domain, load_run_config
from taskfactory.sampler import (
    SPEC_VERSION,
    format_value,
    sample_batch,
    sample_spec,
    task_seed,
    validate_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "configs"
RUN_PATH = CONFIGS / "runs" / "demo.toml"
DOMAIN_PATH = CONFIGS / "domains" / "tourism.toml"


@pytest.fixture(scope="module")
def configs() -> tuple[RunConfig, DomainConfig]:
    """Load the demo run and tourism domain once for the module."""
    return load_run_config(RUN_PATH), load_domain(DOMAIN_PATH)


def test_same_inputs_give_identical_spec(configs: tuple[RunConfig, DomainConfig]) -> None:
    run_cfg, domain_cfg = configs

    for family in ("bar", "line"):
        first = sample_spec(run_cfg, domain_cfg, family, 3)
        second = sample_spec(run_cfg, domain_cfg, family, 3)

        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_task_seed_is_stable_and_family_specific() -> None:
    seed = task_seed(20261206, "bar", "tourism", 7)

    assert seed == task_seed(20261206, "bar", "tourism", 7)
    assert seed != task_seed(20261206, "line", "tourism", 7)
    assert 0 <= seed < 2**32


def test_domain_name_drives_seed_and_spec(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    tourism = replace(domain_cfg, name="tourism")
    energy = replace(domain_cfg, name="energy")

    for family in ("bar", "line"):
        tourism_spec = sample_spec(run_cfg, tourism, family, 4)
        energy_spec = sample_spec(run_cfg, energy, family, 4)

        assert tourism_spec["domain"] == "tourism"
        assert energy_spec["domain"] == "energy"
        assert tourism_spec["seed"] == task_seed(
            run_cfg.run_seed, family, "tourism", 4
        )
        assert energy_spec["seed"] == task_seed(
            run_cfg.run_seed, family, "energy", 4
        )
        assert tourism_spec["seed"] != energy_spec["seed"]


def test_adding_a_family_does_not_change_bar_specs(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    before = replace(run_cfg, families=["bar"])
    after = replace(run_cfg, families=["bar", "line"])

    for index in range(20):
        assert sample_spec(before, domain_cfg, "bar", index) == sample_spec(
            after, domain_cfg, "bar", index
        )


def test_adding_a_domain_family_does_not_change_bar_specs(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    before = replace(domain_cfg, families=["bar"])
    after = replace(domain_cfg, families=["bar", "line"])

    for index in range(20):
        assert sample_spec(run_cfg, before, "bar", index) == sample_spec(
            run_cfg, after, "bar", index
        )


def test_format_value() -> None:
    assert format_value(45_200_000, "{:.1f}M") == "45.2M"
    assert format_value(45_200_000, "{:,}") == "45,200,000"
    assert format_value(1_234_567, "{:.2f}M") == "1.23M"
    assert format_value(999, "{:d}") == "999"


def test_every_sampled_spec_validates(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for family in ("bar", "line"):
        for index in range(200):
            spec = sample_spec(run_cfg, domain_cfg, family, index)
            validate_spec(spec)

            assert spec["spec_version"] == SPEC_VERSION
            assert spec["family"] == family
            assert spec["domain"] == "tourism"
            assert spec["index"] == index
            assert spec["seed"] == task_seed(
                run_cfg.run_seed, family, "tourism", index
            )
            assert spec["question_in_image"] is True


def test_bar_specs_have_one_series_and_distinct_values(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for index in range(100):
        spec = sample_spec(run_cfg, domain_cfg, "bar", index)

        assert spec["family"] == "bar"
        assert len(spec["series"]) == 1

        series = spec["series"][0]
        values = series["values"]

        assert series["name"] == ""
        assert len(values) == len(spec["x_labels"]) == len(series["labels"])
        assert len(set(values)) == len(values)
        assert all(
            domain_cfg.value_range[0] <= value <= domain_cfg.value_range[1]
            for value in values
        )
        assert len(spec["x_labels"]) == len(set(spec["x_labels"]))
        assert set(spec["x_labels"]).issubset(domain_cfg.categories)
        assert spec["orientation"] in ("vertical", "horizontal")
        assert spec["x_label_rotation"] in (0, 30)
        assert "{year}" not in spec["title"]
        assert any(
            str(year) in spec["title"] for year in range(2015, 2025)
        )


def _relative_margin(values: list[int]) -> float:
    """Mirror of the sampler's ``(max - second) / max`` rule."""
    largest, second = sorted(values, reverse=True)[:2]
    return (largest - second) / largest


def test_bar_specs_keep_the_ambiguity_margin(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    threshold = run_cfg.checks.get("ambiguity_min_margin", 0.05)
    assert threshold == 0.05

    for index in range(500):
        spec = sample_spec(run_cfg, domain_cfg, "bar", index)

        assert _relative_margin(spec["series"][0]["values"]) >= 0.05


def test_bar_sampler_meets_a_strict_margin(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    strict = replace(
        run_cfg, checks={**run_cfg.checks, "ambiguity_min_margin": 0.5}
    )
    wide = replace(domain_cfg, value_range=(1, 1_000_000_000), value_format="{:d}")

    spec = sample_spec(strict, wide, "bar", 0)

    validate_spec(spec)
    assert _relative_margin(spec["series"][0]["values"]) >= 0.5


def test_bar_sampler_raises_when_the_margin_is_unreachable(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    impossible = replace(
        run_cfg, checks={**run_cfg.checks, "ambiguity_min_margin": 1.5}
    )

    with pytest.raises(ValueError) as excinfo:
        sample_spec(impossible, domain_cfg, "bar", 2)

    message = str(excinfo.value)
    assert "bar" in message
    assert domain_cfg.name in message
    assert "2" in message


def test_sampling_the_same_index_twice_is_identical(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for index in (0, 1, 7, 42):
        assert sample_spec(run_cfg, domain_cfg, "bar", index) == sample_spec(
            run_cfg, domain_cfg, "bar", index
        )


def test_line_specs_have_two_or_three_equal_series(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for index in range(100):
        spec = sample_spec(run_cfg, domain_cfg, "line", index)

        assert spec["family"] == "line"
        assert spec["orientation"] == "vertical"
        assert spec["x_label_rotation"] in (0, 30)
        assert 2 <= len(spec["series"]) <= 3
        assert 6 <= len(spec["x_labels"]) <= 10
        assert spec["x_labels"][-1] == "2025"

        years = [int(label) for label in spec["x_labels"]]
        assert years == list(range(years[0], years[0] + len(years)))

        names = []
        for series in spec["series"]:
            names.append(series["name"])
            assert series["name"] in domain_cfg.categories
            assert len(series["values"]) == len(spec["x_labels"])
            assert len(series["labels"]) == len(spec["x_labels"])
            assert len(set(series["values"])) == len(series["values"])

        assert len(names) == len(set(names))


def test_line_specs_keep_distinct_columns_and_the_ambiguity_margin(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    threshold = run_cfg.checks.get("ambiguity_min_margin", 0.05)
    assert threshold == 0.05

    for index in range(300):
        spec = sample_spec(run_cfg, domain_cfg, "line", index)
        validate_spec(spec)

        columns = zip(*(series["values"] for series in spec["series"]))
        for column in columns:
            values = list(column)
            assert len(set(values)) == len(values)
            assert _relative_margin(values) >= 0.05


def test_line_sampling_the_same_index_twice_is_identical(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for index in (0, 1, 7, 42):
        assert sample_spec(run_cfg, domain_cfg, "line", index) == sample_spec(
            run_cfg, domain_cfg, "line", index
        )


def test_line_sampler_raises_when_the_margin_is_unreachable(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    impossible = replace(
        run_cfg, checks={**run_cfg.checks, "ambiguity_min_margin": 1.5}
    )

    with pytest.raises(ValueError) as excinfo:
        sample_spec(impossible, domain_cfg, "line", 2)

    message = str(excinfo.value)
    assert "line" in message
    assert domain_cfg.name in message
    assert "2" in message


def test_bar_specs_are_unaffected_by_line_sampling(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs

    for index in (0, 1, 7, 42):
        first = sample_spec(run_cfg, domain_cfg, "bar", index)
        sample_spec(run_cfg, domain_cfg, "line", index)
        second = sample_spec(run_cfg, domain_cfg, "bar", index)

        assert first == second
        assert first["series"][0]["values"] == second["series"][0]["values"]


def test_sample_batch_indexes_in_order(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    batch = sample_batch(run_cfg, domain_cfg, "bar", 5)

    assert [spec["index"] for spec in batch] == list(range(5))
    assert batch[2] == sample_spec(run_cfg, domain_cfg, "bar", 2)


def test_unknown_family_raises(configs: tuple[RunConfig, DomainConfig]) -> None:
    run_cfg, domain_cfg = configs

    with pytest.raises(ValueError):
        sample_spec(run_cfg, domain_cfg, "pie", 0)
    with pytest.raises(ValueError):
        sample_spec(run_cfg, domain_cfg, "floorplan", 0)


def test_family_not_enabled_for_domain_raises(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    bar_only = DomainConfig(
        title=domain_cfg.title,
        categories=domain_cfg.categories,
        value_range=domain_cfg.value_range,
        value_format=domain_cfg.value_format,
        families=["bar"],
        name=domain_cfg.name,
    )

    with pytest.raises(ValueError):
        sample_spec(run_cfg, bar_only, "line", 0)


def test_validate_rejects_duplicate_values(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    spec = sample_spec(run_cfg, domain_cfg, "bar", 0)
    spec["series"][0]["values"][1] = spec["series"][0]["values"][0]

    with pytest.raises(ValueError, match="duplicate"):
        validate_spec(spec)


def test_validate_rejects_bar_with_two_series(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    spec = sample_spec(run_cfg, domain_cfg, "bar", 0)
    spec["series"].append(dict(spec["series"][0]))

    with pytest.raises(ValueError, match="exactly one series"):
        validate_spec(spec)


def test_validate_rejects_horizontal_line(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    spec = sample_spec(run_cfg, domain_cfg, "line", 0)
    spec["orientation"] = "horizontal"

    with pytest.raises(ValueError, match="vertical"):
        validate_spec(spec)


def test_validate_rejects_label_count_mismatch(
    configs: tuple[RunConfig, DomainConfig],
) -> None:
    run_cfg, domain_cfg = configs
    spec = sample_spec(run_cfg, domain_cfg, "bar", 0)
    spec["series"][0]["labels"].pop()

    with pytest.raises(ValueError, match="differ in length"):
        validate_spec(spec)


def test_default_cap_keeps_the_pool_spec_it_drew_before_the_key_existed() -> None:
    run_cfg = load_run_config(CONFIGS / "runs" / "pool.toml")
    domain_cfg = load_domain(CONFIGS / "domains" / "tourism.toml")

    assert run_cfg.bar_max_categories == 8
    assert sample_spec(run_cfg, domain_cfg, "bar", 0) == {
        "domain": "tourism",
        "family": "bar",
        "index": 0,
        "orientation": "horizontal",
        "question_in_image": True,
        "seed": 3498640343,
        "series": [
            {
                "labels": ["31.5M", "67.4M", "23.8M", "79.8M", "2.5M"],
                "name": "",
                "values": [31485119, 67365801, 23792964, 79782391, 2522023],
            }
        ],
        "spec_version": 1,
        "title": "International tourist arrivals (2015)",
        "x_label_rotation": 30,
        "x_labels": ["Spain", "Italy", "Germany", "France", "Japan"],
    }


def test_bar_max_categories_caps_the_bar_count() -> None:
    default_run = load_run_config(CONFIGS / "runs" / "hard.toml")
    wide_run = load_run_config(CONFIGS / "runs" / "hard2.toml")
    energy = load_domain(CONFIGS / "domains" / "energy_hard.toml")  # 16 categories
    tourism = load_domain(CONFIGS / "domains" / "tourism.toml")  # 8 categories

    def bar_counts(run_cfg: RunConfig, domain_cfg: DomainConfig) -> set[int]:
        return {
            len(sample_spec(run_cfg, domain_cfg, "bar", index)["x_labels"])
            for index in range(200)
        }

    assert bar_counts(default_run, energy) == set(range(4, 9))
    assert bar_counts(wide_run, energy) == set(range(4, 13))
    # The domain has only 8 categories, so the cap of 12 cannot add more.
    assert bar_counts(wide_run, tourism) == set(range(4, 9))


def test_wide_bar_specs_validate_and_keep_the_margin() -> None:
    run_cfg = load_run_config(CONFIGS / "runs" / "hard2.toml")
    energy = load_domain(CONFIGS / "domains" / "energy_hard.toml")

    for index in range(200):
        spec = sample_spec(run_cfg, energy, "bar", index)
        validate_spec(spec)

        assert _relative_margin(spec["series"][0]["values"]) >= 0.02


def test_sampler_refuses_a_cap_outside_the_range() -> None:
    run_cfg = load_run_config(CONFIGS / "runs" / "demo.toml")
    domain_cfg = load_domain(CONFIGS / "domains" / "tourism.toml")

    with pytest.raises(ValueError, match="bar_max_categories"):
        sample_spec(replace(run_cfg, bar_max_categories=1), domain_cfg, "bar", 0)


def test_validate_spec_accepts_twenty_bars_and_rejects_twenty_one() -> None:
    run_cfg = load_run_config(CONFIGS / "runs" / "demo.toml")
    domain_cfg = load_domain(CONFIGS / "domains" / "energy.toml")

    def with_bars(count: int) -> dict:
        spec = sample_spec(run_cfg, domain_cfg, "bar", 0)
        values = [1000 + 7 * position for position in range(count)]
        spec["x_labels"] = [f"Bar {position}" for position in range(count)]
        spec["series"][0]["values"] = values
        spec["series"][0]["labels"] = [str(value) for value in values]
        return spec

    validate_spec(with_bars(20))
    with pytest.raises(ValueError, match="between 1 and 20"):
        validate_spec(with_bars(21))
