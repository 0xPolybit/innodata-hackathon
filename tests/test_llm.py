"""Tests for taskfactory.llm. Offline only: _send is replaced and time.sleep is faked."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from taskfactory import llm
from taskfactory.llm import ModelClient, ModelError, RateLimited, Reply

FAKE_KEY = "TESTKEY-123"
PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"
PNG_B64 = base64.b64encode(PNG).decode("ascii")
NO_THROTTLE = {"gemini": 0.0, "openrouter": 0.0}
REAL_SEND = llm._send  # saved before the autouse fixture replaces it
PROVIDER_KEYS = [
    ("gemini", "gemini-2.5-flash", "GEMINI_API_KEY"),
    ("openrouter", "openai/gpt-4o-mini", "OPENROUTER_API_KEY"),
]
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "a cat"}]}}]}
OPENROUTER_OK = {"choices": [{"message": {"content": "a cat"}}]}


class FakeSend:
    """Stands in for llm._send. Each call records the request and returns or raises the next result."""

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request_obj: urllib.request.Request) -> Any:
        self.requests.append(request_obj)
        if not self.results:
            raise AssertionError("unexpected network call")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeHTTPResponse:
    """What urllib.request.urlopen returns for a successful call."""

    def __init__(self, body: bytes) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self._body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def ok(payload: dict[str, Any]) -> llm._HttpResponse:
    return llm._HttpResponse(200, {}, json.dumps(payload).encode("utf-8"))


def http_reply(status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> llm._HttpResponse:
    return llm._HttpResponse(status, headers or {}, body)


def headers_of(request_obj: urllib.request.Request) -> dict[str, str]:
    """urllib capitalises header names (x-goog-api-key becomes X-goog-api-key), so compare lowercase."""
    return {name.lower(): value for name, value in request_obj.header_items()}


def body_of(request_obj: urllib.request.Request) -> dict[str, Any]:
    return json.loads(request_obj.data)


def client_for(tmp_path: Path, env: dict[str, str] | None = None) -> ModelClient:
    return ModelClient(tmp_path, env={} if env is None else env, min_intervals=NO_THROTTLE)


def write_png(tmp_path: Path, name: str = "page.png", data: bytes = PNG) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def cache_file(tmp_path: Path, model_id: str = "gpt-4o-mini") -> Path:
    return tmp_path / "eval" / model_id / "responses.jsonl"


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Records every time.sleep call instead of sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", recorded.append)
    return recorded


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    """Every test: the network is refused, sleeps are faked and the throttle table starts empty."""

    def refuse(request_obj: urllib.request.Request) -> None:
        raise AssertionError(f"a test tried the network: {request_obj.full_url}")

    monkeypatch.setattr(llm, "_send", refuse)
    monkeypatch.setattr(llm, "_LAST_REQUEST", {})


# --- request shape per provider ----------------------------------------------------------


def test_gemini_body_contains_the_inline_image_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = write_png(tmp_path)
    fake = FakeSend(ok(GEMINI_OK))
    monkeypatch.setattr(llm, "_send", fake)

    reply = client_for(tmp_path, {"GEMINI_API_KEY": FAKE_KEY}).call(
        "gemini-2.5-flash", "gemini", "describe", image_path=image, max_tokens=64
    )

    req = fake.requests[0]
    assert req.full_url == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert FAKE_KEY not in req.full_url
    assert headers_of(req)["x-goog-api-key"] == FAKE_KEY
    body = body_of(req)
    assert body["contents"][0]["parts"] == [
        {"text": "describe"},
        {"inline_data": {"mimeType": "image/png", "data": PNG_B64}},
    ]
    assert body["generationConfig"] == {"temperature": 0, "maxOutputTokens": 64}
    assert reply == Reply("a cat", 200, False, "gemini-2.5-flash", "gemini")


def test_gemini_body_is_text_only_without_an_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSend(ok(GEMINI_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client_for(tmp_path, {"GEMINI_API_KEY": FAKE_KEY}).call("gemini-2.5-flash", "gemini", "hi")

    assert body_of(fake.requests[0])["contents"][0]["parts"] == [{"text": "hi"}]


def test_openrouter_request_has_the_data_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = write_png(tmp_path)
    fake = FakeSend(ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    reply = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call(
        "openai/gpt-4o-mini", "openrouter", "read it", image_path=image, max_tokens=256
    )

    req = fake.requests[0]
    assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers_of(req)["authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in req.full_url
    body = body_of(req)
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["temperature"] == 0 and body["max_tokens"] == 256
    assert body["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "read it"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}},
            ],
        }
    ]
    assert reply.text == "a cat" and reply.provider == "openrouter"


# --- cache -------------------------------------------------------------------------------


def test_cache_miss_then_hit_makes_exactly_one_network_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSend(ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY})
    first = client.call("gpt-4o-mini", "openrouter", "q", max_tokens=16)
    second = client.call("gpt-4o-mini", "openrouter", "q", max_tokens=16)
    third = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call(
        "gpt-4o-mini", "openrouter", "q", max_tokens=16
    )  # a new client reads the file

    assert len(fake.requests) == 1
    assert (first.cached, second.cached, third.cached) == (False, True, True)
    assert (first.raw_status, second.raw_status) == (200, None)
    assert first.text == second.text == third.text == "a cat"


def test_cache_line_has_the_spec_fields_and_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = write_png(tmp_path)
    monkeypatch.setattr(llm, "_send", FakeSend(ok(OPENROUTER_OK)))
    client = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY})

    client.call("gpt-4o-mini", "openrouter", "describe", image_path=image, max_tokens=32)

    lines = client.cache_path("gpt-4o-mini").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    image_sha = hashlib.sha256(PNG).hexdigest()
    assert record["key"] == hashlib.sha256(f"gpt-4o-mini\ndescribe\n{image_sha}\n32".encode("utf-8")).hexdigest()
    assert set(record) == {"key", "model_id", "provider", "text", "created_at"}
    assert (record["model_id"], record["provider"], record["text"]) == ("gpt-4o-mini", "openrouter", "a cat")
    assert datetime.fromisoformat(record["created_at"]).utcoffset().total_seconds() == 0


def test_cache_key_depends_on_prompt_and_max_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSend(ok(OPENROUTER_OK), ok(OPENROUTER_OK), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY})
    client.call("gpt-4o-mini", "openrouter", "q", max_tokens=16)
    client.call("gpt-4o-mini", "openrouter", "q", max_tokens=32)  # different max_tokens: a new key
    client.call("gpt-4o-mini", "openrouter", "r", max_tokens=32)  # different prompt: a new key

    assert len(fake.requests) == 3


def test_changing_the_image_bytes_changes_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = write_png(tmp_path, data=b"first")
    fake = FakeSend(ok(OPENROUTER_OK), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY})
    client.call("gpt-4o-mini", "openrouter", "read", image_path=image)
    image.write_bytes(b"second")
    reply = client.call("gpt-4o-mini", "openrouter", "read", image_path=image)

    assert reply.cached is False
    assert len(fake.requests) == 2


def test_cache_hit_needs_no_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSend(ok(GEMINI_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client_for(tmp_path, {"GEMINI_API_KEY": FAKE_KEY}).call("gemini-2.5-flash", "gemini", "hi")
    reply = client_for(tmp_path, {}).call("gemini-2.5-flash", "gemini", "hi")

    assert (reply.cached, reply.text) == (True, "a cat")
    assert len(fake.requests) == 1


def test_corrupt_last_line_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    good = {
        "key": llm.cache_key("gpt-4o-mini", "kept prompt", "", 16),
        "model_id": "gpt-4o-mini",
        "provider": "openrouter",
        "text": "from cache",
        "created_at": "2026-11-19T00:00:00+00:00",
    }
    path = cache_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(good) + '\n{"key": "abc", "text": "half a wri', encoding="utf-8")
    fake = FakeSend()
    monkeypatch.setattr(llm, "_send", fake)

    with caplog.at_level(logging.WARNING, logger="taskfactory.llm"):
        reply = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call(
            "gpt-4o-mini", "openrouter", "kept prompt", max_tokens=16
        )

    assert (reply.cached, reply.text) == (True, "from cache")
    assert fake.requests == []
    assert any("corrupt" in record.getMessage() for record in caplog.records)


def test_new_record_after_a_torn_tail_stays_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = cache_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"key": "abc", "text": "half', encoding="utf-8")  # no newline: a crash mid-write
    fake = FakeSend(ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "new prompt")
    reply = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "new prompt")

    assert len(fake.requests) == 1
    assert (reply.cached, reply.text) == (True, "a cat")


# --- retries and throttling --------------------------------------------------------------


def test_two_429_responses_then_success_returns_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeSend(http_reply(429), http_reply(429), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    reply = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert (reply.text, reply.cached) == ("a cat", False)
    assert len(fake.requests) == 3
    assert sleeps == [2.0, 4.0]


def test_retry_after_header_replaces_the_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeSend(http_reply(429, headers={"Retry-After": "7"}), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert sleeps == [7.0]


def test_429_on_every_attempt_raises_rate_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """The first try and the four retries all get 429, so RateLimited follows the fifth attempt."""
    fake = FakeSend(*[http_reply(429) for _ in range(llm.MAX_ATTEMPTS)])
    monkeypatch.setattr(llm, "_send", fake)

    with pytest.raises(RateLimited) as caught:
        client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert len(fake.requests) == 5
    assert sleeps == [2.0, 4.0, 8.0, 16.0]
    assert (caught.value.provider, caught.value.status) == ("openrouter", 429)


TRANSIENT_STATUSES = (500, 502, 503, 504)


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
def test_two_transient_server_errors_then_success_returns_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float], status: int
) -> None:
    fake = FakeSend(http_reply(status), http_reply(status), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    reply = client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert (reply.text, reply.cached) == ("a cat", False)
    assert len(fake.requests) == 3
    assert sleeps == [2.0, 4.0]


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
def test_transient_server_error_on_every_attempt_raises_model_error_with_the_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float], status: int
) -> None:
    """Five answers (the first try and four retries), then a ModelError that names the status. Never RateLimited."""
    fake = FakeSend(*[http_reply(status) for _ in range(llm.MAX_ATTEMPTS)])
    monkeypatch.setattr(llm, "_send", fake)

    with pytest.raises(ModelError) as caught:
        client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert not isinstance(caught.value, RateLimited)
    assert f"HTTP {status}" in str(caught.value)
    assert (caught.value.provider, caught.value.status) == ("openrouter", status)
    assert len(fake.requests) == 5
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_retry_after_header_applies_to_a_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeSend(http_reply(503, headers={"Retry-After": "7"}), ok(OPENROUTER_OK))
    monkeypatch.setattr(llm, "_send", fake)

    client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert sleeps == [7.0]


@pytest.mark.parametrize("status", [400, 401, 501])
def test_other_error_statuses_are_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float], status: int
) -> None:
    fake = FakeSend(http_reply(status, body=b'{"error": "no"}'))
    monkeypatch.setattr(llm, "_send", fake)

    with pytest.raises(ModelError) as caught:
        client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "p")

    assert not isinstance(caught.value, RateLimited)
    assert (caught.value.status, len(fake.requests), sleeps) == (status, 1, [])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3.0), ("2.5", 2.5), ("-4", 0.0), ("nan", None), ("soon", None)],
)
def test_parse_retry_after(raw: str, expected: float | None) -> None:
    assert llm._parse_retry_after(raw) == expected


def test_default_min_intervals_match_the_plan() -> None:
    assert llm.DEFAULT_MIN_INTERVAL_S == {"gemini": 1.0, "openrouter": 3.5}


def test_gemini_calls_are_spaced_by_the_default_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    fake = FakeSend(ok(GEMINI_OK), ok(GEMINI_OK))
    monkeypatch.setattr(llm, "_send", fake)
    client = ModelClient(tmp_path, env={"GEMINI_API_KEY": FAKE_KEY})  # default intervals

    client.call("gemini-2.5-flash", "gemini", "one")
    assert sleeps == []
    client.call("gemini-2.5-flash", "gemini", "two")

    assert len(sleeps) == 1 and 0.5 < sleeps[0] <= 1.0


# --- errors ------------------------------------------------------------------------------


@pytest.mark.parametrize(("provider", "model", "var"), PROVIDER_KEYS)
@pytest.mark.parametrize("blank", [False, True], ids=["unset", "blank"])
def test_missing_key_raises_model_error_naming_only_the_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
    model: str,
    var: str,
    blank: bool,
) -> None:
    fake = FakeSend()
    monkeypatch.setattr(llm, "_send", fake)
    other = "GEMINI_API_KEY" if var == "OPENROUTER_API_KEY" else "OPENROUTER_API_KEY"
    env = {other: FAKE_KEY}  # the other provider's key must not leak into the message either
    if blank:
        env[var] = "   "

    with pytest.raises(ModelError) as caught:
        client_for(tmp_path, env).call(model, provider, "hi")

    message = str(caught.value)
    assert var in message
    assert FAKE_KEY not in message
    assert caught.value.provider == provider
    assert fake.requests == []
    out = capsys.readouterr()
    assert FAKE_KEY not in out.out + out.err


def every_attempt(response: llm._HttpResponse) -> list[llm._HttpResponse]:
    """The same answer on each of the five attempts, for a status that is retried."""
    return [response] * llm.MAX_ATTEMPTS


LEAK_SCENARIOS = {
    "http-500-echoes-key": lambda: every_attempt(http_reply(500, body=f'{{"error": "bad key {FAKE_KEY}"}}'.encode())),
    "http-503-echoes-key": lambda: every_attempt(http_reply(503, body=FAKE_KEY.encode())),
    "http-401": lambda: [http_reply(401, body=b'{"error": "invalid api key"}')],
    "429-on-every-attempt": lambda: [http_reply(429, body=FAKE_KEY.encode())] * llm.MAX_ATTEMPTS,
    "url-error-repeats-key": lambda: [urllib.error.URLError(f"reset while sending {FAKE_KEY}")],
    "value-error-from-http-client": lambda: [ValueError(f"Invalid header value {FAKE_KEY!r}")],
    "body-not-json-echoes-key": lambda: [llm._HttpResponse(200, {}, f"oops {FAKE_KEY}".encode())],
}


@pytest.mark.parametrize(("provider", "model", "var"), PROVIDER_KEYS)
@pytest.mark.parametrize("scenario", sorted(LEAK_SCENARIOS))
def test_api_key_never_appears_in_exception_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, model: str, var: str, scenario: str
) -> None:
    monkeypatch.setattr(llm, "_send", FakeSend(*LEAK_SCENARIOS[scenario]()))

    with pytest.raises(ModelError) as caught:
        client_for(tmp_path, {var: FAKE_KEY}).call(model, provider, "hi")

    assert FAKE_KEY not in str(caught.value)
    assert FAKE_KEY not in repr(caught.value)


def test_http_error_raises_model_error_with_status_and_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm, "_send", FakeSend(http_reply(400, body=b'{"error": "bad request"}')))

    with pytest.raises(ModelError) as caught:
        client_for(tmp_path, {"GEMINI_API_KEY": FAKE_KEY}).call("gemini-2.5-flash", "gemini", "hi")

    assert not isinstance(caught.value, RateLimited)
    assert (caught.value.status, caught.value.provider) == (400, "gemini")
    assert "bad request" in str(caught.value)


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_openrouter_reply_raises_model_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    monkeypatch.setattr(llm, "_send", FakeSend(ok({"choices": [{"message": {"content": content}}]})))

    with pytest.raises(ModelError, match="reply was empty") as caught:
        client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("m", "openrouter", "hi")

    assert "reasoning models" in str(caught.value)
    assert (caught.value.provider, caught.value.status) == ("openrouter", 200)
    assert not (tmp_path / "eval").exists()  # an empty answer is never cached


def test_empty_gemini_reply_raises_model_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_send", FakeSend(ok({"candidates": [{"content": {"parts": [{"text": ""}]}}]})))

    with pytest.raises(ModelError, match="empty"):
        client_for(tmp_path, {"GEMINI_API_KEY": FAKE_KEY}).call("gemini-2.5-flash", "gemini", "hi")


def test_network_failure_raises_model_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_send", FakeSend(urllib.error.URLError("connection refused")))

    with pytest.raises(ModelError, match="network") as caught:
        client_for(tmp_path, {"OPENROUTER_API_KEY": FAKE_KEY}).call("gpt-4o-mini", "openrouter", "hi")

    assert caught.value.provider == "openrouter"


def test_unknown_provider_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        client_for(tmp_path).call("m", "bedrock", "hi")
    with pytest.raises(ValueError, match="unknown provider"):
        ModelClient(tmp_path, min_intervals={"bedrock": 1.0})


# --- transport and helpers ---------------------------------------------------------------


def test_send_calls_urlopen_with_a_120_second_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request_obj: urllib.request.Request, timeout: float | None = None) -> FakeHTTPResponse:
        seen["timeout"] = timeout
        return FakeHTTPResponse(b"{}")

    monkeypatch.setattr(llm, "_send", REAL_SEND)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = REAL_SEND(urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=b"{}", method="POST"))

    assert seen["timeout"] == 120
    assert (result.status, result.body) == (200, b"{}")


def test_send_turns_an_http_error_into_a_status_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request_obj: urllib.request.Request, timeout: float | None = None) -> None:
        raise urllib.error.HTTPError(
            request_obj.full_url, 429, "Too Many Requests", {"Retry-After": "3"}, io.BytesIO(b"slow down")
        )

    monkeypatch.setattr(llm, "_send", REAL_SEND)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = REAL_SEND(urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=b"{}", method="POST"))

    assert (result.status, result.body) == (429, b"slow down")
    assert llm._header(result.headers, "retry-after") == "3"


def test_cache_path_uses_a_safe_model_folder(tmp_path: Path) -> None:
    client = ModelClient(tmp_path, env={})

    assert client.cache_path("gemini-2.5-flash") == tmp_path / "eval" / "gemini-2.5-flash" / "responses.jsonl"
    assert client.cache_path("org/model:tag v1") == tmp_path / "eval" / "org_model_tag_v1" / "responses.jsonl"
    assert client.cache_path("..") == tmp_path / "eval" / "__" / "responses.jsonl"


def test_image_sha256_matches_hashlib(tmp_path: Path) -> None:
    assert llm.image_sha256(write_png(tmp_path)) == hashlib.sha256(PNG).hexdigest()
