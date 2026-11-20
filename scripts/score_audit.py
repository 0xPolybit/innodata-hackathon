"""Score a filled audit CSV against the answer key.

An answer is correct when it matches the key after lower-casing and removing
spaces and punctuation. A row marked ``no`` for question grounding or answer
visibility counts as an audit error even when the answer matches.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
Z_95 = 1.959964


def normalize_answer(value: str) -> str:
    """Lower-case the text and drop whitespace and punctuation."""
    kept = []
    for character in value.lower():
        if character.isspace():
            continue
        if unicodedata.category(character).startswith("P"):
            continue
        kept.append(character)
    return "".join(kept)


def wilson_interval(errors: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Return the 95% Wilson score interval for ``errors / total``."""
    if total == 0:
        return 0.0, 0.0
    proportion = errors / total
    denominator = 1.0 + (z * z) / total
    centre = (proportion + (z * z) / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total + (z * z) / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def _is_no(value: str | None) -> bool:
    """True when a yes/no field was answered ``no``."""
    return (value or "").strip().lower() == "no"


def score(results_path: Path, key_path: Path) -> dict[str, object]:
    """Score the reviewed rows and return the report dictionary."""
    if not results_path.is_file():
        raise SystemExit(f"error: results file not found: {results_path}")
    if not key_path.is_file():
        raise SystemExit(f"error: answer key not found: {key_path}")

    key = json.loads(key_path.read_text(encoding="utf-8"))
    if not isinstance(key, dict):
        raise SystemExit(f"error: answer key is not a JSON object: {key_path}")

    reviewed = 0
    errors = 0
    skipped = 0
    error_packages: list[str] = []
    missing_key: list[str] = []

    with results_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "package" not in fields or "reviewer_answer" not in fields:
            raise SystemExit(
                "error: results CSV needs at least the package and "
                "reviewer_answer columns"
            )
        for row in reader:
            reviewer_answer = (row.get("reviewer_answer") or "").strip()
            if not reviewer_answer:
                skipped += 1
                continue

            reviewed += 1
            package = (row.get("package") or "").strip()
            expected = key.get(package)
            answer_matches = expected is not None and normalize_answer(
                reviewer_answer
            ) == normalize_answer(str(expected))

            audit_error = _is_no(row.get("question_grounded")) or _is_no(
                row.get("answer_visible")
            )
            if not answer_matches or audit_error:
                errors += 1
                if package and package not in error_packages:
                    error_packages.append(package)
            if expected is None and package:
                missing_key.append(package)

    low, high = wilson_interval(errors, reviewed)
    if missing_key:
        print(
            f"warning: {len(missing_key)} reviewed package(s) missing from the key: "
            + ", ".join(missing_key),
            file=sys.stderr,
        )

    return {
        "items_reviewed": reviewed,
        "errors": errors,
        "error_rate": round(errors / reviewed, 4) if reviewed else 0.0,
        "wilson_95_interval": [round(low, 4), round(high, 4)],
        "error_packages": error_packages,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, score the audit and print the JSON report."""
    parser = argparse.ArgumentParser(description="Score a filled human audit CSV.")
    parser.add_argument(
        "--results",
        type=Path,
        default=REPO_ROOT / "audit" / "results_template.csv",
        help="filled audit CSV (default: audit/results_template.csv)",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=REPO_ROOT / "out" / "audit_key.json",
        help="answer key written by make_audit_sheet.py (default: out/audit_key.json)",
    )
    args = parser.parse_args(argv)

    report = score(args.results, args.key)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
