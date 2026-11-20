"""Tests for the parsing helpers of ``scripts/spike_gate.py``.

The gate itself talks HTTP; these tests only read HTML that looks like the
results page, so no server is started and nothing is generated.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "spike_gate.py"

PAGE = """<table class="summary">
<tbody>
<tr class="main-count"><th>Attempted</th><td><strong>14</strong> tasks attempted</td></tr>
<tr><th>Accepted</th><td>14</td></tr>
<tr><th>Rejected</th><td>0</td></tr>
</tbody>
</table>
<p class="checks-summary">7 of 7 checks passed</p>
<p class="checks-summary">7 of 7 checks passed</p>
<img src="data:image/png;base64,AAAA" alt="Chart for one">
<img src="data:image/png;base64,BBBB" alt="Chart for two">
"""


def _load_script() -> ModuleType:
    """Import the stdlib-only gate script from its path."""
    spec = importlib.util.spec_from_file_location("spike_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_counts() -> None:
    gate = _load_script()

    assert gate.parse_counts(PAGE) == {"attempted": 14, "accepted": 14, "rejected": 0}


def test_parse_counts_ignores_missing_labels() -> None:
    gate = _load_script()

    assert gate.parse_counts("<p>no summary here</p>") == {}


def test_parse_check_summaries() -> None:
    gate = _load_script()

    assert gate.parse_check_summaries(PAGE) == [(7, 7), (7, 7)]
    assert gate.parse_check_summaries("6 of 7 checks passed") == [(6, 7)]


def test_count_png_images() -> None:
    gate = _load_script()

    assert gate.count_png_images(PAGE) == 2
    assert gate.count_png_images("no pictures") == 0
