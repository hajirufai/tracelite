"""
Decorator-based tracing for functions.

The @trace decorator wraps any function in a span,
automatically recording timing, attributes, and exceptions.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Optional, Callable

from tracelite.span import Span, SpanKind, StatusCode, Resource
from tracelite.context import get_current_span, set_current_span, restore_span
from tracelite.clock import now_ns, monotonic_ns


# Module-level list of processors that decorators will use
_decorator_processors: list = []
_decorator_resource: Optional[Resource] = None


def configure_decorator_tracing(
    processors: list = None,
    resource: Optional[Resource] = None,
) -> None:
    """
    Configure global settings for @trace decorators.

    Call this once at startup to set the processors and resource
    that decorated functions will use.
    """
    global _decorator_processors, _decorator_resource
    if processors is not None:
        _decorator_processors = processors
    if resource is not None:
        _decorator_resource = resource


def trace(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict[str, Any]] = None,
    record_args: bool = False,
):
    """
    Decorator that wraps a function call in a tracing span.

    Can be used with or without arguments:

        @trace
        def my_function():
            ...

        @trace(name="custom-name", attributes={"key": "val"})
        def my_function():
            ...

        @trace(record_args=True)
        def my_function(x, y):
            ...
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            parent = get_current_span()
            trace_id = parent.trace_id if parent else None
            parent_span_id = parent.span_id if parent else None

            span = Span(
                name=span_name,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                kind=kind,
                resource=_decorator_resource or Resource(),
                attributes=dict(attributes) if attributes else {},
            )

            if record_args:
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                for param_name, param_val in bound.arguments.items():
                    span.set_attribute(f"arg.{param_name}", repr(param_val))

            token = set_current_span(span)

            for proc in _decorator_processors:
                proc.on_start(span)

            try:
                result = func(*args, **kwargs)
                span.set_status(StatusCode.OK)
                return result
            except Exception as exc:
                span.record_exception(exc)
                raise
            finally:
                span.end()
                for proc in _decorator_processors:
                    proc.on_end(span)
                restore_span(token)

        return wrapper

    if _func is not None:
        return decorator(_func)
    return decorator
