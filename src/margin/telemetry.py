"""neatlogs shim. Without NEATLOGS_API_KEY every call is a no-op, so tests and dry runs need no network.

neatlogs.init must run before `anthropic` is imported (auto-instrumentation attaches at import),
so nothing in this package imports anthropic at module level.
"""
from __future__ import annotations

import contextlib
import functools
import json
import os
from collections.abc import Callable, Iterator
from typing import Any

_enabled = False


def init_telemetry(workflow_name: str, tags: list[str]) -> bool:
    global _enabled
    key = os.environ.get("NEATLOGS_API_KEY")
    if not key:
        return False
    import neatlogs

    neatlogs.init(api_key=key, workflow_name=workflow_name, instrumentations=["anthropic"], tags=tags)
    _enabled = True
    return True


def shutdown_telemetry() -> None:
    if not _enabled:
        return
    import neatlogs

    neatlogs.flush()
    neatlogs.shutdown()


def coerce(value: Any) -> Any:
    """neatlogs documents str, int and bool attribute values; everything else becomes a string."""
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return f"{value:.6f}"
    return json.dumps(value, sort_keys=True, default=str)


class _NullSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None


def span(kind: str, name: str | None = None, **kwargs: Any) -> Callable:
    """Decorator: a neatlogs span when telemetry is on, otherwise a pass-through."""

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kw: Any) -> Any:
            if not _enabled:
                return fn(*args, **kw)
            import neatlogs

            return neatlogs.span(kind=kind, name=name or fn.__name__, **kwargs)(fn)(*args, **kw)

        return wrapper

    return decorate


@contextlib.contextmanager
def trace(name: str, kind: str, **attrs: Any) -> Iterator[Any]:
    if not _enabled:
        yield _NullSpan()
        return
    import neatlogs

    with neatlogs.trace(name, kind=kind) as sp:
        for key, value in attrs.items():
            sp.set_attribute(key, coerce(value))
        yield sp
