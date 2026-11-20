"""Tests for taskfactory.benchmark and the `tf eval` wiring. Offline: providers are replaced, the transport refuses the network."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from taskfactory import cli, llm
from taskfactory.benchmark import (
    ERROR_LABELS,
    MAX_TOKENS,
    build_prompt,
    entity_names,
    error_label,
    grade,
    load_api_keys,
    run_benchmark,
    run_eval,
    wilson_interval,
)
from taskfactory.evalset import build_eval_set, load_eval_set
from taskfactory.llm import ModelError, RateLimited, Reply

BAR_LABELS = ["Wind", "Nuclear", "Gas", "Coal", "Biomass"]
BAR_VALUES = [27171, 12577, 15253, 49552, 46602]
LINE_YEARS = ["2020", "2021"]
LINE_SERIES = {"Geothermal": [84504, 22382], "Nuclear": [49771, 89277], "Biomass": [54867, 10553]}

# (category, printed answer) for the bar items, and (year, series) for the line items.
BAR_QUESTIONS = [("Wind", "27,171"), ("Coal", "49,552"), ("Gas", "15,253")]
LINE_QUESTIONS = [("2020", "Geothermal"), ("2021", "Nuclear"), ("2020", "Biomass")]

# What each fake model says for the item whose answer is the key. Covers every outcome.
REPLIES_BY_ANSWER = {
    "27,171": "27171",  # correct: same number without the separator
    "49,552": "Gas",  # wrong_entity
    "15,253": "16,000",  # wrong_value
    "Geothermal": "Geothermal",  # correct
    "Nuclear": "",  # empty
    "Biomass": "Coal",  # other: Coal is not on the line chart
}

MODELS_TOML = """
[[models]]
id = "model-a"
provider = "gemini"
role = "evaluated"
inputs = ["text", "image"]
test_call = "not run"
limits = "test only"
notes = "test only"

[[models]]
id = "model-b"
provider = "openrouter"
role = "evaluated"
inputs = ["text", "image"]
test_call = "not run"
limits = "test only"
notes = "test only"

[[models]]
id = "local-check"
provider = "gemini"
role = "secondary"
inputs = ["text", "image"]
test_call = "not run"
limits = "test only"
notes = "test only"
"""

PROMPT_TEXT = (
    "Look at the chart image and answer the question. Reply with only the answer, "
    "exactly as it is printed on the chart, nothing else.\n\nQuestion: "
)


def bar_spec() -> dict[str, Any]:
    return {
        "family": "bar",
        "x_labels": BAR_LABELS,
        "series": [{"name": "", "labels": [f"{v:,}" for v in BAR_VALUES], "values": BAR_VALUES}],
    }


def line_spec() -> dict[str, Any]:
    return {
        "family": "line",
        "x_labels": LINE_YEARS,
        "series": [
            {"name": name, "labels": [f"{v:,}" for v in values], "values": values}
            for name, values in LINE_SERIES.items()
        ],
    }


def write_package(pool: Path, item_id: str, task: dict[str, Any], spec: dict[str, Any], image: bytes) -> None:
    folder = pool / item_id
    folder.mkdir(parents=True)
    (folder / "task.json").write_text(json.dumps(task, sort_keys=True), encoding="utf-8")
    (folder / "spec.json").write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
    (folder / "image.png").write_bytes(image)


def make_pool(root: Path) -> Path:
    """Three bar value_lookup packages and three line series_at_x packages."""
    pool = root / "pool" / "tasks"
    for index, (category, answer) in enumerate(BAR_QUESTIONS):
        task = {
            "answer": answer,
            "answer_category": category,
            "answer_printed_in_image": True,
            "domain": "energy",
            "family": "bar",
            "question": f"What value is shown for {category}?",
            "question_in_image": True,
            "reasoning_steps": 1,
            "spec_index": index,
            "task_type": "value_lookup",
        }
        write_package(pool, f"bar-energy-{index:06d}-value_lookup", task, bar_spec(), f"bar image {index}".encode())
    for index, (year, answer) in enumerate(LINE_QUESTIONS):
        task = {
            "answer": answer,
            "answer_category": answer,
            "answer_printed_in_image": True,
            "domain": "energy",
            "family": "line",
            "question": f"Which series is highest in {year}?",
            "question_in_image": True,
            "reasoning_steps": 3,
            "spec_index": index,
            "task_type": "series_at_x",
            "year": year,
        }
        write_package(pool, f"line-energy-{index:06d}-series_at_x", task, line_spec(), f"line image {index}".encode())
    return pool


@pytest.fixture
def eval_set(tmp_path: Path) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Six packages frozen into eval/items.jsonl. Returns (pool, items_path, items)."""
    pool = make_pool(tmp_path)
    items_path = tmp_path / "eval" / "items.jsonl"
    build_eval_set(pool, items_path, n=6, seed=11)
    items, _ = load_eval_set(items_path)
    return pool, items_path, items


def write_models(path: Path) -> Path:
    path.write_text(MODELS_TOML, encoding="utf-8")
    return path


def replies_for(items: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {str(item["item_id"]): REPLIES_BY_ANSWER[str(item["answer"])] for item in items}


def read_results(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").split("\n") if line]


def client_for(cache_root: Path) -> llm.ModelClient:
    return llm.ModelClient(cache_root, env={}, min_intervals={"gemini": 0.0, "openrouter": 0.0})


class FakeProvider:
    """Stands in for every provider function. A model's reply for an item comes from the reply table.

    ``fail_after`` maps a model id to the number of answers it gives before every later call is
    rate limited. ``error_items`` are item ids whose call raises a ModelError.
    """

    def __init__(
        self,
        replies: Mapping[str, str],
        *,
        fail_after: Mapping[str, int] | None = None,
        error_items: Iterable[str] = (),
    ) -> None:
        self.replies = dict(replies)
        self.fail_after = dict(fail_after or {})
        self.error_items = set(error_items)
        self.calls: list[tuple[str, str]] = []  # (model id, item id), in call order

    def __call__(
        self,
        model_id: str,
        prompt: str,
        image_path: str | Path | None = None,
        max_tokens: int = 1024,
        *,
        env: Mapping[str, str] | None = None,
        min_interval: float | None = None,
    ) -> Reply:
        assert image_path is not None
        assert prompt.startswith(PROMPT_TEXT), "the prompt must start with the exact instruction text"
        assert max_tokens == 1024
        item_id = Path(image_path).parent.name
        self.calls.append((model_id, item_id))
        answered = sum(1 for called, _ in self.calls if called == model_id)
        if model_id in self.fail_after and answered > self.fail_after[model_id]:
            raise RateLimited("gemini still returned HTTP 429 after 5 attempts", provider="gemini", status=429)
        if item_id in self.error_items:
            raise ModelError("gemini returned HTTP 500", provider="gemini", status=500)
        return Reply(self.replies[item_id], 200, False, model_id, "gemini")


def install(monkeypatch: pytest.MonkeyPatch, provider: Callable[..., Reply]) -> None:
    for name in ("gemini", "openrouter"):
        monkeypatch.setitem(llm.PROVIDERS, name, provider)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The network is refused, and no API key from the real environment is visible."""

    def refuse(request_obj: urllib.request.Request) -> None:
        raise AssertionError(f"a test tried the network: {request_obj.full_url}")

    monkeypatch.setattr(llm, "_send", refuse)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


class FakeModelClient:
    """Stands in for ModelClient. Each call takes the next scripted outcome: a Reply, or an error to raise.

    ``cache_dir`` is the root of the fake's responses.jsonl layout, so a test can store answers that
    the benchmark reads after a rate-limit stop. ``budgets`` records the max_tokens of every call, in order.
    """

    def __init__(self, *outcomes: Reply | BaseException, cache_dir: Path | None = None) -> None:
        self.outcomes = list(outcomes)
        self.budgets: list[int] = []
        self.cache_dir = cache_dir

    def cache_path(self, model_id: str) -> Path:
        assert self.cache_dir is not None, "the fake needs a cache_dir to answer a cache lookup"
        return self.cache_dir / "eval" / llm.safe_model_id(model_id) / "responses.jsonl"

    def call(
        self,
        model_id: str,
        provider: str,
        prompt: str,
        image_path: str | Path | None = None,
        max_tokens: int = 1024,
    ) -> Reply:
        self.budgets.append(max_tokens)
        if not self.outcomes:
            raise AssertionError("the benchmark asked for more answers than the test scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def store_cached_answer(
    client: FakeModelClient, model_id: str, item: Mapping[str, Any], reply: str, max_tokens: int = MAX_TOKENS
) -> None:
    """Put an answer for an item in the fake's responses.jsonl, as an earlier run would have."""
    path = client.cache_path(model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = llm.cache_key(model_id, build_prompt(str(item["question"])), str(item["image_sha256"]), max_tokens)
    record = {"key": key, "model_id": model_id, "text": reply}
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record) + "\n")


def empty_reply_error() -> ModelError:
    """The error llm raises for a reply with no text, as OpenRouter does when reasoning uses up the budget."""
    return ModelError(
        "openrouter reply was empty (reasoning models can use up the max_tokens budget before answering)",
        provider="openrouter",
        status=200,
    )


def run_one_item(tmp_path: Path, client: FakeModelClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one item whose answer is "OK" through run_benchmark. Returns its result lines and its model's metrics."""
    pool = tmp_path / "pool"
    item_id = "bar-energy-000000-value_lookup"
    task = {"answer": "OK", "family": "bar", "task_type": "value_lookup"}
    write_package(pool, item_id, task, bar_spec(), b"one image")
    item = {
        "answer": "OK",
        "family": "bar",
        "image_sha256": llm.image_sha256(pool / item_id / "image.png"),
        "item_id": item_id,
        "package_dir": item_id,
        "question": "What value is shown for Wind?",
        "task_type": "value_lookup",
    }
    out = tmp_path / "eval"
    metrics = run_benchmark(
        [item],
        items_dir=pool,
        models=[{"id": "model-a", "provider": "openrouter"}],
        client=client,
        out_dir=out,
        eval_set_sha256="0" * 64,
    )
    return read_results(out / "results" / "model-a.jsonl"), metrics["models"]["model-a"]


# --- prompt and grading ---------------------------------------------------------------------


def test_prompt_is_the_exact_instruction_followed_by_the_question() -> None:
    assert build_prompt("What value is shown for Wind?") == (
        "Look at the chart image and answer the question. Reply with only the answer, "
        "exactly as it is printed on the chart, nothing else.\n\nQuestion: What value is shown for Wind?"
    )


@pytest.mark.parametrize(
    ("reply", "answer", "expected"),
    [
        ("76,471", "76,471", True),
        ("76471", "76,471", True),
        ("$76,471", "76,471", True),
        ("Spain", "spain", True),
        ("spain.", "Spain", True),
        ("  Coal  ", "coal", True),
        ("81.1M", "81.2M", False),
        ("76,471 GWh", "76,471", False),
        ("76,472", "76,471", False),
        ("Gas", "Coal", False),
    ],
)
def test_grade_compares_normalised_text_and_numbers_exactly(reply: str, answer: str, expected: bool) -> None:
    assert grade(reply, answer) is expected


def test_entity_names_are_the_x_labels_and_the_non_empty_series_names() -> None:
    assert entity_names(bar_spec()) == BAR_LABELS
    assert entity_names(line_spec()) == ["2020", "2021", "Geothermal", "Nuclear", "Biomass"]


@pytest.mark.parametrize(
    ("reply", "answer", "entities", "label"),
    [
        ("", "27,171", BAR_LABELS, "empty"),
        ("   ", "Coal", BAR_LABELS, "empty"),
        (
            "I cannot read the value because the axis labels are too small to tell.",
            "27,171",
            BAR_LABELS,
            "refusal_or_long",
        ),
        ("Gas", "Coal", BAR_LABELS, "wrong_entity"),
        ("Nuclear", "27,171", BAR_LABELS, "wrong_entity"),
        ("Coal or Gas", "Coal", BAR_LABELS, "wrong_entity"),
        ("Gas 15,253", "Coal", BAR_LABELS, "wrong_entity"),  # entity rule comes before the number rule
        ("12,577", "27,171", BAR_LABELS, "wrong_value"),
        ("81.1M", "81.2M", ["Japan"], "wrong_value"),
        ("49,552", "Coal", BAR_LABELS, "wrong_value"),  # a value offered for a category question
        ("27,171 GWh", "27,171", BAR_LABELS, "other"),
        ("coal mine", "Coal", BAR_LABELS, "other"),
    ],
)
def test_error_label_follows_the_first_matching_rule(
    reply: str, answer: str, entities: list[str], label: str
) -> None:
    assert error_label(reply, answer, entities) == label


def test_error_labels_are_the_five_documented_ones() -> None:
    assert ERROR_LABELS == ("empty", "refusal_or_long", "wrong_entity", "wrong_value", "other")


# --- the Wilson accuracy interval ------------------------------------------------------------


def test_wilson_interval_is_the_95_percent_score_interval() -> None:
    # Computed with z = 1.959964, rounded to four places.
    assert wilson_interval(195, 200) == (0.9428, 0.9893)  # a 97.5% rate
    assert wilson_interval(191, 200) == (0.9167, 0.9761)  # a 95.5% rate


def test_wilson_interval_is_none_when_nothing_was_attempted() -> None:
    assert wilson_interval(0, 0) == (None, None)


# --- running the models ---------------------------------------------------------------------


def test_every_item_is_graded_and_counted(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    install(monkeypatch, FakeProvider(replies_for(items)))
    out = tmp_path / "eval"

    metrics = run_eval(items_path, out, models, client=client_for(tmp_path))

    rows = {row["answer"]: row for row in read_results(out / "results" / "model-a.jsonl")}
    assert len(rows) == 6
    assert rows["27,171"]["reply"] == "27171" and rows["27,171"]["correct"] is True
    assert rows["27,171"]["error_label"] is None and rows["27,171"]["cached"] is False
    assert rows["49,552"]["error_label"] == "wrong_entity" and rows["49,552"]["correct"] is False
    assert rows["15,253"]["error_label"] == "wrong_value"
    assert rows["Geothermal"]["correct"] is True
    assert rows["Nuclear"]["error_label"] == "empty"
    assert rows["Biomass"]["error_label"] == "other"
    assert all(row["model_id"] == "model-a" for row in rows.values())
    assert all(row["max_tokens_used"] == 1024 and row["retried_with_larger_budget"] is False for row in rows.values())

    entry = metrics["models"]["model-a"]
    assert entry["provider"] == "gemini" and entry["model_id"] == "model-a"
    assert entry["n_items_attempted"] == 6
    assert entry["n_correct"] == 2
    assert entry["accuracy"] == 0.3333
    assert entry["error_label_counts"] == {
        "empty": 1,
        "other": 1,
        "refusal_or_long": 0,
        "wrong_entity": 1,
        "wrong_value": 1,
    }
    assert entry["accuracy_by_family"]["bar"] == {
        "accuracy": 0.3333,
        "accuracy_ci95_high": 0.7923,
        "accuracy_ci95_low": 0.0615,
        "n_correct": 1,
        "n_items_attempted": 3,
    }
    assert entry["accuracy_by_task_type"]["series_at_x"]["n_correct"] == 1
    assert entry["stopped_reason"] is None
    assert entry["provider_error_count"] == 0
    assert metrics["models"]["model-b"]["provider"] == "openrouter"
    assert "local-check" not in metrics["models"]  # secondary models never run


def test_rate_limit_stops_one_model_cleanly_and_the_next_run_resumes(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    replies = replies_for(items)

    limited = FakeProvider(replies, fail_after={"model-a": 2})
    install(monkeypatch, limited)
    first = run_eval(items_path, out, models, client=client_for(tmp_path))

    stopped = first["models"]["model-a"]
    assert stopped["stopped_reason"] == "rate_limited"
    assert stopped["n_items_attempted"] == 2
    assert stopped["n_items_not_attempted"] == 4
    assert len(read_results(out / "results" / "model-a.jsonl")) == 2
    assert first["models"]["model-b"]["stopped_reason"] is None
    assert first["models"]["model-b"]["n_items_attempted"] == 6

    # The next run keeps the two stored answers and asks only for the four that are left.
    stored_ids = {row["item_id"] for row in read_results(out / "results" / "model-a.jsonl")}
    resumed = FakeProvider(replies)
    install(monkeypatch, resumed)
    second = run_eval(items_path, out, models, client=client_for(tmp_path))

    asked = [item_id for model, item_id in resumed.calls if model == "model-a"]
    assert len(asked) == 4
    assert set(asked).isdisjoint(stored_ids)
    assert set(asked) | stored_ids == {str(item["item_id"]) for item in items}
    assert [model for model, _ in resumed.calls].count("model-b") == 0  # all of model-b came from the cache
    assert second["models"]["model-a"]["stopped_reason"] is None
    assert second["models"]["model-a"]["n_items_attempted"] == 6
    cached_flags = [row["cached"] for row in read_results(out / "results" / "model-a.jsonl")]
    assert cached_flags.count(True) == 2


def test_a_rate_limited_model_still_grades_answers_from_the_cache(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]]
) -> None:
    _, items_path, items = eval_set
    run_items = items[:3]
    cached_item = run_items[2]  # the first two items have no stored answer
    limited = RateLimited("openrouter still returned HTTP 429 after 5 attempts", provider="openrouter", status=429)
    client = FakeModelClient(limited, cache_dir=tmp_path / "cache")
    store_cached_answer(client, "model-a", cached_item, str(cached_item["answer"]))
    out = tmp_path / "eval"

    metrics = run_benchmark(
        run_items,
        items_dir=items_path.parent,
        models=[{"id": "model-a", "provider": "openrouter"}],
        client=client,
        out_dir=out,
        eval_set_sha256="0" * 64,
    )

    (row,) = read_results(out / "results" / "model-a.jsonl")
    assert row["item_id"] == cached_item["item_id"]
    assert (row["cached"], row["correct"], row["reply"]) == (True, True, str(cached_item["answer"]))
    assert client.budgets == [MAX_TOKENS]  # the stop ends the calls; the cache is read for free
    entry = metrics["models"]["model-a"]
    assert entry["stopped_reason"] == "rate_limited"
    assert (entry["n_items_attempted"], entry["n_items_not_attempted"]) == (1, 2)
    assert (entry["n_correct"], entry["accuracy"]) == (1, 1.0)


def test_a_provider_error_is_recorded_against_its_item_and_the_run_goes_on(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    failing_item = str(items[1]["item_id"])
    install(monkeypatch, FakeProvider(replies_for(items), error_items=[failing_item]))

    metrics = run_eval(items_path, out, models, client=client_for(tmp_path))

    row = next(r for r in read_results(out / "results" / "model-a.jsonl") if r["item_id"] == failing_item)
    assert row["error_type"] == "provider_error"
    assert row["correct"] is False
    assert row["reply"] is None
    assert row["error_label"] is None
    assert "HTTP 500" in row["error_message"]
    entry = metrics["models"]["model-a"]
    assert entry["n_items_attempted"] == 6
    assert entry["provider_error_count"] == 1
    assert entry["stopped_reason"] is None


def test_answers_already_in_the_cache_make_no_provider_call(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    install(monkeypatch, FakeProvider(replies_for(items)))
    run_eval(items_path, out, models, client=client_for(tmp_path))

    def must_not_be_called(*args: Any, **kwargs: Any) -> Reply:
        raise AssertionError("a provider was called for an answer that is already cached")

    install(monkeypatch, must_not_be_called)
    metrics = run_eval(items_path, out, models, client=client_for(tmp_path))

    assert all(row["cached"] for row in read_results(out / "results" / "model-a.jsonl"))
    assert all(row["cached"] for row in read_results(out / "results" / "model-b.jsonl"))
    assert metrics["models"]["model-a"]["n_items_attempted"] == 6
    assert metrics["models"]["model-a"]["accuracy"] == 0.3333


def test_metrics_file_has_sorted_keys_no_timestamps_and_four_decimal_accuracy(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    install(monkeypatch, FakeProvider(replies_for(items)))

    run_eval(items_path, out, models, client=client_for(tmp_path))

    text = (out / "benchmark_metrics.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert text == json.dumps(data, sort_keys=True, indent=2) + "\n"
    assert "timestamp" not in text and "created" not in text
    assert data["eval_set_sha256"] == load_eval_set(items_path)[1]
    assert data["eval_set_items"] == 6
    for entry in data["models"].values():
        assert entry["accuracy"] == round(entry["n_correct"] / entry["n_items_attempted"], 4)
        assert entry["accuracy"] == round(entry["accuracy"], 4)
        assert entry["accuracy_ci95_low"] < entry["accuracy"] < entry["accuracy_ci95_high"]


def test_only_model_updates_its_entry_and_keeps_the_others(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    install(monkeypatch, FakeProvider(replies_for(items)))
    run_eval(items_path, out, models, client=client_for(tmp_path))

    partial = run_eval(items_path, out, models, only_model="model-a", limit=2, client=client_for(tmp_path))

    assert partial["models"]["model-a"]["n_items_in_run"] == 2
    assert partial["models"]["model-a"]["n_items_attempted"] == 2
    assert partial["models"]["model-b"]["n_items_in_run"] == 6
    assert len(read_results(out / "results" / "model-a.jsonl")) == 2


def test_only_model_must_name_an_evaluated_model(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]]
) -> None:
    _, items_path, _ = eval_set
    models = write_models(tmp_path / "models.toml")
    with pytest.raises(ValueError, match="not an evaluated model"):
        run_eval(items_path, tmp_path / "eval", models, only_model="local-check", client=client_for(tmp_path))


def test_limit_runs_the_first_items_only_and_must_be_positive(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    out = tmp_path / "eval"
    install(monkeypatch, FakeProvider(replies_for(items)))

    metrics = run_eval(items_path, out, models, limit=2, client=client_for(tmp_path))

    assert metrics["eval_set_items"] == 6
    assert metrics["models"]["model-a"]["n_items_in_run"] == 2
    assert [row["item_id"] for row in read_results(out / "results" / "model-a.jsonl")] == [
        str(item["item_id"]) for item in items[:2]
    ]
    with pytest.raises(ValueError, match="at least 1"):
        run_eval(items_path, out, models, limit=0, client=client_for(tmp_path))


def test_a_changed_image_stops_the_run_before_any_provider_call(
    tmp_path: Path, eval_set: tuple[Path, Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    (pool / str(items[0]["item_id"]) / "image.png").write_bytes(b"a different picture")
    provider = FakeProvider(replies_for(items))
    install(monkeypatch, provider)

    with pytest.raises(ValueError, match="changed after the eval set was frozen"):
        run_eval(items_path, tmp_path / "eval", models, client=client_for(tmp_path))
    assert provider.calls == []


# --- API keys -------------------------------------------------------------------------------


def test_load_api_keys_sets_only_missing_variables_and_never_prints_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# keys for this machine\nGEMINI_API_KEY="gem-secret-123"\n'
        "export OPENROUTER_API_KEY=or-secret-456\nUNRELATED_TOKEN=nope\n",
        encoding="utf-8",
    )
    environ = {"OPENROUTER_API_KEY": "already-set"}

    loaded = load_api_keys(env_file, environ)

    assert loaded == ["GEMINI_API_KEY"]
    assert environ == {"OPENROUTER_API_KEY": "already-set", "GEMINI_API_KEY": "gem-secret-123"}
    captured = capsys.readouterr()
    assert "gem-secret-123" not in captured.out + captured.err
    assert "already-set" not in captured.out + captured.err


def test_load_api_keys_replaces_an_empty_variable_and_ignores_a_missing_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=or-secret-456\n", encoding="utf-8")
    environ = {"OPENROUTER_API_KEY": "  "}

    assert load_api_keys(env_file, environ) == ["OPENROUTER_API_KEY"]
    assert environ["OPENROUTER_API_KEY"] == "or-secret-456"
    assert load_api_keys(tmp_path / "missing.env", {}) == []


# --- the `tf eval` command -------------------------------------------------------------------


def test_cli_eval_runs_the_models_and_prints_their_metrics(
    tmp_path: Path,
    eval_set: tuple[Path, Path, list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, items_path, items = eval_set
    models = write_models(tmp_path / "models.toml")
    install(monkeypatch, FakeProvider(replies_for(items)))
    monkeypatch.setattr(cli, "_env_file", lambda: tmp_path / "absent.env")

    code = cli.main(
        [
            "eval",
            "--items",
            str(items_path),
            "--out",
            str(tmp_path / "eval"),
            "--models",
            str(models),
            "--limit",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    metrics = json.loads(captured.out)
    assert metrics["models"]["model-a"]["n_items_in_run"] == 2
    assert metrics["models"]["model-b"]["n_items_attempted"] == 2
    assert "eval model-a: attempted 2" in captured.err
    assert (tmp_path / "eval" / "benchmark_metrics.json").is_file()


def test_cli_eval_reports_a_pool_that_is_too_small_for_the_default_n(
    tmp_path: Path,
    eval_set: tuple[Path, Path, list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pool, _, _ = eval_set
    models = write_models(tmp_path / "models.toml")
    monkeypatch.setattr(cli, "_env_file", lambda: tmp_path / "absent.env")

    code = cli.main(
        [
            "eval",
            "--build-from",
            str(pool),
            "--items",
            str(tmp_path / "fresh" / "items.jsonl"),
            "--out",
            str(tmp_path / "fresh"),
            "--models",
            str(models),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "tf eval: error: cannot draw n=200 items" in captured.err
    assert captured.out == ""
    assert not (tmp_path / "fresh" / "items.jsonl").exists()


# --- an empty reply gets one retry with the larger budget -----------------------------------------


def test_an_empty_reply_is_asked_again_with_the_larger_budget(tmp_path: Path) -> None:
    client = FakeModelClient(empty_reply_error(), Reply("OK", 200, False, "model-a", "openrouter"))

    rows, entry = run_one_item(tmp_path, client)

    assert client.budgets == [1024, 4096]
    (row,) = rows
    assert (row["reply"], row["correct"], row["error_type"], row["cached"]) == ("OK", True, None, False)
    assert (row["max_tokens_used"], row["retried_with_larger_budget"]) == (4096, True)
    assert (entry["n_correct"], entry["n_items_attempted"], entry["provider_error_count"]) == (1, 1, 0)


def test_a_second_empty_reply_leaves_a_provider_error_line(tmp_path: Path) -> None:
    client = FakeModelClient(empty_reply_error(), empty_reply_error())

    rows, entry = run_one_item(tmp_path, client)

    assert client.budgets == [1024, 4096]
    (row,) = rows
    assert row["error_type"] == "provider_error"
    assert (row["correct"], row["reply"], row["error_label"]) == (False, None, None)
    assert "was empty" in row["error_message"]
    assert (row["max_tokens_used"], row["retried_with_larger_budget"]) == (4096, True)
    assert (entry["provider_error_count"], entry["n_items_attempted"], entry["accuracy"]) == (1, 1, 0.0)


def test_an_answer_at_the_first_budget_is_not_retried(tmp_path: Path) -> None:
    client = FakeModelClient(Reply("OK", 200, False, "model-a", "openrouter"))

    rows, _ = run_one_item(tmp_path, client)

    assert client.budgets == [1024]
    (row,) = rows
    assert row["correct"] is True
    assert (row["max_tokens_used"], row["retried_with_larger_budget"]) == (1024, False)


def test_other_provider_errors_are_recorded_at_the_first_budget_without_a_retry(tmp_path: Path) -> None:
    unavailable = ModelError("gemini still returned HTTP 503 after 5 attempts", provider="gemini", status=503)
    client = FakeModelClient(unavailable)

    rows, entry = run_one_item(tmp_path, client)

    assert client.budgets == [1024]
    (row,) = rows
    assert row["error_type"] == "provider_error"
    assert "HTTP 503" in row["error_message"]
    assert (row["max_tokens_used"], row["retried_with_larger_budget"]) == (1024, False)
    assert entry["provider_error_count"] == 1


def test_a_rate_limit_on_the_retry_stops_the_model_without_a_line_for_the_item(tmp_path: Path) -> None:
    limited = RateLimited("openrouter still returned HTTP 429 after 5 attempts", provider="openrouter", status=429)
    client = FakeModelClient(empty_reply_error(), limited, cache_dir=tmp_path / "cache")

    rows, entry = run_one_item(tmp_path, client)

    assert rows == []
    assert entry["stopped_reason"] == "rate_limited"
    assert (entry["n_items_attempted"], entry["n_items_not_attempted"]) == (0, 1)
