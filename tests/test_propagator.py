"""Tests for W3C Trace Context propagation."""

import pytest
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.context import SpanContext


class TestInject:
    def setup_method(self):
        self.propagator = W3CTraceContextPropagator()

    def test_inject_basic(self):
        ctx = SpanContext(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            trace_flags=1,
        )
        carrier = {}
        self.propagator.inject(ctx, carrier)
        assert carrier["traceparent"] == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    def test_inject_not_sampled(self):
        ctx = SpanContext(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            trace_flags=0,
        )
        carrier = {}
        self.propagator.inject(ctx, carrier)
        assert carrier["traceparent"].endswith("-00")

    def test_inject_with_tracestate(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=1,
            trace_state={"vendor1": "val1", "vendor2": "val2"},
        )
        carrier = {}
        self.propagator.inject(ctx, carrier)
        assert "traceparent" in carrier
        assert "tracestate" in carrier
        assert "vendor1=val1" in carrier["tracestate"]

    def test_inject_invalid_context(self):
        ctx = SpanContext(
            trace_id="0" * 32,
            span_id="0" * 16,
        )
        carrier = {}
        self.propagator.inject(ctx, carrier)
        assert "traceparent" not in carrier


class TestExtract:
    def setup_method(self):
        self.propagator = W3CTraceContextPropagator()

    def test_extract_basic(self):
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.span_id == "00f067aa0ba902b7"
        assert ctx.is_sampled is True
        assert ctx.is_remote is True

    def test_extract_not_sampled(self):
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is not None
        assert ctx.is_sampled is False

    def test_extract_with_tracestate(self):
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "tracestate": "vendor1=value1,vendor2=value2",
        }
        ctx = self.propagator.extract(carrier)
        assert ctx.trace_state["vendor1"] == "value1"
        assert ctx.trace_state["vendor2"] == "value2"

    def test_extract_missing_header(self):
        carrier = {}
        ctx = self.propagator.extract(carrier)
        assert ctx is None

    def test_extract_invalid_format(self):
        carrier = {"traceparent": "not-valid"}
        ctx = self.propagator.extract(carrier)
        assert ctx is None

    def test_extract_version_ff_invalid(self):
        carrier = {
            "traceparent": "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is None

    def test_extract_all_zero_trace_id(self):
        carrier = {
            "traceparent": f"00-{'0' * 32}-00f067aa0ba902b7-01"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is None

    def test_extract_case_insensitive(self):
        carrier = {
            "traceparent": "00-4BF92F3577B34DA6A3CE929D0E0E4736-00F067AA0BA902B7-01"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is not None

    def test_extract_title_case_header(self):
        carrier = {
            "Traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }
        ctx = self.propagator.extract(carrier)
        assert ctx is not None


class TestRoundTrip:
    def test_inject_then_extract(self):
        propagator = W3CTraceContextPropagator()
        original = SpanContext(
            trace_id="abcdef1234567890abcdef1234567890",
            span_id="1234567890abcdef",
            trace_flags=1,
            trace_state={"myvendor": "myvalue"},
        )
        carrier = {}
        propagator.inject(original, carrier)
        restored = propagator.extract(carrier)
        assert restored is not None
        assert restored.trace_id == original.trace_id
        assert restored.span_id == original.span_id
        assert restored.is_sampled == original.is_sampled
        assert restored.trace_state.get("myvendor") == "myvalue"
