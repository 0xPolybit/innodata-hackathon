"""Command-line entry point for TaskFactory."""

from __future__ import annotations

import argparse
import errno
import json
import socket
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


def _add_diff_command(subparsers: Any) -> None:
    """Register ``tf diff``, which compares the accepted packages and index of two runs."""
    diff = subparsers.add_parser(
        "diff",
        help="compare the accepted packages and tasks.jsonl of two runs",
        description=(
            "Compare two run folders written by tf run. Accepted packages in tasks/ are matched "
            "by folder name, and a package is changed when any of its files differs in bytes "
            "(images are compared as bytes, never as pixels). tasks.jsonl is compared line by "
            "line, in any order, and the rejected/ folders are counted. The comparison is printed "
            "as JSON on stdout; a one-line summary goes to stderr. Exit code 0 when the accepted "
            "packages and tasks.jsonl match, 1 when they differ, 2 when a run folder is missing."
        ),
    )
    diff.add_argument("run_a", type=Path, help="first run folder, for example out/run_a")
    diff.add_argument("run_b", type=Path, help="second run folder, for example out/run_b")
    diff.set_defaults(func=_diff_command)


def _diff_command(args: argparse.Namespace) -> int:
    """Handle ``tf diff``: compare two runs, print the report, and return 0, 1 or 2."""
    # Imported here, as the other handlers do, so that --help does not load the module.
    from taskfactory.diff import compare_runs

    try:
        result = compare_runs(args.run_a, args.run_b)
    except OSError as exc:  # a missing run, tasks or rejected folder is a FileNotFoundError
        print(f"tf diff: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_json(), indent=2))
    print(result.summary(), file=sys.stderr)
    return result.exit_code


def _port_number(value: str) -> int:
    """An integer port from 1 to 65535."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _add_serve_command(subparsers: Any) -> None:
    """Register ``tf serve``, which runs the form app on Waitress."""
    serve = subparsers.add_parser(
        "serve",
        help="serve the form app on the local machine",
        description=(
            "Serve the TaskFactory form with Waitress. The defaults bind to 127.0.0.1:8000, "
            "so only this machine can reach it; --allow-remote is required for any other host. "
            "No browser is opened automatically."
        ),
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--port",
        default=8000,
        type=_port_number,
        help="port to bind, 1 to 65535 (default: 8000)",
    )
    serve.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow a host other than 127.0.0.1 or localhost",
    )
    serve.set_defaults(func=_serve_command)


def _bind_error(host: str, port: int) -> OSError | None:
    """Return the error a plain socket gets when binding to the host and port, or None."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind((host, port))
        except OSError as exc:
            return exc
    return None


def _serve_command(args: argparse.Namespace) -> int:
    """Handle ``tf serve``: check the host, then run Waitress until Ctrl+C."""
    if args.host not in {"127.0.0.1", "localhost"} and not args.allow_remote:
        print(
            f"tf serve: error: refusing to bind to {args.host!r}; "
            "use --allow-remote to serve other machines",
            file=sys.stderr,
        )
        return 2

    # Checked before Waitress imports the app, so a busy port fails fast and clearly.
    error = _bind_error(args.host, args.port)
    if error is not None:
        in_use = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
        if error.errno in in_use:
            print(
                f"Port {args.port} is already in use by another program. "
                "Run `uv run tf serve --port 8011` (or any free port), then open "
                "http://127.0.0.1:<that port>.",
                file=sys.stderr,
            )
            return 2
        print(
            f"Could not start the web app on {args.host}:{args.port}: {error}",
            file=sys.stderr,
        )
        return 2

    # Imported here so that --help and the other subcommands do not load Waitress.
    from taskfactory.web.app import application
    from waitress import serve

    print(
        f"TaskFactory is running at http://{args.host}:{args.port} "
        "(press Ctrl+C to stop)",
        flush=True,
    )
    serve(application, host=args.host, port=args.port)
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
        if name == "diff":
            _add_diff_command(subparsers)
            continue
        subparser = subparsers.add_parser(
            name,
            help=f"{name} (not implemented yet)",
            description=f"{name} (not implemented yet)",
        )
        subparser.set_defaults(func=_not_implemented)
    # Registered outside the loop: COMMANDS is also the list the placeholder smoke
    # test iterates, and serve must never be mistaken for a placeholder.
    _add_serve_command(subparsers)
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
