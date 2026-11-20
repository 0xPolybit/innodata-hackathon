"""Command-line entry point for TaskFactory."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

COMMANDS = ("generate", "validate", "score", "eval", "report", "run", "diff")

NOT_IMPLEMENTED = "not implemented yet"


def _not_implemented(args: argparse.Namespace) -> int:
    """Placeholder handler shared by every subcommand."""
    print(NOT_IMPLEMENTED)
    return 0


def _add_run_command(subparsers: Any) -> None:
    """Register ``tf run``, the one subcommand that is implemented."""
    run = subparsers.add_parser(
        "run",
        help="generate, check and package the tasks of one run config",
        description=(
            "Sample, render, check and package every implemented task in a run "
            "config. The run metrics are printed as JSON on stdout; a one-line "
            "summary goes to stderr."
        ),
    )
    run.add_argument(
        "--config",
        required=True,
        type=Path,
        help="run config file, for example configs/runs/demo.toml",
    )
    run.add_argument("--out", default="out", type=Path, help="output folder (default: out)")
    run.add_argument("--run-id", required=True, help="run label, written to metrics.json")
    run.add_argument(
        "--tesseract",
        default=None,
        help=(
            "path to the tesseract executable (default: TESSERACT_CMD, then the "
            "usual install path, then PATH)"
        ),
    )
    run.add_argument(
        "--overwrite",
        action="store_true",
        help="delete the packages and summary files already in --out before running",
    )
    run.set_defaults(func=_run_command)


def _summary_line(metrics: dict[str, Any]) -> str:
    """One line describing a finished run."""
    return (
        f"run {metrics['run_id']}: generated {metrics['generated']}, "
        f"passed {metrics['passed']}, rejected {metrics['rejected']}, "
        f"yield {metrics['yield']:.4f}, skipped {len(metrics['skipped'])}"
    )


def _run_command(args: argparse.Namespace) -> int:
    """Handle ``tf run``: run the pipeline, print its metrics, and return an exit code."""
    # Imported here so that --help and the placeholder commands do not load
    # matplotlib and OpenCV.
    from taskfactory.pipeline import run_pipeline

    try:
        metrics = run_pipeline(
            args.config,
            args.out,
            args.run_id,
            tesseract_cmd=args.tesseract,
            overwrite=args.overwrite,
        )
    except (OSError, ValueError) as exc:  # ConfigError is a ValueError
        print(f"tf run: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(_summary_line(metrics), file=sys.stderr)
    return 0


def _add_eval_command(subparsers: Any) -> None:
    """Register ``tf eval``, which runs the evaluated models on the frozen item set."""
    ev = subparsers.add_parser(
        "eval",
        help="run the evaluated models on the frozen item set",
        description=(
            "Run every evaluated model in configs/models.toml on the frozen item set and grade "
            "each answer without a model. Answers are cached, so a rerun resumes where it stopped. "
            "The metrics are printed as JSON on stdout; one summary line per model goes to stderr. "
            "API keys come from GEMINI_API_KEY and OPENROUTER_API_KEY, or from the repo's .env file."
        ),
    )
    ev.add_argument(
        "--items",
        required=True,
        type=Path,
        help="frozen item set (JSON Lines), for example out/eval/items.jsonl",
    )
    ev.add_argument(
        "--out",
        default=Path("out/eval"),
        type=Path,
        help="output folder for results and metrics (default: out/eval)",
    )
    ev.add_argument(
        "--models",
        default=Path("configs/models.toml"),
        type=Path,
        help="model roster (default: configs/models.toml)",
    )
    ev.add_argument(
        "--build-from",
        default=None,
        type=Path,
        help="pool tasks folder: build the frozen set at --items first",
    )
    ev.add_argument("--only-model", default=None, help="run only this evaluated model id")
    ev.add_argument(
        "--limit",
        default=None,
        type=int,
        help="use only the first N items of the set (for smoke tests)",
    )
    ev.set_defaults(func=_eval_command)


def _env_file() -> Path:
    """The repo's .env file, or ./.env when the package is not run from its repo."""
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    return repo_env if repo_env.is_file() else Path.cwd() / ".env"


def _eval_command(args: argparse.Namespace) -> int:
    """Handle ``tf eval``: load the API keys, run the benchmark, and print its metrics."""
    # Imported here so that --help and the placeholder commands do not load the benchmark.
    from taskfactory.benchmark import load_api_keys, run_eval

    load_api_keys(_env_file())  # sets the variables only; no value is printed
    try:
        metrics = run_eval(
            args.items,
            args.out,
            args.models,
            build_from=args.build_from,
            only_model=args.only_model,
            limit=args.limit,
        )
    except (OSError, ValueError) as exc:  # ConfigError is a ValueError
        print(f"tf eval: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(metrics, indent=2, sort_keys=True))
    for model_id, entry in metrics["models"].items():
        print(
            f"eval {model_id}: attempted {entry['n_items_attempted']}, "
            f"correct {entry['n_correct']}, accuracy {entry['accuracy']}, "
            f"stopped {entry['stopped_reason']}",
            file=sys.stderr,
        )
    return 0


def _add_report_command(subparsers: Any) -> None:
    """Register ``tf report``, which writes the static HTML report."""
    report = subparsers.add_parser(
        "report",
        help="write the static HTML report (out/report/index.html)",
        description=(
            "Write index.html and examples/*.png from a pool run and a benchmark run. The report "
            "only reads files: no check is run and no model is called. The self-test section is "
            "filled only when --selftest names a saved self-test result."
        ),
    )
    report.add_argument(
        "--pool",
        default=Path("out/pool"),
        type=Path,
        help="pool run folder with metrics.json, validation.jsonl and tasks/ (default: out/pool)",
    )
    report.add_argument(
        "--eval",
        default=Path("out/eval"),
        type=Path,
        help="benchmark folder with benchmark_metrics.json and items.jsonl (default: out/eval)",
    )
    report.add_argument(
        "--out",
        default=Path("out/report"),
        type=Path,
        help="output folder for index.html and examples/ (default: out/report)",
    )
    report.add_argument(
        "--selftest",
        default=None,
        type=Path,
        help="saved self-test result (JSON); without it the report says the self-test has not run",
    )
    report.set_defaults(func=_report_command)


def _report_command(args: argparse.Namespace) -> int:
    """Handle ``tf report``: write the report and print the path of its index page."""
    # Imported here so that --help and the placeholder commands do not load the report module.
    from taskfactory.report import build_report

    try:
        index = build_report(args.pool, args.eval, args.out, selftest_json=args.selftest)
    except (OSError, ValueError) as exc:
        print(f"tf report: error: {exc}", file=sys.stderr)
        return 2
    print(f"report written: {index}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``tf`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="tf",
        description=(
            "TaskFactory: build, validate, score and benchmark chart and "
            "floor-plan tasks."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name in COMMANDS:
        if name == "run":
            _add_run_command(subparsers)
            continue
        if name == "eval":
            _add_eval_command(subparsers)
            continue
        if name == "report":
            _add_report_command(subparsers)
            continue
        subparser = subparsers.add_parser(
            name,
            help=f"{name} (not implemented yet)",
            description=f"{name} (not implemented yet)",
        )
        subparser.set_defaults(func=_not_implemented)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 0

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
