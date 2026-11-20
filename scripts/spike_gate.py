"""The 25 Nov container gate: health, version and one fixed default generation.

Run it against a server that is already listening::

    python scripts/spike_gate.py --base http://127.0.0.1:3000

The form payload is the published default (seed 20261206, three charts per
type, bar and line, tourism, all five question types, standard, question on the
image). The gate reads the results page, so it makes no assumption about the
server's internals. Only the standard library is used.

The plan says "15 tasks". The real pipeline attempts 14 at this seed because
its margin rule skips one planned task, so the gate is: attempted is at least
14 and every attempted task passes all seven checks. The summary says this in
plain words.

It prints one JSON document and exits 0 only when every gate passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 4_500_000
MAX_SECONDS = 180.0
MIN_ATTEMPTED = 14
EXPECTED_PLANNED = 15

DEFAULT_FORM: list[tuple[str, str]] = [
    ("seed", "20261206"),
    ("charts_per_type", "3"),
    ("chart_types", "bar"),
    ("chart_types", "line"),
    ("topic", "tourism"),
    ("question_types", "value_lookup"),
    ("question_types", "extremum"),
    ("question_types", "rank_k"),
    ("question_types", "pair_compare"),
    ("question_types", "series_at_x"),
    ("difficulty", "standard"),
    ("question_in_image", "on"),
]

GATE_NOTE = (
    f"The plan says {EXPECTED_PLANNED} tasks. The real pipeline attempts 14 at "
    "this seed (15 planned) because the margin rule skips one planned task. "
    f"The gate is therefore: attempted >= {MIN_ATTEMPTED} and every attempted "
    "task passes 7/7 checks."
)

_COUNT_RE = re.compile(
    r"<th>\s*(Attempted|Accepted|Rejected)\s*</th>\s*<td>\s*(?:<strong>)?\s*(\d+)",
    re.IGNORECASE,
)
_CHECK_RE = re.compile(r"(\d+)\s+of\s+(\d+)\s+checks passed")

FORBIDDEN_TEXT = ("gemini", "openrouter", "api_key")


def parse_counts(html: str) -> dict[str, int]:
    """Read the Attempted, Accepted and Rejected numbers from a results page."""
    counts: dict[str, int] = {}
    for label, value in _COUNT_RE.findall(html):
        counts[label.lower()] = int(value)
    return counts


def parse_check_summaries(html: str) -> list[tuple[int, int]]:
    """Every "N of M checks passed" line on a results page, in page order."""
    return [(int(passed), int(total)) for passed, total in _CHECK_RE.findall(html)]


def count_png_images(html: str) -> int:
    """How many inline PNG data URIs the page carries."""
    return html.count("data:image/png")


def _request(
    method: str, url: str, data: bytes | None, timeout: float
) -> tuple[int, bytes]:
    """One HTTP request; return its status and the whole body."""
    headers = {"User-Agent": "taskfactory-spike-gate"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def _gate(name: str, passed: bool, detail: str) -> dict[str, Any]:
    """One named gate result."""
    return {"name": name, "passed": bool(passed), "detail": detail}


def _text_response(body: bytes) -> str:
    """A response body as text, never raising on odd bytes."""
    return body.decode("utf-8", "replace")


def run_gate(base: str, timeout: float = 240.0) -> dict[str, Any]:
    """Run every gate against ``base`` and return the summary dictionary."""
    base = base.rstrip("/")
    summary: dict[str, Any] = {
        "base": base,
        "date": time.strftime("%Y-%m-%d"),
        "gate_note": GATE_NOTE,
        "health": {},
        "version": {},
        "generation": {},
        "gates": [],
    }
    gates: list[dict[str, Any]] = summary["gates"]

    try:
        status, body = _request("GET", f"{base}/api/health", None, 30.0)
        payload = json.loads(body)
        ok = status == 200 and payload.get("status") == "ok"
        summary["health"] = {
            "http_status": status,
            "status": payload.get("status"),
            "python": payload.get("python"),
        }
        gates.append(
            _gate(
                "health is ok",
                ok,
                f"HTTP {status}, status={payload.get('status')!r}",
            )
        )
    except (OSError, URLError, ValueError) as error:
        summary["health"] = {"error": str(error)}
        gates.append(_gate("health is ok", False, f"request failed: {error}"))

    try:
        status, body = _request("GET", f"{base}/api/version", None, 30.0)
        payload = json.loads(body)
        commit = payload.get("commit")
        present = status == 200 and isinstance(commit, str) and bool(commit.strip())
        summary["version"] = {
            "http_status": status,
            "version": payload.get("version"),
            "commit": commit,
        }
        gates.append(
            _gate(
                "version has a commit",
                present,
                f"HTTP {status}, commit={commit!r}",
            )
        )
    except (OSError, URLError, ValueError) as error:
        summary["version"] = {"error": str(error)}
        gates.append(_gate("version has a commit", False, f"request failed: {error}"))

    payload = urlencode(DEFAULT_FORM).encode("ascii")
    started = time.perf_counter()
    try:
        status, body = _request("POST", f"{base}/api/generate", payload, timeout)
        elapsed = time.perf_counter() - started
        page = _text_response(body)
        counts = parse_counts(page)
        checks = parse_check_summaries(page)
        images = count_png_images(page)

        attempted = counts.get("attempted")
        accepted = counts.get("accepted")
        rejected = counts.get("rejected")
        lowered = page.lower()
        found_text = [word for word in FORBIDDEN_TEXT if word in lowered]

        summary["generation"] = {
            "http_status": status,
            "body_bytes": len(body),
            "elapsed_seconds": round(elapsed, 3),
            "images": images,
            "attempted": attempted,
            "accepted": accepted,
            "rejected": rejected,
            "check_summaries": checks,
            "forbidden_text": found_text,
        }

        gates.append(
            _gate("generation returns 200", status == 200, f"HTTP {status}")
        )
        gates.append(
            _gate(
                f"body under {MAX_BODY_BYTES} bytes",
                len(body) < MAX_BODY_BYTES,
                f"{len(body)} bytes",
            )
        )
        gates.append(
            _gate(
                f"elapsed under {MAX_SECONDS:.0f} seconds",
                elapsed < MAX_SECONDS,
                f"{elapsed:.1f} seconds",
            )
        )
        gates.append(
            _gate(
                f"attempted at least {MIN_ATTEMPTED}",
                attempted is not None and attempted >= MIN_ATTEMPTED,
                f"attempted={attempted}",
            )
        )

        counted_all = (
            attempted is not None
            and accepted is not None
            and rejected is not None
            and accepted == attempted
            and rejected == 0
            and len(checks) == accepted
            and len(checks) > 0
            and all(passed == 7 and total == 7 for passed, total in checks)
        )
        gates.append(
            _gate(
                "every attempted task passes 7/7 checks",
                counted_all,
                (
                    f"accepted={accepted} of attempted={attempted}, "
                    f"rejected={rejected}, check lines={len(checks)}"
                ),
            )
        )
        gates.append(
            _gate(
                "no model or key text in the body",
                not found_text,
                f"found={found_text}",
            )
        )
    except (OSError, URLError, ValueError) as error:
        elapsed = time.perf_counter() - started
        summary["generation"] = {
            "error": str(error),
            "elapsed_seconds": round(elapsed, 3),
        }
        gates.append(_gate("generation returns 200", False, f"request failed: {error}"))
        gates.append(
            _gate(
                "every attempted task passes 7/7 checks",
                False,
                "no results page to read",
            )
        )

    summary["passed"] = all(item["passed"] for item in gates)
    summary["failures"] = [
        item["name"] for item in gates if not item["passed"]
    ]
    return summary


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments, run the gate and print the JSON summary."""
    parser = argparse.ArgumentParser(
        description=(
            "Check a running TaskFactory server: health, version and one "
            "default generation, gated on size, time and 7/7 checks."
        )
    )
    parser.add_argument(
        "--base",
        default="http://127.0.0.1:3000",
        help="base URL of the running server (default: http://127.0.0.1:3000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="seconds to wait for the generation response (default: 240)",
    )
    args = parser.parse_args(argv)

    summary = run_gate(args.base, timeout=args.timeout)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
