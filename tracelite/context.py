"""
Context propagation for distributed tracing.

Uses Python's contextvars to maintain the current span across
function calls and thread boundaries. Each thread/coroutine
gets its own context automatically.
"""

from __future__ import annotations

import contextvars
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tracelite.span import Span


_current_span: contextvars.ContextVar[Optional["Span"]] = contextvars.ContextVar(
    "current_span", default=None
)


def get_current_span() -> Optional["Span"]:
    """Get the currently active span in this context."""
    return _current_span.get()


def set_current_span(span: Optional["Span"]) -> contextvars.Token:
    """
    Set the active span and return a token for restoring the previous value.

    Usage:
        token = set_current_span(my_span)
        try:
            # ... do work with my_span as active ...
        finally:
            restore_span(token)
    """
    return _current_span.set(span)


def restore_span(token: contextvars.Token) -> None:
    """Restore the previous span from a token."""
    _current_span.reset(token)


class SpanContext:
    """
    Immutable context that identifies a span within a trace.

    Carries the trace_id, span_id, and trace flags across
    process/service boundaries via propagators.
    """

    __slots__ = ("trace_id", "span_id", "trace_flags", "trace_state", "is_remote")

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        trace_flags: int = 1,
        trace_state: Optional[dict[str, str]] = None,
        is_remote: bool = False,
    ):
        self.trace_id = trace_id
        self.span_id = span_id
        self.trace_flags = trace_flags
        self.trace_state = trace_state or {}
        self.is_remote = is_remote

    @property
    def is_sampled(self) -> bool:
        """Check if the sampled flag (bit 0) is set."""
        return bool(self.trace_flags & 0x01)

    @property
    def is_valid(self) -> bool:
        """A context is valid if trace_id and span_id are non-zero."""
        try:
            return int(self.trace_id, 16) != 0 and int(self.span_id, 16) != 0
        except (ValueError, TypeError):
            return False

    def __repr__(self) -> str:
        return (
            f"SpanContext(trace_id={self.trace_id[:8]}..., "
            f"span_id={self.span_id[:8]}..., sampled={self.is_sampled})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SpanContext):
            return NotImplemented
        return (
            self.trace_id == other.trace_id
            and self.span_id == other.span_id
            and self.trace_flags == other.trace_flags
        )

    def __hash__(self) -> int:
        return hash((self.trace_id, self.span_id, self.trace_flags))
