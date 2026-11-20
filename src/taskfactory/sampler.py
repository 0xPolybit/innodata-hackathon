"""Seeded sampler for bar and line chart task specs.

A spec is a plain, JSON-serialisable dict shared with the renderers::

    {
        "spec_version": 1,
        "family": "bar" | "line",
        "domain": str,
        "index": int,
        "seed": int,
        "title": str,
        "x_labels": [str, ...],
        "series": [{"name": str, "values": [int, ...], "labels": [str, ...]}],
        "orientation": "vertical" | "horizontal",
        "x_label_rotation": 0 | 30,
        "question_in_image": bool,
    }

Every random choice in :func:`sample_spec` comes from a ``random.Random``
seeded by :func:`task_seed`, so a spec can be reproduced from the run seed,
family, domain and index alone.  Adding a family to a run therefore never
changes any existing task's spec.

``labels`` holds the printed value labels (``value_format`` applied to each
value); ``x_labels`` holds the category names for a bar chart and the year
strings for a line chart.

Bar and line values keep the run's ambiguity margin
---------------------------------------------------
A bar draw whose top two values are closer than the run's
``checks.ambiguity_min_margin`` (default 0.05), measured as
``(max - second) / max``, is redrawn from the same seeded generator, up to
200 attempts.

A line draw is redrawn the same way when any year column -- the values of
all series at one x position -- has two equal values or a top-two relative
margin below the threshold. Each series still holds distinct values of its
own. A line spec that cannot satisfy both rules in 200 attempts raises
:class:`ValueError` naming the family, domain and index.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from taskfactory.config import DomainConfig, RunConfig

__all__ = [
    "SPEC_VERSION",
    "format_value",
    "sample_batch",
    "sample_spec",
    "task_seed",
    "validate_spec",
]

SPEC_VERSION = 1

_BAR = "bar"
_LINE = "line"
_SAMPLEABLE_FAMILIES = (_BAR, _LINE)
_ORIENTATIONS = ("vertical", "horizontal")
_X_LABEL_ROTATIONS = (0, 30)

_BAR_MIN_CATEGORIES = 4
_BAR_MAX_CATEGORIES = 8
_LINE_MIN_POINTS = 6
_LINE_MAX_POINTS = 10
_LINE_LAST_YEAR = 2025
_TITLE_MIN_YEAR = 2015
_TITLE_MAX_YEAR = 2024

_SEED_MODULUS = 1 << 32
_MILLION = 1_000_000

_DEFAULT_AMBIGUITY_MARGIN = 0.05
_MARGIN_ATTEMPTS = 200


def task_seed(run_seed: int, family: str, domain: str, index: int) -> int:
    """Return the per-task seed derived from the four identifying inputs.

    The seed is the first eight bytes of the SHA-256 of
    ``"{run_seed}|{family}|{domain}|{index}"`` read as an unsigned big-endian
    integer and reduced modulo ``2**32``.  It deliberately ignores everything
    else, so adding a family cannot shift another family's tasks.
    """
    payload = f"{run_seed}|{family}|{domain}|{index}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % _SEED_MODULUS


def format_value(value: int, value_format: str) -> str:
    """Format ``value`` with ``value_format``, scaling millions when needed.

    A format string ending in ``"M"`` (the suffix sits after the closing
    brace, as in ``"{:.1f}M"``) is fed the value divided by 1,000,000;
    otherwise the raw value is formatted.  The format string supplies the
    suffix, so ``"{:.1f}M"`` already prints the trailing ``M``.
    """
    numeric = value / _MILLION if value_format.endswith("M") else value
    return value_format.format(numeric)


def sample_spec(
    run_cfg: RunConfig,
    domain_cfg: DomainConfig,
    family: str,
    index: int,
) -> dict[str, Any]:
    """Sample one reproducible spec for ``family`` at ``index``.

    Raises :class:`ValueError` for a family the sampler does not know or a
    family the domain has not enabled.
    """
    if family not in _SAMPLEABLE_FAMILIES:
        choices = ", ".join(_SAMPLEABLE_FAMILIES)
        raise ValueError(f"unknown family {family!r}; expected one of: {choices}")
    if family not in domain_cfg.families:
        raise ValueError(
            f"family {family!r} is not enabled for this domain; "
            f"domain families are: {', '.join(domain_cfg.families)}"
        )

    domain_name = _domain_name(domain_cfg)
    seed = task_seed(run_cfg.run_seed, family, domain_name, index)
    rng = random.Random(seed)

    if family == _BAR:
        return _sample_bar(rng, run_cfg, domain_cfg, domain_name, index, seed)
    return _sample_line(rng, run_cfg, domain_cfg, domain_name, index, seed)


def sample_batch(
    run_cfg: RunConfig,
    domain_cfg: DomainConfig,
    family: str,
    count: int,
) -> list[dict[str, Any]]:
    """Return ``count`` specs with indexes ``0 .. count - 1``."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError(f"count: expected an integer, got {type(count).__name__}")
    if count < 0:
        raise ValueError(f"count: must be non-negative, got {count}")
    return [sample_spec(run_cfg, domain_cfg, family, index) for index in range(count)]


def validate_spec(spec: Any) -> None:
    """Validate the shared spec shape, raising :class:`ValueError` if broken."""
    if not isinstance(spec, dict):
        raise ValueError(f"spec: expected a dict, got {type(spec).__name__}")

    version = _require_int(spec, "spec_version")
    if version != SPEC_VERSION:
        raise ValueError(
            f"spec.spec_version: expected {SPEC_VERSION}, got {version}"
        )

    family = _require_str(spec, "family")
    if family not in _SAMPLEABLE_FAMILIES:
        choices = ", ".join(_SAMPLEABLE_FAMILIES)
        raise ValueError(
            f"spec.family: expected one of: {choices}; got {family!r}"
        )

    _require_str(spec, "domain")

    index = _require_int(spec, "index")
    if index < 0:
        raise ValueError(f"spec.index: must be non-negative, got {index}")

    seed = _require_int(spec, "seed")
    if not 0 <= seed < _SEED_MODULUS:
        raise ValueError(
            f"spec.seed: expected an integer in [0, {_SEED_MODULUS}), got {seed}"
        )

    _require_str(spec, "title")
    x_labels = _require_str_list(spec, "x_labels")

    raw_series = spec.get("series")
    if not isinstance(raw_series, list) or not raw_series:
        raise ValueError("spec.series: expected a non-empty list")

    orientation = _require_str(spec, "orientation")
    if orientation not in _ORIENTATIONS:
        choices = ", ".join(_ORIENTATIONS)
        raise ValueError(
            f"spec.orientation: expected one of: {choices}; got {orientation!r}"
        )

    rotation = _require_int(spec, "x_label_rotation")
    if rotation not in _X_LABEL_ROTATIONS:
        raise ValueError(
            f"spec.x_label_rotation: expected 0 or 30, got {rotation}"
        )

    question_in_image = spec.get("question_in_image")
    if not isinstance(question_in_image, bool):
        raise ValueError("spec.question_in_image: expected a boolean")

    series = [
        _validate_series(item, position)
        for position, item in enumerate(raw_series)
    ]

    if family == _BAR:
        _validate_bar(series, x_labels)
    else:
        _validate_line(series, x_labels, orientation)


def _domain_name(domain_cfg: DomainConfig) -> str:
    """Return the domain name used in specs and seeds.

    The name is :attr:`~taskfactory.config.DomainConfig.name`, which
    :func:`~taskfactory.config.load_domain` fills with the config file stem.
    """
    name = getattr(domain_cfg, "name", None)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "domain config has no name: load it with load_domain() so the "
            "domain name comes from the config file stem"
        )
    return name


def _sample_bar(
    rng: random.Random,
    run_cfg: RunConfig,
    domain_cfg: DomainConfig,
    domain_name: str,
    index: int,
    seed: int,
) -> dict[str, Any]:
    """Sample one bar spec; the single series carries each bar's value."""
    categories = list(domain_cfg.categories)
    if not categories:
        raise ValueError("domain config has no categories")

    upper = min(_BAR_MAX_CATEGORIES, len(categories))
    lower = min(_BAR_MIN_CATEGORIES, upper)
    count = rng.randint(lower, upper)
    x_labels = rng.sample(categories, count)
    values = _bar_values(
        rng,
        domain_cfg.value_range,
        count,
        _ambiguity_min_margin(run_cfg),
        domain_name,
        index,
    )
    labels = [format_value(value, domain_cfg.value_format) for value in values]

    return {
        "spec_version": SPEC_VERSION,
        "family": _BAR,
        "domain": domain_name,
        "index": index,
        "seed": seed,
        "title": _title(domain_cfg.title, rng),
        "x_labels": x_labels,
        "series": [{"name": "", "values": values, "labels": labels}],
        "orientation": rng.choice(_ORIENTATIONS),
        "x_label_rotation": rng.choice(_X_LABEL_ROTATIONS),
        "question_in_image": bool(run_cfg.question_in_image),
    }


def _sample_line(
    rng: random.Random,
    run_cfg: RunConfig,
    domain_cfg: DomainConfig,
    domain_name: str,
    index: int,
    seed: int,
) -> dict[str, Any]:
    """Sample one line spec with 2-3 category series over consecutive years."""
    categories = list(domain_cfg.categories)
    if len(categories) < 2:
        raise ValueError("line family needs at least two domain categories")

    point_count = rng.randint(_LINE_MIN_POINTS, _LINE_MAX_POINTS)
    x_labels = [
        str(year)
        for year in range(_LINE_LAST_YEAR - point_count + 1, _LINE_LAST_YEAR + 1)
    ]

    series_count = rng.randint(2, min(3, len(categories)))
    names = rng.sample(categories, series_count)
    values_by_series = _line_values(
        rng,
        domain_cfg.value_range,
        point_count,
        series_count,
        _ambiguity_min_margin(run_cfg),
        domain_name,
        index,
    )

    series: list[dict[str, Any]] = []
    for name, values in zip(names, values_by_series):
        labels = [format_value(value, domain_cfg.value_format) for value in values]
        series.append({"name": name, "values": values, "labels": labels})

    return {
        "spec_version": SPEC_VERSION,
        "family": _LINE,
        "domain": domain_name,
        "index": index,
        "seed": seed,
        "title": _title(domain_cfg.title, rng),
        "x_labels": x_labels,
        "series": series,
        "orientation": "vertical",
        "x_label_rotation": rng.choice(_X_LABEL_ROTATIONS),
        "question_in_image": bool(run_cfg.question_in_image),
    }


def _title(template: str, rng: random.Random) -> str:
    """Fill the ``{year}`` placeholder with a year from 2015 through 2024."""
    year = rng.randint(_TITLE_MIN_YEAR, _TITLE_MAX_YEAR)
    return template.replace("{year}", str(year))


def _distinct_values(
    rng: random.Random,
    value_range: tuple[int, int],
    count: int,
) -> list[int]:
    """Draw ``count`` distinct integers, regenerating every duplicate."""
    low, high = value_range
    available = high - low + 1
    if available < count:
        raise ValueError(
            f"value_range [{low}, {high}] cannot supply {count} distinct values"
        )

    values: list[int] = []
    seen: set[int] = set()
    while len(values) < count:
        value = rng.randint(low, high)
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _ambiguity_min_margin(run_cfg: RunConfig) -> float:
    """The run's minimum top-two margin, from ``checks`` or its attribute form."""
    default = _DEFAULT_AMBIGUITY_MARGIN
    checks = getattr(run_cfg, "checks", None)
    if isinstance(checks, dict):
        raw = checks.get("ambiguity_min_margin", default)
    elif checks is not None:
        raw = getattr(checks, "ambiguity_min_margin", default)
    else:
        raw = getattr(run_cfg, "ambiguity_min_margin", default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    return float(raw)


def _bar_values(
    rng: random.Random,
    value_range: tuple[int, int],
    count: int,
    min_margin: float,
    domain_name: str,
    index: int,
) -> list[int]:
    """Draw distinct bar values whose top-two relative margin clears the threshold.

    Each rejected draw is replaced by a fresh one from the same seeded
    ``rng``, so a spec stays reproducible. After 200 failed draws a
    :class:`ValueError` names the family, domain and index.
    """
    for _ in range(_MARGIN_ATTEMPTS):
        values = _distinct_values(rng, value_range, count)
        if _relative_margin(values) >= min_margin:
            return values
    raise ValueError(
        f"family {_BAR!r} domain {domain_name!r} index {index}: could not draw "
        f"values with a top-two relative margin of at least {min_margin:g} "
        f"in {_MARGIN_ATTEMPTS} attempts"
    )


def _line_values(
    rng: random.Random,
    value_range: tuple[int, int],
    point_count: int,
    series_count: int,
    min_margin: float,
    domain_name: str,
    index: int,
) -> list[list[int]]:
    """Draw per-series distinct values whose year columns clear the margin.

    Each series keeps its own distinct values. Every year column -- the
    values of all series at one x position -- must also hold distinct values
    with a top-two relative margin of at least ``min_margin``. Each rejected
    draw is replaced by a fresh one for every series from the same seeded
    ``rng``, so a spec stays reproducible. After 200 failed draws a
    :class:`ValueError` names the family, domain and index.
    """
    for _ in range(_MARGIN_ATTEMPTS):
        rows = [
            _distinct_values(rng, value_range, point_count)
            for _ in range(series_count)
        ]
        if _line_columns_clear_margin(rows, min_margin):
            return rows
    raise ValueError(
        f"family {_LINE!r} domain {domain_name!r} index {index}: could not draw "
        f"line values with distinct series values and a top-two relative "
        f"margin of at least {min_margin:g} in every year column in "
        f"{_MARGIN_ATTEMPTS} attempts"
    )


def _line_columns_clear_margin(
    rows: list[list[int]],
    min_margin: float,
) -> bool:
    """Return True when every year column is tie-free and clears the margin."""
    for column in zip(*rows):
        if len(set(column)) != len(column):
            return False
        if _relative_margin(list(column)) < min_margin:
            return False
    return True


def _relative_margin(values: list[int]) -> float:
    """Return ``(max - second) / max``, or 1.0 when it is not defined."""
    if len(values) < 2:
        return 1.0
    largest, second = sorted(values, reverse=True)[:2]
    if largest <= 0:
        return 1.0
    return (largest - second) / largest


def _validate_bar(
    series: list[tuple[str, list[int], list[str]]],
    x_labels: list[str],
) -> None:
    """Check the bar-specific rules on an already-parsed series list."""
    if len(series) != 1:
        raise ValueError(
            f"spec.series: a bar spec needs exactly one series, got {len(series)}"
        )

    name, values, _ = series[0]
    if name != "":
        raise ValueError(
            'spec.series[0].name: a bar series must be named ""'
        )
    if len(values) != len(x_labels):
        raise ValueError(
            "spec.series[0].values: expected "
            f"{len(x_labels)} values to match x_labels, got {len(values)}"
        )
    if not 1 <= len(values) <= _BAR_MAX_CATEGORIES:
        raise ValueError(
            "spec.series[0].values: a bar spec needs between 1 and "
            f"{_BAR_MAX_CATEGORIES} values, got {len(values)}"
        )


def _validate_line(
    series: list[tuple[str, list[int], list[str]]],
    x_labels: list[str],
    orientation: str,
) -> None:
    """Check the line-specific rules on an already-parsed series list."""
    if len(series) not in (2, 3):
        raise ValueError(
            f"spec.series: a line spec needs 2 or 3 series, got {len(series)}"
        )
    if orientation != "vertical":
        raise ValueError(
            'spec.orientation: a line spec must be "vertical", '
            f"got {orientation!r}"
        )
    if not _LINE_MIN_POINTS <= len(x_labels) <= _LINE_MAX_POINTS:
        raise ValueError(
            "spec.x_labels: a line spec needs between "
            f"{_LINE_MIN_POINTS} and {_LINE_MAX_POINTS} points, "
            f"got {len(x_labels)}"
        )
    _validate_line_years(x_labels)

    for position, (_, values, _) in enumerate(series):
        if len(values) != len(x_labels):
            raise ValueError(
                f"spec.series[{position}].values: expected "
                f"{len(x_labels)} values to match x_labels, got {len(values)}"
            )


def _validate_line_years(x_labels: list[str]) -> None:
    """Require consecutive four-digit years ending at 2025."""
    years: list[int] = []
    for position, label in enumerate(x_labels):
        if len(label) != 4 or not label.isascii() or not label.isdigit():
            raise ValueError(
                f"spec.x_labels[{position}]: expected a four-digit year, "
                f"got {label!r}"
            )
        years.append(int(label))

    if years[-1] != _LINE_LAST_YEAR:
        raise ValueError(
            f"spec.x_labels: line labels must end at {_LINE_LAST_YEAR}, "
            f"got {x_labels[-1]!r}"
        )
    for earlier, later in zip(years, years[1:]):
        if later != earlier + 1:
            raise ValueError(
                "spec.x_labels: line labels must be consecutive years"
            )


def _validate_series(
    raw: Any, position: int
) -> tuple[str, list[int], list[str]]:
    """Validate one series object and return its parsed name, values and labels."""
    prefix = f"spec.series[{position}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{prefix}: expected an object, got {type(raw).__name__}")

    name = raw.get("name")
    if not isinstance(name, str):
        raise ValueError(f"{prefix}.name: expected a string")

    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"{prefix}.values: expected a non-empty list of integers")
    for offset, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{prefix}.values[{offset}]: expected an integer, "
                f"got {type(value).__name__}"
            )
    if len(set(values)) != len(values):
        raise ValueError(f"{prefix}.values: duplicate values within the series")

    labels = raw.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"{prefix}.labels: expected a non-empty list of strings")
    for offset, label in enumerate(labels):
        if not isinstance(label, str):
            raise ValueError(
                f"{prefix}.labels[{offset}]: expected a string, "
                f"got {type(label).__name__}"
            )
    if len(values) != len(labels):
        raise ValueError(
            f"{prefix}: values and labels differ in length "
            f"({len(values)} vs {len(labels)})"
        )

    return name, values, labels


def _require_int(spec: dict[str, Any], key: str) -> int:
    """Return ``spec[key]`` as a non-boolean integer or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    value = spec[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"spec.{key}: expected an integer, got {type(value).__name__}"
        )
    return value


def _require_str(spec: dict[str, Any], key: str) -> str:
    """Return ``spec[key]`` as a non-empty string or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    value = spec[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"spec.{key}: expected a non-empty string")
    return value


def _require_str_list(spec: dict[str, Any], key: str) -> list[str]:
    """Return ``spec[key]`` as a non-empty list of non-empty strings or raise."""
    if key not in spec:
        raise ValueError(f"spec: missing required key {key!r}")
    value = spec[key]
    if not isinstance(value, list) or not value:
        raise ValueError(f"spec.{key}: expected a non-empty list of strings")
    for position, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"spec.{key}[{position}]: expected a non-empty string"
            )
    return value
