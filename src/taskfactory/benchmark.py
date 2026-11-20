"""Benchmark runner: each evaluated model answers the frozen items, and every answer is graded.

Answers come through :class:`taskfactory.llm.ModelClient`, so each one is cached on disk and
a rerun makes no network call for an answer it already has. Grading is deterministic and uses
no model. Output under ``out_dir``::

    results/<safe model id>.jsonl   one line per item asked, with its grade
    benchmark_metrics.json          counts, accuracy with its 95% Wilson interval, and error labels per model

Standard library only.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from taskfactory.config import load_models
from taskfactory.evalset import build_eval_set, load_eval_set, read_json_object, write_atomic
from taskfactory.llm import (
    ModelClient,
    ModelError,
    RateLimited,
    _read_cache_file,
    cache_key,
    image_sha256,
    safe_model_id,
)
from taskfactory.questions import normalise_answer

__all__ = [
    "API_KEY_VARS",
    "ERROR_LABELS",
    "MAX_TOKENS",
    "RETRY_MAX_TOKENS",
    "build_prompt",
    "entity_names",
    "error_label",
    "grade",
    "load_api_keys",
    "run_benchmark",
    "run_eval",
    "wilson_interval",
]

PROMPT_HEAD = (
    "Look at the chart image and answer the question. Reply with only the answer, "
    "exactly as it is printed on the chart, nothing else.\n\nQuestion: "
)
MAX_TOKENS = 1024
RETRY_MAX_TOKENS = 4096  # the one larger budget an empty reply gets; reasoning models spend the budget first
LONG_REPLY_CHARS = 60
ERROR_LABELS = ("empty", "refusal_or_long", "wrong_entity", "wrong_value", "other")
API_KEY_VARS = ("GEMINI_API_KEY", "OPENROUTER_API_KEY")

_CURRENCY_SYMBOLS = frozenset("$€£¥₹¢₩₽₺")
_PLAIN_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
_NUMBER_IN_TEXT = re.compile(r"(?<![\w.])[+-]?[0-9][0-9,]*(?:\.[0-9]+)?")


def build_prompt(question: str) -> str:
    """The exact prompt every evaluated model receives for one item."""
    return PROMPT_HEAD + question


def grade(reply: str, answer: str) -> bool:
    """True when the reply is the answer.

    Both sides go through normalise_answer and must match exactly. The one exception: when
    both parse as numbers once thousands separators and currency symbols are removed, they are
    compared as numbers with zero tolerance, so "76471" and "76,471" match.
    """
    got = normalise_answer(reply)
    want = normalise_answer(answer)
    if got == want:
        return True
    got_number = _as_number(got)
    want_number = _as_number(want)
    return got_number is not None and want_number is not None and got_number == want_number


def error_label(reply: str, answer: str, entities: Iterable[str]) -> str:
    """The one label for a wrong reply. The first rule that matches wins.

    ``entities`` are the item's category and series names (its spec's x_labels and series names).

    - ``empty``: the reply is blank.
    - ``refusal_or_long``: the reply is longer than 60 characters.
    - ``wrong_entity``: the reply equals a different entity, or the answer is an entity and the
      reply names a different one as a whole word.
    - ``wrong_value``: the reply contains a number that the answer does not contain.
    - ``other``: anything else.
    """
    text = reply.strip()
    if not text:
        return "empty"
    if len(text) > LONG_REPLY_CHARS:
        return "refusal_or_long"

    got = normalise_answer(text)
    want = normalise_answer(answer)
    names = {normalise_answer(name) for name in entities if name.strip()}
    others = names - {want}
    if got in others:
        return "wrong_entity"
    if want in names and any(_mentions(got, name) for name in others):
        return "wrong_entity"

    answer_numbers = _numbers_in(want)
    if any(number not in answer_numbers for number in _numbers_in(text)):
        return "wrong_value"
    return "other"


def entity_names(spec: Mapping[str, Any]) -> list[str]:
    """The category and series names a chart prints: its x_labels and each non-empty series name."""
    names = [str(label) for label in spec.get("x_labels", [])]
    for series in spec.get("series", []):
        name = series.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def load_api_keys(env_file: Path, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Set the API key variables from a KEY=VALUE file, where they are not already set.

    Only the names in API_KEY_VARS are read. Returns the names that were set. Values are never
    returned, printed or logged, and a missing file is not an error.
    """
    target: MutableMapping[str, str] = os.environ if environ is None else environ
    path = Path(env_file)
    if not path.is_file():
        return []
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in API_KEY_VARS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value and name not in found:
            found[name] = value

    loaded: list[str] = []
    for name in API_KEY_VARS:
        if name in found and not (target.get(name) or "").strip():
            target[name] = found[name]
            loaded.append(name)
    return loaded


def run_benchmark(
    items: Sequence[Mapping[str, Any]],
    *,
    items_dir: Path,
    models: Sequence[Mapping[str, Any]],
    client: ModelClient,
    out_dir: Path,
    eval_set_sha256: str,
    eval_set_items: int | None = None,
    evaluated_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Ask every model in ``models`` each item, grade the answers, and write results and metrics.

    ``models`` are evaluated entries from configs/models.toml (each with ``id`` and ``provider``).
    ``items_dir`` is the folder that the items' ``package_dir`` values are relative to.

    A model whose call is rate limited makes no further network calls and keeps stopped_reason
    "rate_limited". Its answers already in the cache are still read and graded for the remaining
    items, because reading the cache uses no quota; an item with no stored answer is not attempted.
    An empty reply is asked once more at RETRY_MAX_TOKENS. A provider error is recorded against its
    item and the run goes on. ``evaluated_ids`` lists every evaluated model in the config, so a
    partial run keeps the metrics of the models it did not touch.
    """
    if not items:
        raise ValueError("the eval set has no items")
    image_paths, entities = _prepare(items, Path(items_dir))
    out = Path(out_dir)
    per_model: dict[str, dict[str, Any]] = {}
    for model in models:
        model_id = str(model["id"])
        provider = str(model["provider"])
        records, stopped = _run_model(client, model_id, provider, items, image_paths, entities)
        write_atomic(out / "results" / f"{safe_model_id(model_id)}.jsonl", _jsonl_bytes(records))
        per_model[model_id] = _summarise(model_id, provider, records, stopped, len(items))
    return _write_metrics(
        out / "benchmark_metrics.json",
        eval_set_sha256=eval_set_sha256,
        eval_set_items=len(items) if eval_set_items is None else eval_set_items,
        models=per_model,
        evaluated_ids=list(evaluated_ids) if evaluated_ids is not None else [str(m["id"]) for m in models],
    )


def run_eval(
    items_path: Path,
    out_dir: Path,
    models_path: Path,
    *,
    build_from: Path | None = None,
    only_model: str | None = None,
    limit: int | None = None,
    cache_root: Path | None = None,
    client: ModelClient | None = None,
) -> dict[str, Any]:
    """The steps behind ``tf eval``: optionally freeze the set, load it, and run the evaluated models.

    ``build_from`` builds the frozen set at ``items_path`` first. ``limit`` keeps the first N
    items of the set, for smoke tests. ``only_model`` runs one evaluated model. Answers are
    cached under ``cache_root``, which defaults to the parent of ``out_dir``, so out/eval gives
    out/eval/<model>/responses.jsonl, the layout that llm.py documents.
    """
    if limit is not None and limit < 1:
        raise ValueError(f"--limit must be at least 1, got {limit}")
    if build_from is not None:
        build_eval_set(build_from, items_path)
    items, digest = load_eval_set(items_path)

    evaluated = [model for model in load_models(models_path) if model["role"] == "evaluated"]
    if not evaluated:
        raise ValueError(f"{models_path}: no model has role \"evaluated\"")
    evaluated_ids = [str(model["id"]) for model in evaluated]
    selected = evaluated
    if only_model is not None:
        selected = [model for model in evaluated if model["id"] == only_model]
        if not selected:
            raise ValueError(
                f"{only_model!r} is not an evaluated model in {models_path}; "
                f"expected one of: {', '.join(evaluated_ids)}"
            )

    run_items = items if limit is None else items[:limit]
    if client is None:
        client = ModelClient(cache_root if cache_root is not None else Path(out_dir).parent)
    return run_benchmark(
        run_items,
        items_dir=Path(items_path).parent,
        models=selected,
        client=client,
        out_dir=Path(out_dir),
        eval_set_sha256=digest,
        eval_set_items=len(items),
        evaluated_ids=evaluated_ids,
    )


# --- grading helpers ---------------------------------------------------------------------


def _as_number(text: str) -> Decimal | None:
    """The number a whole answer states, once commas and currency symbols are removed. None otherwise."""
    cleaned = "".join(ch for ch in text if ch != "," and ch not in _CURRENCY_SYMBOLS).strip()
    if not _PLAIN_NUMBER.fullmatch(cleaned):
        return None
    return Decimal(cleaned)


def _numbers_in(text: str) -> list[Decimal]:
    """Every number written in the text, with thousands separators removed. "81.1M" gives 81.1."""
    return [Decimal(token.replace(",", "")) for token in _NUMBER_IN_TEXT.findall(text)]


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


# --- running the models --------------------------------------------------------------------


def _prepare(
    items: Sequence[Mapping[str, Any]], items_dir: Path
) -> tuple[dict[str, Path], dict[str, list[str]]]:
    """Check every item's files before any network call, and read each item's entity names."""
    image_paths: dict[str, Path] = {}
    entities: dict[str, list[str]] = {}
    for item in items:
        item_id = str(item["item_id"])
        folder = (items_dir / str(item["package_dir"])).resolve()
        image = folder / "image.png"
        spec_file = folder / "spec.json"
        if not image.is_file():
            raise ValueError(f"{item_id}: image.png not found in {folder}")
        if image_sha256(image) != item["image_sha256"]:
            raise ValueError(f"{item_id}: image.png changed after the eval set was frozen")
        if not spec_file.is_file():
            raise ValueError(f"{item_id}: spec.json not found in {folder}; error labels need its names")
        image_paths[item_id] = image
        entities[item_id] = entity_names(read_json_object(spec_file))
    return image_paths, entities


def _run_model(
    client: ModelClient,
    model_id: str,
    provider: str,
    items: Sequence[Mapping[str, Any]],
    image_paths: Mapping[str, Path],
    entities: Mapping[str, list[str]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Answer and grade each item. A rate limit ends the network calls, not the grading.

    When a call is rate limited the model stops asking, but every item left is still looked up
    in the model's cache: a stored answer is graded as a normal, cached result and an item with
    no stored answer is skipped. Reading the cache makes no network call.
    """
    records: list[dict[str, Any]] = []
    stopped: str | None = None
    secrets = _secret_values()
    cache: Mapping[str, Mapping[str, Any]] | None = None
    for item in items:
        item_id = str(item["item_id"])
        if stopped is None:
            try:
                records.append(
                    _answer_record(
                        client, model_id, provider, item, image_paths[item_id], entities[item_id], secrets
                    )
                )
                continue
            except RateLimited:
                stopped = "rate_limited"
                cache = _read_cache_file(client.cache_path(model_id))
        if cache is not None:
            record = _stored_record(cache, model_id, item, entities[item_id])
            if record is not None:
                records.append(record)
    return records, stopped


def _stored_record(
    cache: Mapping[str, Mapping[str, Any]],
    model_id: str,
    item: Mapping[str, Any],
    entities: Iterable[str],
) -> dict[str, Any] | None:
    """The graded line for an item whose answer is already stored, or None when the cache has none.

    The first ask at MAX_TOKENS is preferred over the empty-reply retry at RETRY_MAX_TOKENS, the
    order _answer_record asks in. ``item["image_sha256"]`` was checked against the image before
    the run, so it is the digest the client used for its key.
    """
    prompt = build_prompt(str(item["question"]))
    image_sha = str(item["image_sha256"])
    for budget in (MAX_TOKENS, RETRY_MAX_TOKENS):
        entry = cache.get(cache_key(model_id, prompt, image_sha, budget))
        if entry is not None:
            return _graded_record(
                item,
                model_id,
                str(entry["text"]),
                True,
                entities,
                max_tokens_used=budget,
                retried=budget == RETRY_MAX_TOKENS,
            )
    return None


def _answer_record(
    client: ModelClient,
    model_id: str,
    provider: str,
    item: Mapping[str, Any],
    image_path: Path,
    entities: Iterable[str],
    secrets: Sequence[str],
) -> dict[str, Any]:
    """The result line for one item. A RateLimited error passes through, so that _run_model stops the model.

    The item is asked at MAX_TOKENS. An empty reply is asked once more at RETRY_MAX_TOKENS; the cache
    keeps the two asks apart. A second empty reply, or any other provider error, is a provider_error line.
    """
    prompt = build_prompt(str(item["question"]))
    budget = MAX_TOKENS
    try:
        reply = client.call(model_id, provider, prompt, image_path=image_path, max_tokens=budget)
    except RateLimited:
        raise
    except ModelError as exc:
        if "empty" not in str(exc):  # any other provider error is final: no second ask
            message = _redact(str(exc), secrets)
            return _provider_error_record(item, model_id, message, max_tokens_used=budget, retried=False)
        budget = RETRY_MAX_TOKENS
        try:
            reply = client.call(model_id, provider, prompt, image_path=image_path, max_tokens=budget)
        except RateLimited:
            raise
        except ModelError as retry_exc:
            message = _redact(str(retry_exc), secrets)
            return _provider_error_record(item, model_id, message, max_tokens_used=budget, retried=True)
        return _graded_record(item, model_id, reply.text, reply.cached, entities, max_tokens_used=budget, retried=True)
    return _graded_record(item, model_id, reply.text, reply.cached, entities, max_tokens_used=budget, retried=False)


def _record_base(item: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    return {
        "answer": item["answer"],
        "family": item["family"],
        "item_id": item["item_id"],
        "model_id": model_id,
        "task_type": item["task_type"],
    }


def _graded_record(
    item: Mapping[str, Any],
    model_id: str,
    reply: str,
    cached: bool,
    entities: Iterable[str],
    *,
    max_tokens_used: int,
    retried: bool,
) -> dict[str, Any]:
    answer = str(item["answer"])
    correct = grade(reply, answer)
    record = _record_base(item, model_id)
    record.update(
        {
            "cached": cached,
            "correct": correct,
            "error_label": None if correct else error_label(reply, answer, entities),
            "error_message": None,
            "error_type": None,
            "max_tokens_used": max_tokens_used,
            "reply": reply,
            "retried_with_larger_budget": retried,
        }
    )
    return record


def _provider_error_record(
    item: Mapping[str, Any],
    model_id: str,
    message: str,
    *,
    max_tokens_used: int,
    retried: bool,
) -> dict[str, Any]:
    record = _record_base(item, model_id)
    record.update(
        {
            "cached": False,
            "correct": False,
            "error_label": None,
            "error_message": message,
            "error_type": "provider_error",
            "max_tokens_used": max_tokens_used,
            "reply": None,
            "retried_with_larger_budget": retried,
        }
    )
    return record


def _secret_values() -> list[str]:
    return [os.environ[name] for name in API_KEY_VARS if os.environ.get(name)]


def _redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


# --- metrics -------------------------------------------------------------------------------


Z_95 = 1.959964  # two-sided 95% normal quantile


def wilson_interval(successes: int, n: int) -> tuple[float | None, float | None]:
    """The 95% Wilson score interval for ``successes`` answered correctly out of ``n`` attempted.

    Returns ``(low, high)``, each rounded to four places, or ``(None, None)`` when ``n`` is zero.
    The score interval stays inside 0 to 1 and is not degenerate at 100%, unlike the normal
    approximation. Both ends are proportions, not percentages.
    """
    if n == 0:
        return (None, None)
    p = successes / n
    z2 = Z_95 * Z_95
    denominator = 1 + z2 / n
    centre = p + z2 / (2 * n)
    margin = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (round((centre - margin) / denominator, 4), round((centre + margin) / denominator, 4))


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def _accuracy_fields(successes: int, n: int) -> dict[str, Any]:
    """The accuracy of one entry and the two ends of its 95% Wilson interval."""
    low, high = wilson_interval(successes, n)
    return {"accuracy": _ratio(successes, n), "accuracy_ci95_low": low, "accuracy_ci95_high": high}


def _group_accuracy(records: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[bool]] = {}
    for record in records:
        groups.setdefault(str(record[key]), []).append(bool(record["correct"]))
    return {
        name: {
            **_accuracy_fields(sum(flags), len(flags)),
            "n_correct": sum(flags),
            "n_items_attempted": len(flags),
        }
        for name, flags in sorted(groups.items())
    }


def _summarise(
    model_id: str,
    provider: str,
    records: Sequence[Mapping[str, Any]],
    stopped: str | None,
    n_items_in_run: int,
) -> dict[str, Any]:
    attempted = len(records)
    correct = sum(1 for record in records if record["correct"])
    label_counts = dict.fromkeys(ERROR_LABELS, 0)
    for record in records:
        if record["error_label"] is not None:
            label_counts[str(record["error_label"])] += 1
    return {
        **_accuracy_fields(correct, attempted),
        "accuracy_by_family": _group_accuracy(records, "family"),
        "accuracy_by_task_type": _group_accuracy(records, "task_type"),
        "error_label_counts": label_counts,
        "model_id": model_id,
        "n_correct": correct,
        "n_items_attempted": attempted,
        "n_items_in_run": n_items_in_run,
        "n_items_not_attempted": n_items_in_run - attempted,
        "provider": provider,
        "provider_error_count": sum(1 for record in records if record["error_type"] == "provider_error"),
        "stopped_reason": stopped,
    }


def _write_metrics(
    path: Path,
    *,
    eval_set_sha256: str,
    eval_set_items: int,
    models: Mapping[str, dict[str, Any]],
    evaluated_ids: Sequence[str],
) -> dict[str, Any]:
    """Write benchmark_metrics.json, keeping earlier entries of models this run did not touch."""
    kept: dict[str, Any] = {}
    if path.is_file():
        try:
            previous = read_json_object(path)
        except ValueError:
            previous = {}
        prior = previous.get("models")
        if previous.get("eval_set_sha256") == eval_set_sha256 and isinstance(prior, dict):
            kept = {mid: prior[mid] for mid in evaluated_ids if mid in prior and mid not in models}
    merged = {**kept, **models}
    metrics: dict[str, Any] = {
        "eval_set_items": eval_set_items,
        "eval_set_sha256": eval_set_sha256,
        "max_tokens": MAX_TOKENS,
        "models": {mid: merged[mid] for mid in sorted(merged)},
    }
    write_atomic(path, _json_bytes(metrics))
    return metrics


def _jsonl_bytes(records: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records).encode("utf-8")


def _json_bytes(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
