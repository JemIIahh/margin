"""Token usage, price table and the live spend meter used by the governor and the ledger."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

M = 1_000_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @classmethod
    def from_api(cls, usage: Any) -> Usage:
        def n(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        return cls(
            n("input_tokens"), n("output_tokens"), n("cache_creation_input_tokens"), n("cache_read_input_tokens")
        )

    @classmethod
    def from_dict(cls, d: dict) -> Usage:
        return cls(**{k: int(d.get(k, 0)) for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_write: float
    cache_read: float
    long_prompt_threshold: int | None = None
    long_prompt_multiplier: float = 1.0

    def cost(self, u: Usage) -> float:
        mult = 1.0
        if self.long_prompt_threshold is not None and u.prompt_tokens > self.long_prompt_threshold:
            mult = self.long_prompt_multiplier
        raw = (
            u.input_tokens * self.input
            + u.output_tokens * self.output
            + u.cache_write_tokens * self.cache_write
            + u.cache_read_tokens * self.cache_read
        )
        return mult * raw / M


class PriceTable:
    def __init__(self, models: dict[str, ModelPrice]):
        self.models = models

    @classmethod
    def load(cls, path: Path) -> PriceTable:
        data = tomllib.loads(Path(path).read_text())
        return cls({name: ModelPrice(**fields) for name, fields in data["models"].items()})

    def _price(self, model: str) -> ModelPrice:
        try:
            return self.models[model]
        except KeyError:
            raise KeyError(f"no price for model {model!r}; add it to pricing.toml") from None

    def cost(self, model: str, usage: Usage) -> float:
        return self._price(model).cost(usage)

    def estimate_next_call(self, model: str, prompt_tokens: int, expected_output_tokens: int) -> float:
        """Optimistic: the prompt is read from a warm cache, output is the expected length."""
        return self.cost(model, Usage(output_tokens=expected_output_tokens, cache_read_tokens=prompt_tokens))


class SpendMeter:
    def __init__(self, prices: PriceTable):
        self.prices = prices
        self.total_usd = 0.0
        self.usage_by_model: dict[str, Usage] = {}

    def record(self, model: str, usage: Usage) -> float:
        cost = self.prices.cost(model, usage)
        self.total_usd += cost
        self.usage_by_model[model] = self.usage_by_model.get(model, Usage()) + usage
        return cost

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self.usage_by_model.values())
