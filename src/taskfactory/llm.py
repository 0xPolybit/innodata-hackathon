"""Model client for the eval step: Gemini, OpenRouter and Ollama behind one call().

Standard library only. API keys come from environment variables and never reach a file,
a log line or an exception message. Every answer is appended to
out_dir/eval/<model>/responses.jsonl, so a repeated question is answered from disk and an
interrupted run resumes without paying for answers it already has.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

__all__ = [
    "DEFAULT_MIN_INTERVAL_S",
    "PROVIDERS",
    "ModelClient",
    "ModelError",
    "RateLimited",
    "Reply",
    "cache_key",
    "call_gemini",
    "call_ollama",
    "call_openrouter",
    "image_sha256",
    "safe_model_id",
]

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 120
MAX_ATTEMPTS = 5  # the first try plus four retries when the provider answers with a retryable status
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})  # 429 is rate limiting; the rest are transient server errors
BACKOFF_BASE_S = 2.0  # waits 2, 4, 8, 16 s between attempts unless Retry-After says otherwise
MAX_RETRY_WAIT_S = 120.0  # upper bound on any single wait, Retry-After included

DEFAULT_MIN_INTERVAL_S: dict[str, float] = {"gemini": 1.0, "openrouter": 3.5, "ollama": 0.0}

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_URL = "http://localhost:11434/api/generate"

_LAST_REQUEST: dict[str, float] = {}  # provider -> time.monotonic() of its latest request
_SAFE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


class ModelError(Exception):
    """A model call failed. Messages never include a request header or an API key."""

    def __init__(self, message: str, *, provider: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status


class RateLimited(ModelError):
    """The provider answered HTTP 429 on every attempt."""


@dataclass(frozen=True)
class Reply:
    text: str
    raw_status: int | None  # HTTP status of the answer; None when it was served from the cache
    cached: bool
    model_id: str
    provider: str


@dataclass(frozen=True)
class _HttpResponse:
    status: int
    headers: Any  # anything with .items(): urllib's HTTPMessage or a plain dict
    body: bytes


# --- transport ---------------------------------------------------------------------------


def _send(request_obj: urllib.request.Request) -> _HttpResponse:
    """The only function that touches the network.

    HTTP error statuses come back as responses so that _post can see a retryable status and retry.
    Network failures are raised and turned into ModelError by _post.
    """
    try:
        with urllib.request.urlopen(request_obj, timeout=REQUEST_TIMEOUT_S) as resp:
            return _HttpResponse(resp.status, resp.headers, resp.read())
    except urllib.error.HTTPError as exc:
        body = b""
        if exc.fp is not None:
            try:
                body = exc.read()
            except (OSError, http.client.HTTPException):
                pass
            finally:
                exc.close()
        return _HttpResponse(exc.code, exc.headers, body)


def _post(
    provider: str,
    url: str,
    headers: Mapping[str, str],
    payload: dict[str, Any],
    min_interval: float,
    secrets: tuple[str, ...],
) -> _HttpResponse:
    """POST a JSON body. Every attempt is throttled; a RETRYABLE_STATUSES answer is retried with backoff.

    When every attempt fails, a 429 raises RateLimited and any other retryable status raises ModelError.
    """
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle(provider, min_interval)
        try:
            request_obj = urllib.request.Request(url, data=data, headers=dict(headers), method="POST")
            response = _send(request_obj)
        except ValueError:
            # http.client quotes the offending header value in this message, so it is not repeated.
            raise ModelError(f"{provider} request could not be built or sent", provider=provider) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            detail = _redact(f"{type(exc).__name__}: {getattr(exc, 'reason', None) or exc}", secrets)
            raise ModelError(f"{provider} network request failed ({detail})", provider=provider) from None
        if response.status not in RETRYABLE_STATUSES:
            return response
        if attempt < MAX_ATTEMPTS:
            time.sleep(_retry_wait(attempt, response.headers))
    if response.status == 429:
        raise RateLimited(
            f"{provider} still returned HTTP 429 after {MAX_ATTEMPTS} attempts",
            provider=provider,
            status=429,
        )
    raise ModelError(
        f"{provider} still returned HTTP {response.status} after {MAX_ATTEMPTS} attempts",
        provider=provider,
        status=response.status,
    )


def _throttle(provider: str, min_interval: float) -> None:
    """Sleep until min_interval seconds have passed since this provider's last request."""
    if min_interval <= 0:
        return
    last = _LAST_REQUEST.get(provider)
    if last is not None:
        remaining = min_interval - (time.monotonic() - last)
        if remaining > 0:
            time.sleep(remaining)
    _LAST_REQUEST[provider] = time.monotonic()


def _retry_wait(attempt: int, headers: Any) -> float:
    """Seconds to wait after attempt number `attempt` was answered with a retryable status."""
    raw = _header(headers, "Retry-After")
    seconds = _parse_retry_after(raw) if raw is not None else None
    if seconds is None:
        seconds = BACKOFF_BASE_S * 2 ** (attempt - 1)
    return min(seconds, MAX_RETRY_WAIT_S)


def _parse_retry_after(raw: str) -> float | None:
    """Retry-After as delta-seconds or as an HTTP date. None when the value is unusable."""
    value = raw.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(seconds, 0.0)


def _header(headers: Any, name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


# --- request and response helpers --------------------------------------------------------


def _api_key(provider: str, var: str, env: Mapping[str, str] | None) -> str:
    """Read a key from the environment. Errors name the variable and never print its value."""
    source: Mapping[str, str] = os.environ if env is None else env
    key = (source.get(var) or "").strip()
    if not key:
        raise ModelError(f"{provider} needs the {var} environment variable, which is not set", provider=provider)
    if not (key.isascii() and key.isprintable()):
        raise ModelError(f"{var} holds characters that cannot be sent in an HTTP header", provider=provider)
    return key


def _interval(provider: str, min_interval: float | None) -> float:
    return DEFAULT_MIN_INTERVAL_S[provider] if min_interval is None else float(min_interval)


def _image_b64(image_path: str | Path) -> str:
    return base64.b64encode(Path(image_path).read_bytes()).decode("ascii")


def _redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _snippet(body: bytes, secrets: Iterable[str], limit: int = 300) -> str:
    """Start of an error body for a message. Keys are redacted before whitespace is collapsed."""
    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    return " ".join(text.split())[:limit]


def _json_ok(response: _HttpResponse, provider: str, secrets: tuple[str, ...]) -> Any:
    if not 200 <= response.status < 300:
        detail = _snippet(response.body, secrets)
        suffix = f": {detail}" if detail else ""
        raise ModelError(
            f"{provider} returned HTTP {response.status}{suffix}",
            provider=provider,
            status=response.status,
        )
    try:
        return json.loads(response.body)
    except ValueError:
        raise ModelError(
            f"{provider} returned a body that is not JSON",
            provider=provider,
            status=response.status,
        ) from None


def _dig(data: Any, *path: str | int) -> Any:
    """data[p0][p1]... or None when any step is missing."""
    try:
        for step in path:
            data = data[step]
    except (KeyError, IndexError, TypeError):
        return None
    return data


# --- providers: one function each, same call shape --------------------------------------


def call_gemini(
    model_id: str,
    prompt: str,
    image_path: str | Path | None = None,
    max_tokens: int = 1024,
    *,
    env: Mapping[str, str] | None = None,
    min_interval: float | None = None,
) -> Reply:
    """Gemini REST generateContent. The key goes in the x-goog-api-key header, not the URL."""
    provider = "gemini"
    key = _api_key(provider, "GEMINI_API_KEY", env)
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_path is not None:
        parts.append({"inline_data": {"mimeType": "image/png", "data": _image_b64(image_path)}})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
    }
    model = quote(model_id.removeprefix("models/"), safe="")
    response = _post(
        provider,
        GEMINI_URL.format(model=model),
        {"Content-Type": "application/json", "x-goog-api-key": key},
        payload,
        _interval(provider, min_interval),
        (key,),
    )
    data = _json_ok(response, provider, (key,))
    text = _dig(data, "candidates", 0, "content", "parts", 0, "text")
    if not isinstance(text, str) or not text.strip():
        raise ModelError(
            "gemini reply was empty or had no text (the answer may have been blocked)",
            provider=provider,
            status=response.status,
        )
    return Reply(text, response.status, False, model_id, provider)


def call_openrouter(
    model_id: str,
    prompt: str,
    image_path: str | Path | None = None,
    max_tokens: int = 1024,
    *,
    env: Mapping[str, str] | None = None,
    min_interval: float | None = None,
) -> Reply:
    """OpenRouter chat completions (OpenAI-compatible). The key goes in the Authorization header."""
    provider = "openrouter"
    key = _api_key(provider, "OPENROUTER_API_KEY", env)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_path is not None:
        content.append(
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _image_b64(image_path)}}
        )
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    response = _post(
        provider,
        OPENROUTER_URL,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        payload,
        _interval(provider, min_interval),
        (key,),
    )
    data = _json_ok(response, provider, (key,))
    message = _dig(data, "choices", 0, "message", "content")
    if message is None or (isinstance(message, str) and not message.strip()):
        raise ModelError(
            "openrouter reply was empty (reasoning models can use up the max_tokens budget before answering)",
            provider=provider,
            status=response.status,
        )
    if not isinstance(message, str):
        raise ModelError("openrouter reply content was not text", provider=provider, status=response.status)
    return Reply(message, response.status, False, model_id, provider)


def call_ollama(
    model_id: str,
    prompt: str,
    image_path: str | Path | None = None,
    max_tokens: int = 1024,
    *,
    env: Mapping[str, str] | None = None,
    min_interval: float | None = None,
) -> Reply:
    """Local Ollama REST generate. No key; env is accepted only for a uniform signature."""
    provider = "ollama"
    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    if image_path is not None:
        payload["images"] = [_image_b64(image_path)]
    response = _post(
        provider,
        OLLAMA_URL,
        {"Content-Type": "application/json"},
        payload,
        _interval(provider, min_interval),
        (),
    )
    data = _json_ok(response, provider, ())
    text = data.get("response") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ModelError("ollama reply was empty", provider=provider, status=response.status)
    return Reply(text, response.status, False, model_id, provider)


PROVIDERS: dict[str, Callable[..., Reply]] = {
    "gemini": call_gemini,
    "openrouter": call_openrouter,
    "ollama": call_ollama,
}


# --- cache -----------------------------------------------------------------------------


def cache_key(model_id: str, prompt: str, image_sha: str, max_tokens: int) -> str:
    """sha256 over model_id, prompt, image sha256 ("" when there is no image) and max_tokens."""
    material = f"{model_id}\n{prompt}\n{image_sha}\n{max_tokens}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def safe_model_id(model_id: str) -> str:
    """Folder name for a model: anything outside letters, digits, dot, dash and underscore becomes _."""
    if not model_id:
        raise ValueError("model_id must not be empty")
    safe = "".join(ch if ch in _SAFE_CHARS else "_" for ch in model_id)
    if not safe.strip("."):  # "." and ".." would point outside eval/
        safe = "_" * len(safe)
    return safe


def image_sha256(path: str | Path) -> str:
    """sha256 hex digest of the file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_cache_file(path: Path) -> dict[str, dict[str, Any]]:
    """Map key -> record. A line that is not a JSON object with string key and text is skipped."""
    entries: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return entries
    with path.open("rb") as fh:
        for number, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)  # bytes input: UTF-8 errors surface as ValueError too
                if not (
                    isinstance(record, dict)
                    and isinstance(record.get("key"), str)
                    and isinstance(record.get("text"), str)
                ):
                    raise ValueError("record lacks a string key or text")
            except ValueError:
                log.warning("Skipping corrupt cache line %d in %s", number, path)
                continue
            entries.setdefault(record["key"], record)
    return entries


def _append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line. A torn last line from an earlier crash is closed first, so the new record stays intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lead = ""
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                lead = "\n"
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(lead + line + "\n")


class ModelClient:
    """Cached, throttled access to the three providers.

    Answers are stored under out_dir/eval/<model>/responses.jsonl. Keys are read from env
    (default os.environ) and only when a network call is actually needed, so a cached
    answer works without a key. min_intervals overrides DEFAULT_MIN_INTERVAL_S per provider.
    """

    def __init__(
        self,
        out_dir: str | Path,
        env: Mapping[str, str] | None = None,
        min_intervals: Mapping[str, float] | None = None,
    ) -> None:
        self.out_dir = Path(out_dir)
        self._env: Mapping[str, str] = os.environ if env is None else env
        self._min_intervals = dict(DEFAULT_MIN_INTERVAL_S)
        for provider, seconds in (min_intervals or {}).items():
            if provider not in PROVIDERS:
                raise ValueError(f"unknown provider {provider!r}")
            self._min_intervals[provider] = float(seconds)
        self._loaded: dict[Path, dict[str, dict[str, Any]]] = {}

    def cache_path(self, model_id: str) -> Path:
        return self.out_dir / "eval" / safe_model_id(model_id) / "responses.jsonl"

    def call(
        self,
        model_id: str,
        provider: str,
        prompt: str,
        image_path: str | Path | None = None,
        max_tokens: int = 1024,
    ) -> Reply:
        """Answer from the cache when possible; otherwise call the provider and cache the answer."""
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}; expected one of {sorted(PROVIDERS)}")
        image_hash = image_sha256(image_path) if image_path is not None else ""
        key = cache_key(model_id, prompt, image_hash, max_tokens)
        path = self.cache_path(model_id)
        entries = self._entries(path)
        hit = entries.get(key)
        if hit is not None:
            return Reply(hit["text"], None, True, model_id, provider)
        reply = PROVIDERS[provider](
            model_id,
            prompt,
            image_path=image_path,
            max_tokens=max_tokens,
            env=self._env,
            min_interval=self._min_intervals[provider],
        )
        record = {
            "key": key,
            "model_id": model_id,
            "provider": provider,
            "text": reply.text,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _append_record(path, record)
        entries[key] = record
        return reply

    def _entries(self, path: Path) -> dict[str, dict[str, Any]]:
        """Read the file on first use; later calls reuse the in-memory copy."""
        if path not in self._loaded:
            self._loaded[path] = _read_cache_file(path)
        return self._loaded[path]
