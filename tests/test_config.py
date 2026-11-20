"""Tests for configuration loading and policy checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from taskfactory.config import (
    ConfigError,
    check_blocklist,
    check_no_secondary_in_eval,
    load_blocklist,
    load_domain,
    load_models,
    load_run_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "configs"

VALID_RUN = """\
run_seed = 20261206
tasks_per_cell = 6
question_in_image = true
families = ["bar", "line"]
domains = ["tourism"]
question_types = ["value_lookup", "spatial"]

[checks]
min_font_px = 9
"""

VALID_DOMAIN = """\
title = "Sales by region ({year})"
categories = ["North", "South"]
value_range = [1, 10]
value_format = "{:.1f}"
families = ["bar"]
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Write ``text`` to a temporary config file and return its path."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_demo_run_config_loads() -> None:
    config = load_run_config(CONFIGS / "runs" / "demo.toml")

    assert config.run_seed == 20261206
    assert config.tasks_per_cell == 6
    assert config.question_in_image is True
    assert config.families == ["bar", "line", "floorplan"]
    assert config.domains == ["tourism"]
    assert config.question_types == [
        "value_lookup",
        "extremum",
        "rank_k",
        "pair_compare",
        "series_at_x",
        "spatial",
    ]
    assert config.checks == {
        "ambiguity_min_margin": 0.05,
        "min_font_px": 9,
        "near_dup_phash_max": 6,
    }
    assert config.eval.items_per_model == 200
    assert config.eval.models == "configs/models.toml"
    assert config.eval.stratify_by == ["family", "question_type"]


def test_tourism_domain_loads() -> None:
    domain = load_domain(CONFIGS / "domains" / "tourism.toml")

    assert domain.title == "International tourist arrivals ({year})"
    assert domain.categories == [
        "France",
        "Spain",
        "Italy",
        "Japan",
        "Mexico",
        "Thailand",
        "Turkey",
        "Germany",
    ]
    assert domain.value_range == (2000000, 90000000)
    assert domain.value_format == "{:.1f}M"
    assert domain.families == ["bar", "line"]


def test_tourism_domain_name_is_the_file_stem() -> None:
    domain = load_domain(CONFIGS / "domains" / "tourism.toml")

    assert domain.name == "tourism"


def test_bad_family_name_names_the_key(tmp_path: Path) -> None:
    text = VALID_RUN.replace(
        'families = ["bar", "line"]', 'families = ["bar", "scatter"]'
    )
    with pytest.raises(ConfigError, match="families"):
        load_run_config(_write(tmp_path, "run.toml", text))


def test_missing_run_seed_names_the_key(tmp_path: Path) -> None:
    text = VALID_RUN.replace("run_seed = 20261206\n", "")
    with pytest.raises(ConfigError, match="run_seed"):
        load_run_config(_write(tmp_path, "run.toml", text))


def test_value_range_min_not_less_than_max(tmp_path: Path) -> None:
    text = VALID_DOMAIN.replace("value_range = [1, 10]", "value_range = [10, 10]")
    with pytest.raises(ConfigError, match="value_range"):
        load_domain(_write(tmp_path, "domain.toml", text))


def test_blocklisted_word_in_title_raises(tmp_path: Path) -> None:
    terms = load_blocklist(CONFIGS / "blocklist.txt")
    assert "patient" in terms

    text = VALID_DOMAIN.replace(
        'title = "Sales by region ({year})"',
        'title = "Patient outcomes by region ({year})"',
    )
    domain = load_domain(_write(tmp_path, "domain.toml", text))

    with pytest.raises(ConfigError, match="patient"):
        check_blocklist([domain.title, *domain.categories], terms)


def test_blocklist_is_case_insensitive_and_whole_word() -> None:
    with pytest.raises(ConfigError, match="hate"):
        check_blocklist("HATE speech", ["hate"])
    with pytest.raises(ConfigError, match="political party"):
        check_blocklist("A political party result", ["political party"])
    # A substring inside a longer word is not a whole-word match.
    check_blocklist("Minority report", ["minor"])


def test_check_no_secondary_in_eval_refuses_secondary_id() -> None:
    models = load_models(CONFIGS / "models.toml")
    secondary_ids = [
        model["id"] for model in models if model["role"] == "secondary"
    ]
    evaluated_ids = [
        model["id"] for model in models if model["role"] == "evaluated"
    ]

    assert secondary_ids == ["gemma3:4b"]

    with pytest.raises(ConfigError, match="gemma3:4b"):
        check_no_secondary_in_eval(models, [*evaluated_ids, secondary_ids[0]])

    check_no_secondary_in_eval(models, evaluated_ids)
    check_no_secondary_in_eval(models, None)


def test_load_models_with_eval_ids_refuses_secondary_id() -> None:
    models = load_models(CONFIGS / "models.toml")
    secondary_id = next(
        model["id"] for model in models if model["role"] == "secondary"
    )

    with pytest.raises(ConfigError, match="secondary"):
        load_models(CONFIGS / "models.toml", eval_ids=[secondary_id])


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    text = VALID_RUN.replace("[checks]", "unexpected = 1\n\n[checks]")
    with pytest.raises(ConfigError, match="unexpected"):
        load_run_config(_write(tmp_path, "run.toml", text))


def test_missing_checks_table_is_rejected(tmp_path: Path) -> None:
    text = VALID_RUN.split("[checks]")[0]
    with pytest.raises(ConfigError, match="checks"):
        load_run_config(_write(tmp_path, "run.toml", text))


def test_bar_max_categories_defaults_to_eight() -> None:
    for name in ("demo", "pool", "hard"):
        config = load_run_config(CONFIGS / "runs" / f"{name}.toml")

        assert config.bar_max_categories == 8


def test_bar_max_categories_is_read_from_the_run_config() -> None:
    config = load_run_config(CONFIGS / "runs" / "hard2.toml")

    assert config.bar_max_categories == 12


@pytest.mark.parametrize("value", [2, 20])
def test_bar_max_categories_accepts_both_bounds(tmp_path: Path, value: int) -> None:
    text = VALID_RUN.replace("[checks]", f"bar_max_categories = {value}\n\n[checks]")

    config = load_run_config(_write(tmp_path, "run.toml", text))

    assert config.bar_max_categories == value


@pytest.mark.parametrize(
    ("literal", "message"),
    [
        ("1", "must be at least 2"),
        ("21", "must be at most 20"),
        ("8.0", "expected an integer, got float"),
        ("true", "expected an integer, got boolean"),
        ('"12"', "expected an integer, got string"),
    ],
)
def test_bar_max_categories_must_be_an_integer_from_two_to_twenty(
    tmp_path: Path, literal: str, message: str
) -> None:
    text = VALID_RUN.replace("[checks]", f"bar_max_categories = {literal}\n\n[checks]")

    with pytest.raises(ConfigError, match=f"bar_max_categories: {message}"):
        load_run_config(_write(tmp_path, "run.toml", text))


def test_load_blocklist_ignores_comments_and_blanks() -> None:
    terms = load_blocklist(CONFIGS / "blocklist.txt")

    assert terms[0] == "election"
    assert "political party" in terms
    assert "hate" in terms
    assert all(term == term.lower() for term in terms)
    assert all(term and not term.startswith("#") for term in terms)
