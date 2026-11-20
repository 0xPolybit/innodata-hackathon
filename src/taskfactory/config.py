"""Load and validate TaskFactory configuration files."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FAMILY_NAMES = ("bar", "line", "floorplan")
QUESTION_TYPE_NAMES = (
    "value_lookup",
    "extremum",
    "rank_k",
    "pair_compare",
    "series_at_x",
    "spatial",
)
MODEL_ROLES = ("evaluated", "secondary")

_RUN_KEYS = frozenset(
    {
        "run_seed",
        "tasks_per_cell",
        "question_in_image",
        "families",
        "domains",
        "question_types",
        "checks",
        "eval",
    }
)
_DOMAIN_KEYS = frozenset(
    {"title", "categories", "value_range", "value_format", "families"}
)
_MODEL_KEYS = (
    "id",
    "provider",
    "role",
    "inputs",
    "test_call",
    "limits",
    "notes",
)

_TERM_PATTERNS: dict[str, re.Pattern[str]] = {}


class ConfigError(ValueError):
    """Raised when a configuration file is malformed or breaks a policy."""


@dataclass
class EvalConfig:
    """The optional ``[eval]`` table of a run config."""

    items_per_model: int | None = None
    models: str | None = None
    stratify_by: list[str] = field(default_factory=list)


@dataclass
class RunConfig:
    """A validated run configuration."""

    run_seed: int
    tasks_per_cell: int
    question_in_image: bool
    families: list[str]
    domains: list[str]
    question_types: list[str]
    checks: dict[str, Any] = field(default_factory=dict)
    eval: EvalConfig = field(default_factory=EvalConfig)


@dataclass
class DomainConfig:
    """A validated domain configuration."""

    title: str
    categories: list[str]
    value_range: tuple[int, int]
    value_format: str
    families: list[str]
    name: str = ""


def _describe(value: Any) -> str:
    """Return a human-readable type name for an error message."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


def _load_toml(path: str | Path) -> tuple[Path, dict[str, Any]]:
    """Read a TOML file, wrapping OS and parse errors in :class:`ConfigError`."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"{config_path}: file not found") from exc
    except IsADirectoryError as exc:
        raise ConfigError(f"{config_path}: expected a file, not a directory") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid TOML: {exc}") from exc
    return config_path, data


def _reject_unknown(
    data: Mapping[str, Any], allowed: frozenset[str], *, prefix: str = ""
) -> None:
    """Raise :class:`ConfigError` for the first key not in ``allowed``."""
    for key in data:
        if key not in allowed:
            raise ConfigError(f"{prefix}{key}: unknown key")


def _require(data: Mapping[str, Any], key: str, *, prefix: str = "") -> Any:
    """Return ``data[key]`` or raise naming the missing key."""
    if key not in data:
        raise ConfigError(f"{prefix}{key}: missing required key")
    return data[key]


def _get_int(
    data: Mapping[str, Any], key: str, *, minimum: int | None = None
) -> int:
    """Return an integer value, rejecting booleans, or raise."""
    value = _require(data, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"{key}: expected an integer, got {_describe(value)}"
        )
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key}: must be at least {minimum}, got {value}")
    return value


def _get_bool(data: Mapping[str, Any], key: str) -> bool:
    """Return a boolean value or raise."""
    value = _require(data, key)
    if not isinstance(value, bool):
        raise ConfigError(f"{key}: expected a boolean, got {_describe(value)}")
    return value


def _get_str(data: Mapping[str, Any], key: str) -> str:
    """Return a non-empty string value or raise."""
    value = _require(data, key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key}: expected a non-empty string")
    return value


def _get_str_list(
    data: Mapping[str, Any],
    key: str,
    *,
    allowed: tuple[str, ...] | None = None,
    minimum: int = 1,
    unique: bool = False,
) -> list[str]:
    """Return a validated list of strings or raise."""
    value = _require(data, key)
    if not isinstance(value, list):
        raise ConfigError(f"{key}: expected a list, got {_describe(value)}")
    if len(value) < minimum:
        raise ConfigError(f"{key}: must contain at least {minimum} item(s)")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{key}: entries must be non-empty strings")
        if allowed is not None and item not in allowed:
            choices = ", ".join(allowed)
            raise ConfigError(
                f"{key}: unknown value {item!r}; expected one of: {choices}"
            )
        items.append(item)
    if unique:
        duplicates = sorted({item for item in items if items.count(item) > 1})
        if duplicates:
            raise ConfigError(
                f"{key}: duplicate entries: {', '.join(duplicates)}"
            )
    return items


def _get_table(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Return a TOML table value or raise."""
    value = _require(data, key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key}: expected a table, got {_describe(value)}")
    return value


def _load_eval(data: Mapping[str, Any]) -> EvalConfig:
    """Parse the optional ``[eval]`` table."""
    if "eval" not in data:
        return EvalConfig()
    table = _get_table(data, "eval")

    items_per_model = table.get("items_per_model")
    if items_per_model is not None:
        if isinstance(items_per_model, bool) or not isinstance(items_per_model, int):
            raise ConfigError(
                "eval.items_per_model: expected an integer, "
                f"got {_describe(items_per_model)}"
            )
        if items_per_model < 1:
            raise ConfigError(
                f"eval.items_per_model: must be at least 1, got {items_per_model}"
            )

    models = table.get("models")
    if models is not None and (not isinstance(models, str) or not models.strip()):
        raise ConfigError("eval.models: expected a non-empty path string")

    stratify_by = table.get("stratify_by", [])
    if not isinstance(stratify_by, list):
        raise ConfigError(
            f"eval.stratify_by: expected a list, got {_describe(stratify_by)}"
        )
    for item in stratify_by:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                "eval.stratify_by: entries must be non-empty strings"
            )

    return EvalConfig(
        items_per_model=items_per_model,
        models=models,
        stratify_by=list(stratify_by),
    )


def load_run_config(path: str | Path) -> RunConfig:
    """Load and validate a run configuration from ``path``."""
    _, data = _load_toml(path)
    _reject_unknown(data, _RUN_KEYS)

    run_seed = _get_int(data, "run_seed")
    tasks_per_cell = _get_int(data, "tasks_per_cell", minimum=1)
    question_in_image = _get_bool(data, "question_in_image")
    families = _get_str_list(data, "families", allowed=FAMILY_NAMES)
    domains = _get_str_list(data, "domains")
    question_types = _get_str_list(
        data, "question_types", allowed=QUESTION_TYPE_NAMES
    )
    checks = _get_table(data, "checks")
    eval_config = _load_eval(data)

    return RunConfig(
        run_seed=run_seed,
        tasks_per_cell=tasks_per_cell,
        question_in_image=question_in_image,
        families=families,
        domains=domains,
        question_types=question_types,
        checks=dict(checks),
        eval=eval_config,
    )


def load_domain(path: str | Path) -> DomainConfig:
    """Load and validate a domain configuration from ``path``.

    The returned config's ``name`` is the file stem, so
    ``configs/domains/tourism.toml`` loads as ``"tourism"``.
    """
    config_path, data = _load_toml(path)
    _reject_unknown(data, _DOMAIN_KEYS)

    title = _get_str(data, "title")
    categories = _get_str_list(data, "categories", minimum=2, unique=True)
    value_range = _get_value_range(data)
    value_format = _get_str(data, "value_format")
    if "{" not in value_format:
        raise ConfigError(
            f"value_format: must contain '{{', got {value_format!r}"
        )
    families = _get_str_list(data, "families", allowed=FAMILY_NAMES)

    return DomainConfig(
        title=title,
        categories=categories,
        value_range=value_range,
        value_format=value_format,
        families=families,
        name=config_path.stem,
    )


def _get_value_range(data: Mapping[str, Any]) -> tuple[int, int]:
    """Return the validated ``value_range`` pair."""
    value = _require(data, "value_range")
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigError(
            "value_range: expected a list of exactly two integers"
        )
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ConfigError(
                f"value_range: entries must be integers, got {_describe(item)}"
            )
    low, high = value
    if low >= high:
        raise ConfigError(
            f"value_range: minimum must be less than maximum, got [{low}, {high}]"
        )
    return (low, high)


def load_models(
    path: str | Path, *, eval_ids: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Load model entries and, when given, enforce the secondary-model rule."""
    _, data = _load_toml(path)
    entries = _require(data, "models")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("models: expected a non-empty list of tables")

    models: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"models[{index}]: expected a table")
        model = _validate_model(entry, index)
        model_id = model["id"]
        if model_id in seen_ids:
            raise ConfigError(f"models[{index}].id: duplicate id {model_id!r}")
        seen_ids.add(model_id)
        models.append(model)

    check_no_secondary_in_eval(models, eval_ids)
    return models


def _validate_model(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    """Validate one ``[[models]]`` entry."""
    prefix = f"models[{index}]."
    for key in _MODEL_KEYS:
        if key not in entry:
            raise ConfigError(f"{prefix}{key}: missing required key")

    model_id = entry["id"]
    if not isinstance(model_id, str) or not model_id.strip():
        raise ConfigError(f"{prefix}id: expected a non-empty string")

    provider = entry["provider"]
    if not isinstance(provider, str) or not provider.strip():
        raise ConfigError(f"{prefix}provider: expected a non-empty string")

    role = entry["role"]
    if not isinstance(role, str) or role not in MODEL_ROLES:
        choices = ", ".join(MODEL_ROLES)
        raise ConfigError(
            f"{prefix}role: expected one of: {choices}; got {role!r}"
        )

    inputs = entry["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise ConfigError(f"{prefix}inputs: expected a non-empty list of strings")
    for item in inputs:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{prefix}inputs: entries must be non-empty strings")

    for key in ("test_call", "limits", "notes"):
        value = entry[key]
        if not isinstance(value, str):
            raise ConfigError(f"{prefix}{key}: expected a string")

    return {
        "id": model_id,
        "provider": provider,
        "role": role,
        "inputs": list(inputs),
        "test_call": entry["test_call"],
        "limits": entry["limits"],
        "notes": entry["notes"],
    }


def check_no_secondary_in_eval(
    models: Iterable[Mapping[str, Any]], eval_ids: Iterable[str] | None
) -> None:
    """Refuse any secondary model that appears in the evaluated model ids."""
    if eval_ids is None:
        return
    if isinstance(eval_ids, str):
        eval_ids = [eval_ids]

    secondary_ids = {
        model["id"]
        for model in models
        if model.get("role") == "secondary" and isinstance(model.get("id"), str)
    }
    overlap = sorted(secondary_ids.intersection(eval_ids))
    if overlap:
        raise ConfigError(
            f"secondary model {overlap[0]!r} must not be listed in eval.models"
        )


def load_blocklist(path: str | Path) -> list[str]:
    """Load lowercase blocklist terms, one per line, ignoring comments."""
    blocklist_path = Path(path)
    try:
        text = blocklist_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"{blocklist_path}: file not found") from exc
    except OSError as exc:
        raise ConfigError(f"{blocklist_path}: cannot read file: {exc}") from exc

    terms: list[str] = []
    for line in text.splitlines():
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        terms.append(term.lower())
    return terms


def _term_pattern(term: str) -> re.Pattern[str]:
    """Compile a case-insensitive whole-word pattern for one term."""
    pattern = _TERM_PATTERNS.get(term)
    if pattern is None:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        _TERM_PATTERNS[term] = pattern
    return pattern


def check_blocklist(
    texts: Iterable[str] | str, terms: Iterable[str] | str
) -> None:
    """Raise :class:`ConfigError` for the first blocklisted whole-word match."""
    if isinstance(texts, str):
        texts = [texts]
    if isinstance(terms, str):
        terms = [terms]

    normalized = [(term, term.strip().lower()) for term in terms]
    normalized = [(original, term) for original, term in normalized if term]

    for text in texts:
        for original, term in normalized:
            if _term_pattern(term).search(text):
                raise ConfigError(
                    f"blocklisted term {original!r} found in text {text!r}"
                )
