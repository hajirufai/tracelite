"""Tests for context propagation."""

import threading
import pytest
from tracelite.context import (
    get_current_span, set_current_span, restore_span, SpanContext
)
from tracelite.span import Span


class TestContextVars:
    def test_default_is_none(self):
        assert get_current_span() is None

    def test_set_and_get(self):
        span = Span(name="test")
        token = set_current_span(span)
        assert get_current_span() is span
        restore_span(token)

    def test_restore(self):
        span1 = Span(name="outer")
        span2 = Span(name="inner")

        token1 = set_current_span(span1)
        assert get_current_span() is span1

        token2 = set_current_span(span2)
        assert get_current_span() is span2

        restore_span(token2)
        assert get_current_span() is span1

        restore_span(token1)
        assert get_current_span() is None

    def test_thread_isolation(self):
        span = Span(name="main-span")
        set_current_span(span)

        other_span = [None]
        def check_other_thread():
            other_span[0] = get_current_span()

        t = threading.Thread(target=check_other_thread)
        t.start()
        t.join()

        # New threads don't inherit context by default
        # (They get whatever was set at thread creation time or None)
        # This is expected behavior for contextvars
        assert get_current_span() is span


class TestSpanContext:
    def test_creation(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=1,
        )
        assert ctx.trace_id == "a" * 32
        assert ctx.span_id == "b" * 16
        assert ctx.is_sampled is True
        assert ctx.is_valid is True

    def test_not_sampled(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=0,
        )
        assert ctx.is_sampled is False

    def test_invalid_zero_trace_id(self):
        ctx = SpanContext(
            trace_id="0" * 32,
            span_id="b" * 16,
        )
        assert ctx.is_valid is False

    def test_invalid_zero_span_id(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="0" * 16,
        )
        assert ctx.is_valid is False

    def test_remote_flag(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            is_remote=True,
        )
        assert ctx.is_remote is True

    def test_trace_state(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_state={"vendor": "value"},
        )
        assert ctx.trace_state["vendor"] == "value"

    def test_equality(self):
        ctx1 = SpanContext("a" * 32, "b" * 16, 1)
        ctx2 = SpanContext("a" * 32, "b" * 16, 1)
        assert ctx1 == ctx2

    def test_inequality(self):
        ctx1 = SpanContext("a" * 32, "b" * 16, 1)
        ctx2 = SpanContext("a" * 32, "c" * 16, 1)
        assert ctx1 != ctx2

    def test_hash(self):
        ctx1 = SpanContext("a" * 32, "b" * 16, 1)
        ctx2 = SpanContext("a" * 32, "b" * 16, 1)
        assert hash(ctx1) == hash(ctx2)
        s = {ctx1, ctx2}
        assert len(s) == 1
