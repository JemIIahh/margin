"""Adapter for OpenAI-compatible chat endpoints, built for the event's LiteLLM proxy.

The agent loop speaks Anthropic's shapes: content blocks, tool_use and tool_result, and usage with cache
tokens. Run state, checkpoints and resume all store that shape, so this module converts at the boundary
only: Anthropic-shaped request in, OpenAI chat request out, and the reply converted back.

Verified against the proxy (2026-10-10): tool calls round-trip on every model; prompt caching works through
`cache_control` content parts on Claude models; Nova rejects a cache breakpoint inside a tool result, so the
moving breakpoint is only placed on Claude models; Nova caps output at 10,000 tokens.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

CACHE = {"type": "ephemeral"}
# Output-token ceilings the proxy reports that are below Settings.max_tokens.
MAX_OUTPUT_TOKENS = {"nova-micro": 10_000, "nova-lite": 10_000, "nova-pro": 10_000}
FINISH_TO_STOP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


@dataclass
class TextBlock:
    text: str
    type: str = "text"

    def to_dict(self) -> dict:
        return {"type": "text", "text": self.text}


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"

    def to_dict(self) -> dict:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]},
        }
        for t in tools
    ]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def _mark_last(messages: list[dict]) -> None:
    """Move the cache breakpoint to the end of the conversation, as Anthropic's automatic caching does."""
    last = messages[-1]
    if last["role"] in ("user", "tool") and isinstance(last.get("content"), str) and last["content"]:
        last["content"] = [{"type": "text", "text": last["content"], "cache_control": CACHE}]


def to_openai_messages(system: Any, messages: list[dict], *, cache_last: bool) -> list[dict]:
    blocks = [{"type": "text", "text": system}] if isinstance(system, str) else list(system or [])
    out: list[dict] = []
    if blocks:
        part: dict = {"type": "text", "text": "\n\n".join(b["text"] for b in blocks)}
        if any("cache_control" in b for b in blocks):
            part["cache_control"] = CACHE
        out.append({"role": "system", "content": [part]})
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            calls = [
                {
                    "id": b["id"], "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in content if b["type"] == "tool_use"
            ]
            entry: dict = {"role": "assistant", "content": _text_of(content) or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
        else:  # user: tool results must directly follow the assistant's tool calls, then any text
            for b in content:
                if b["type"] == "tool_result":
                    body = _text_of(b["content"])
                    out.append(
                        {"role": "tool", "tool_call_id": b["tool_use_id"], "content": f"ERROR: {body}" if b.get("is_error") else body}
                    )
            texts = [b["text"] for b in content if b["type"] == "text"]
            if texts:
                out.append({"role": "user", "content": "\n\n".join(texts)})
    if cache_last and out:
        _mark_last(out)
    return out


def to_openai_request(params: dict, *, max_output: dict[str, int] | None = None) -> dict:
    """Anthropic-shaped request (what margin.model.build_request produces) -> OpenAI chat body."""
    model = params["model"]
    limits = {**MAX_OUTPUT_TOKENS, **(max_output or {})}
    body: dict = {
        "model": model,
        "messages": to_openai_messages(
            params.get("system"), params["messages"], cache_last=model.startswith("claude")
        ),
        "max_tokens": min(params["max_tokens"], limits.get(model, params["max_tokens"])),
    }
    if params.get("tools"):
        body["tools"] = to_openai_tools(params["tools"])
    return body  # cache_control (top level) and output_config have no OpenAI equivalent and are dropped


def _usage(raw: dict | None) -> SimpleNamespace:
    raw = raw or {}
    details = raw.get("prompt_tokens_details") or {}
    cache_read = int(raw.get("cache_read_input_tokens") or details.get("cached_tokens") or 0)
    cache_write = int(raw.get("cache_creation_input_tokens") or details.get("cache_creation_tokens") or 0)
    prompt = int(raw.get("prompt_tokens") or 0)  # OpenAI semantics: includes cached tokens
    return SimpleNamespace(
        input_tokens=max(prompt - cache_read - cache_write, 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def from_openai_response(data: dict, *, proxy_cost: float | None = None) -> SimpleNamespace:
    """OpenAI chat reply -> an object shaped like an Anthropic Message, as the agent loop expects."""
    choice = data["choices"][0]
    message = choice["message"]
    finish = choice.get("finish_reason")
    blocks: list = []
    if message.get("content"):
        blocks.append(TextBlock(message["content"]))
    cut_off = False
    for call in message.get("tool_calls") or []:
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise TypeError("arguments must be an object")
        except (ValueError, TypeError):  # JSONDecodeError is a ValueError
            if finish == "length":  # the reply ran out of tokens mid tool call: ask for it again, do not run half of it
                cut_off = True
                continue
            args = {}
        blocks.append(ToolUseBlock(call["id"], call["function"]["name"], args))
    if cut_off:
        stop = "max_tokens"
    elif any(isinstance(b, ToolUseBlock) for b in blocks):
        stop = "tool_use"
    else:
        stop = FINISH_TO_STOP.get(finish, "end_turn")
    return SimpleNamespace(
        content=blocks, stop_reason=stop, usage=_usage(data.get("usage")), model=data.get("model"),
        proxy_cost_usd=proxy_cost,
    )


class OpenAICompatModel:
    """Same `.create(**params)` surface as AnthropicModel, over an OpenAI-compatible endpoint."""

    def __init__(self, client: Any, *, max_output: dict[str, int] | None = None,
                 cost_header: str = "x-litellm-response-cost"):
        self._client = client
        self.max_output = max_output
        self.cost_header = cost_header
        self.proxy_cost_usd = 0.0  # what the proxy says this client spent: a check on our own metering

    def create(self, **params: Any) -> Any:
        body = to_openai_request(params, max_output=self.max_output)
        raw = self._client.chat.completions.with_raw_response.create(**body)
        cost = raw.headers.get(self.cost_header)
        proxy_cost = float(cost) if cost not in (None, "") else None
        if proxy_cost is not None:
            self.proxy_cost_usd += proxy_cost
        return from_openai_response(raw.http_response.json(), proxy_cost=proxy_cost)


def make_litellm_client() -> OpenAICompatModel:
    import openai  # after neatlogs.init, so auto-instrumentation attaches

    key, base = os.environ.get("LITELLM_API_KEY"), os.environ.get("LITELLM_BASE_URL")
    if not key or not base:
        raise RuntimeError("LITELLM_API_KEY and LITELLM_BASE_URL must be set (see .env.example)")
    return OpenAICompatModel(openai.OpenAI(api_key=key, base_url=base, max_retries=0, timeout=120.0))
