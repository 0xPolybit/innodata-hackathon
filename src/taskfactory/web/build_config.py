"""Build the canonical run config of one web request and its run id.

The config is plain TOML written from the parsed form alone: the same choices
always produce byte-identical text and therefore the same run id. Nothing here
reads the clock, a random source or the environment.

The run id is ``ui-`` followed by the first eight hex characters of the SHA-256
of the TOML bytes. Two different choices, such as two seeds, give different
text and a different id.

Difficulty tiers
----------------
``standard`` is the existing standard tier: an ambiguity margin of 0.05, a
minimum font of 9 px, up to 8 bars and near-duplicate distance 6. ``harder``
is the tier in docs/IMPLEMENTATION_PLAN.md section 3 (0.02 margin, 7 px and 12
bars), with the 12 bars taken from ``configs/runs/hard2.toml`` and the same
near-duplicate distance as both hard configs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass

from taskfactory.web.forms import CHART_TYPES, QUESTION_TYPES, ParsedForm

__all__ = [
    "DIFFICULTY_SETTINGS",
    "BuiltConfig",
    "build_config",
    "canonical_toml",
    "run_id_for",
]

# Kept as TOML literals so the emitted bytes cannot depend on float formatting.
DIFFICULTY_SETTINGS: dict[str, dict[str, str]] = {
    "standard": {
        "ambiguity_min_margin": "0.05",
        "min_font_px": "9",
        "near_dup_phash_max": "6",
        "bar_max_categories": "8",
    },
    "harder": {
        "ambiguity_min_margin": "0.02",
        "min_font_px": "7",
        "near_dup_phash_max": "6",
        "bar_max_categories": "12",
    },
}


@dataclass(frozen=True)
class BuiltConfig:
    """The canonical TOML text of a request and the run id derived from it."""

    toml: str
    run_id: str

    @property
    def text(self) -> str:
        """The canonical TOML, under the name callers often reach for first."""
        return self.toml

    @property
    def toml_text(self) -> str:
        """The canonical TOML, under its more explicit name."""
        return self.toml

    def __iter__(self) -> Iterator[str]:
        """Allow ``toml_text, run_id = build_config(form)``."""
        yield self.toml
        yield self.run_id


def canonical_toml(form: ParsedForm) -> str:
    """Return the canonical TOML text of ``form``.

    Lists are written in the fixed order the form defines, so choosing the
    same options in a different order still gives identical bytes.
    """
    settings = DIFFICULTY_SETTINGS[form.difficulty]
    families = _string_list(
        tuple(name for name in CHART_TYPES if name in form.chart_types)
    )
    domains = _string_list(form.domains)
    question_types = _string_list(
        tuple(name for name in QUESTION_TYPES if name in form.question_types)
    )
    lines = [
        f"run_seed = {form.seed}",
        f"tasks_per_cell = {form.charts_per_type}",
        f"question_in_image = {'true' if form.question_in_image else 'false'}",
        f"families = [{families}]",
        f"domains = [{domains}]",
        f"question_types = [{question_types}]",
        f"bar_max_categories = {settings['bar_max_categories']}",
        "",
        "[checks]",
        f"ambiguity_min_margin = {settings['ambiguity_min_margin']}",
        f"min_font_px = {settings['min_font_px']}",
        f"near_dup_phash_max = {settings['near_dup_phash_max']}",
        "",
    ]
    return "\n".join(lines)


def run_id_for(toml_text: str) -> str:
    """The deterministic run id of a canonical TOML text."""
    digest = hashlib.sha256(toml_text.encode("utf-8")).hexdigest()
    return f"ui-{digest[:8]}"


def build_config(form: ParsedForm) -> BuiltConfig:
    """Build the canonical TOML and its run id from one parsed form."""
    text = canonical_toml(form)
    return BuiltConfig(toml=text, run_id=run_id_for(text))


def _string_list(values: tuple[str, ...]) -> str:
    """TOML array entries for an already validated list of names."""
    return ", ".join(f'"{value}"' for value in values)
