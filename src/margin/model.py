"""Request construction and the thin Anthropic wrapper.

`anthropic` is imported lazily so neatlogs.init (which must run first) can attach its instrumentation.
Requests avoid everything Sonnet 5.5 and Haiku 5.5 reject: sampling parameters, disabled thinking,
forced tool choice and prefill. Thinking is left at its adaptive default.
"""
from __future__ import annotations

from typing import Any

from margin.config import Settings
from margin.errors import TransientModelError


def build_request(
    *, model: str, effort: str, system: str, tools: list[dict], messages: list[dict], max_tokens: int
) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "tools": tools,
        "messages": messages,
        "cache_control": {"type": "ephemeral"},
        "output_config": {"effort": effort},
    }


class AnthropicModel:
    def __init__(self, client: Any):
        self._client = client

    def create(self, **params: Any) -> Any:
        return self._client.messages.create(**params)


def make_model_client(settings: Settings) -> AnthropicModel:
    import anthropic

    return AnthropicModel(anthropic.Anthropic(max_retries=0))  # our loop owns retries so each is visible


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientModelError):
        return True
    import anthropic

    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500
