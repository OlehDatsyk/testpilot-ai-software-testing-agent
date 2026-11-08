"""Provider-independent AI layer.

The rest of the application talks only to ``AIProvider``. Responses are always
requested as structured output and validated with Pydantic before use. AI is
optional: ``NullProvider`` is used when no provider is configured and every
caller has a non-AI code path.

The language model is NEVER used to decide whether a test passed — that comes
exclusively from the execution engine.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class AIUnavailable(RuntimeError):
    """Raised when no provider is configured, or the provider failed / refused."""


class AIProvider:
    name = "none"

    @property
    def available(self) -> bool:
        return False

    @property
    def label(self) -> str:
        return self.name

    def structured(self, *, system: str, prompt: str, schema: type[T], max_tokens: int = 8000) -> T:
        raise AIUnavailable("No AI provider is configured")


class NullProvider(AIProvider):
    pass


class _RateLimiter:
    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def check(self) -> None:
        now = time.monotonic()
        with self.lock:
            while self.calls and now - self.calls[0] > 3600:
                self.calls.popleft()
            if len(self.calls) >= self.per_hour:
                raise AIUnavailable("AI usage limit reached for this hour (AI_MAX_REQUESTS_PER_HOUR)")
            self.calls.append(now)


class AnthropicProvider(AIProvider):
    """Claude via the official Anthropic Python SDK, using structured outputs."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: int, per_hour: int):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model
        self.limiter = _RateLimiter(per_hour)

    @property
    def available(self) -> bool:
        return True

    @property
    def label(self) -> str:
        return f"ai:{self.model}"

    def structured(self, *, system: str, prompt: str, schema: type[T], max_tokens: int = 8000) -> T:
        self.limiter.check()
        a = self._anthropic
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": "medium"},
                # Server-side fallback when a request is declined by safety classifiers.
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"fallbacks": "default"},
            )
        except a.AuthenticationError as exc:
            raise AIUnavailable("AI provider rejected the API key") from exc
        except a.RateLimitError as exc:
            raise AIUnavailable("AI provider rate limit reached; try again later") from exc
        except a.BadRequestError as exc:
            raise AIUnavailable(f"AI provider rejected the request: {getattr(exc, 'message', '')[:200]}") from exc
        except a.APIStatusError as exc:
            raise AIUnavailable(f"AI provider error (HTTP {exc.status_code})") from exc
        except a.APIConnectionError as exc:
            raise AIUnavailable("Could not reach the AI provider") from exc

        if response.stop_reason == "refusal":
            raise AIUnavailable("The AI provider declined this request")
        if response.stop_reason == "max_tokens":
            raise AIUnavailable("AI response was truncated (max_tokens)")
        parsed = response.parsed_output
        if parsed is None:
            raise AIUnavailable("AI response did not match the expected schema")
        try:
            return schema.model_validate(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
        except ValidationError as exc:
            raise AIUnavailable("AI response failed validation") from exc


_provider: AIProvider | None = None


def get_provider() -> AIProvider:
    global _provider
    if _provider is None:
        if settings.ai_provider == "anthropic" and settings.ai_api_key:
            try:
                _provider = AnthropicProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds,
                                              settings.ai_max_requests_per_hour)
            except Exception:  # pragma: no cover - SDK import failure
                log.exception("Failed to initialise AI provider; AI features disabled")
                _provider = NullProvider()
        else:
            _provider = NullProvider()
    return _provider


def set_provider(provider: AIProvider | None) -> None:
    """Test hook."""
    global _provider
    _provider = provider
