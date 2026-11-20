"""Build the human audit kit for a random sample of accepted task packages.

The kit is self-contained: the reviewer only needs ``audit/``. The answer key is
written under ``out/`` (git-ignored) so it stays out of the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_COUNT = 50
SEED = 20261121

CSV_FIELDS = (
    "item",
    "package",
    "reviewer",
    "reviewer_answer",
    "question_grounded",
    "answer_visible",
    "notes",
)

PACKAGE_FILES = ("image.png", "task.json", "spec.json")


def _display(path: Path) -> str:
    """Return a repo-relative POSIX path when possible, else the absolute path."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _accepted_packages(tasks_dir: Path) -> list[Path]:
    """Return the sorted package folders that contain the three expected files."""
    packages = [
        entry
        for entry in sorted(tasks_dir.iterdir(), key=lambda path: path.name)
        if entry.is_dir() and all((entry / name).is_file() for name in PACKAGE_FILES)
    ]
    if not packages:
        raise SystemExit(f"error: no task packages found in {tasks_dir}")
    return packages


def _read_task(package: Path) -> tuple[str, str]:
    """Read the question and ground-truth answer from a package's task.json."""
    task = json.loads((package / "task.json").read_text(encoding="utf-8"))
    question = task.get("question")
    answer = task.get("answer")
    if not isinstance(question, str) or not question.strip():
        raise SystemExit(f"error: {package / 'task.json'} has no question text")
    if answer is None or isinstance(answer, bool):
        raise SystemExit(f"error: {package / 'task.json'} has no answer")
    answer_text = str(answer).strip()
    if not answer_text:
        raise SystemExit(f"error: {package / 'task.json'} has an empty answer")
    return question.strip(), answer_text


def _clear_old_images(images_dir: Path) -> None:
    """Remove PNG copies left by an earlier run so the folder matches the sheet."""
    for stale in images_dir.glob("*.png"):
        stale.unlink()


def _write_sheet(sheet_path: Path, items: list[dict[str, str]]) -> None:
    """Write the numbered audit sheet the reviewer fills in by hand."""
    lines = [
        "# Human audit sheet",
        "",
        "**Instructions:** Answer each question from the image only. Do not look "
        "at the answer key. Fill in the blanks below each question.",
        "",
    ]
    for number, item in enumerate(items, start=1):
        lines.extend(
            [
                f"{number}. **Image:** `{item['image']}`",
                f"   **Question:** {item['question']}",
                "",
                "   - Reviewer's answer read from the image: ____",
                "   - Is the question about something visible in the image? (yes / no)",
                "   - Is the answer visible in the image? (yes / no)",
                "   - Notes: ____",
                "",
            ]
        )
    sheet_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_csv(csv_path: Path, packages: list[Path]) -> None:
    """Write one empty row per sampled package, ready to be filled in."""
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for number, package in enumerate(packages, start=1):
            writer.writerow({"item": number, "package": package.name})


def _write_key(key_path: Path, key: dict[str, str]) -> None:
    """Write the package -> answer key outside the repository tree."""
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(
        json.dumps(key, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_audit_kit(
    tasks_dir: Path,
    audit_dir: Path,
    key_path: Path,
    count: int,
) -> tuple[list[Path], Path, Path, Path]:
    """Sample packages and write the images, sheet, CSV template and answer key."""
    if count < 1:
        raise SystemExit("error: --count must be at least 1")

    packages = _accepted_packages(tasks_dir)
    if count > len(packages):
        raise SystemExit(
            f"error: asked for {count} items but only {len(packages)} packages exist"
        )

    chosen = random.Random(SEED).sample(packages, count)

    images_dir = audit_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    _clear_old_images(images_dir)

    items: list[dict[str, str]] = []
    key: dict[str, str] = {}
    for package in chosen:
        question, answer = _read_task(package)
        shutil.copy2(package / "image.png", images_dir / f"{package.name}.png")
        items.append(
            {
                "image": f"audit/images/{package.name}.png",
                "question": question,
            }
        )
        key[package.name] = answer

    sheet_path = audit_dir / "audit_sheet.md"
    csv_path = audit_dir / "results_template.csv"
    _write_sheet(sheet_path, items)
    _write_csv(csv_path, chosen)
    _write_key(key_path, key)

    return chosen, sheet_path, csv_path, key_path


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, build the kit and print a one-line summary."""
    parser = argparse.ArgumentParser(
        description="Build a reviewer-ready audit sheet for a random sample of tasks."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"number of packages to sample without replacement (default: {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=REPO_ROOT / "out" / "pool" / "tasks",
        help="folder of accepted task packages (default: out/pool/tasks)",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=REPO_ROOT / "audit",
        help="folder for the reviewer kit (default: audit)",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=REPO_ROOT / "out" / "audit_key.json",
        help="answer key path, kept outside the repo (default: out/audit_key.json)",
    )
    args = parser.parse_args(argv)

    chosen, sheet_path, csv_path, key_path = build_audit_kit(
        args.tasks, args.audit_dir, args.key, args.count
    )

    images_dir = args.audit_dir / "images"
    print(
        f"wrote {len(chosen)} audit items: {_display(sheet_path)}, "
        f"{_display(csv_path)}, {_display(images_dir)}/ "
        f"({len(chosen)} images), {_display(key_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
