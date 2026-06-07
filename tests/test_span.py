"""Tests for the Span model."""

import time
import pytest
from tracelite.span import (
    Span, SpanKind, StatusCode, SpanStatus, Event, Link, Resource
)


class TestSpanCreation:
    def test_default_span(self):
        span = Span(name="test-op")
        assert span.name == "test-op"
        assert len(span.trace_id) == 32
        assert len(span.span_id) == 16
        assert span.parent_span_id is None
        assert span.kind == SpanKind.INTERNAL
        assert span.status.code == StatusCode.UNSET
        assert not span.is_ended
        assert span.is_recording

    def test_span_with_ids(self):
        span = Span(
            name="child",
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
        )
        assert span.trace_id == "a" * 32
        assert span.span_id == "b" * 16
        assert span.parent_span_id == "c" * 16

    def test_span_with_kind(self):
        span = Span(name="server", kind=SpanKind.SERVER)
        assert span.kind == SpanKind.SERVER

    def test_span_with_resource(self):
        resource = Resource(attributes={"service.name": "api"})
        span = Span(name="op", resource=resource)
        assert span.resource.service_name == "api"

    def test_span_with_attributes(self):
        span = Span(name="op", attributes={"key": "value", "num": 42})
        assert span.attributes["key"] == "value"
        assert span.attributes["num"] == 42


class TestSpanLifecycle:
    def test_end_span(self):
        span = Span(name="op")
        assert not span.is_ended
        span.end()
        assert span.is_ended
        assert not span.is_recording
        assert span.end_time_ns is not None
        assert span.duration_ns > 0

    def test_end_idempotent(self):
        span = Span(name="op")
        span.end()
        end1 = span.end_time_ns
        span.end()
        assert span.end_time_ns == end1

    def test_end_with_timestamp(self):
        span = Span(name="op", start_time_ns=1000)
        span.end(end_time_ns=5000)
        assert span.duration_ns == 4000

    def test_duration_zero_before_end(self):
        span = Span(name="op")
        assert span.duration_ns == 0

    def test_context_manager(self):
        with Span(name="op") as span:
            span.set_attribute("inside", True)
        assert span.is_ended
        assert span.attributes["inside"] is True

    def test_context_manager_exception(self):
        with pytest.raises(ValueError):
            with Span(name="op") as span:
                raise ValueError("boom")
        assert span.is_ended
        assert span.status.code == StatusCode.ERROR
        assert len(span.events) == 1
        assert span.events[0].name == "exception"


class TestSpanAttributes:
    def test_set_attribute(self):
        span = Span(name="op")
        span.set_attribute("key", "val")
        assert span.attributes["key"] == "val"

    def test_set_attributes_bulk(self):
        span = Span(name="op")
        span.set_attributes({"a": 1, "b": 2, "c": 3})
        assert span.attributes == {"a": 1, "b": 2, "c": 3}

    def test_set_attribute_after_end(self):
        span = Span(name="op")
        span.end()
        span.set_attribute("late", True)
        assert "late" not in span.attributes

    def test_chain_attributes(self):
        span = Span(name="op")
        result = span.set_attribute("x", 1)
        assert result is span


class TestSpanEvents:
    def test_add_event(self):
        span = Span(name="op")
        span.add_event("checkpoint", {"step": 1})
        assert len(span.events) == 1
        assert span.events[0].name == "checkpoint"
        assert span.events[0].attributes["step"] == 1

    def test_multiple_events(self):
        span = Span(name="op")
        span.add_event("start")
        span.add_event("middle")
        span.add_event("end")
        assert len(span.events) == 3

    def test_event_timestamp(self):
        span = Span(name="op")
        span.add_event("check")
        assert span.events[0].timestamp_ns > 0

    def test_add_event_after_end(self):
        span = Span(name="op")
        span.end()
        span.add_event("late")
        assert len(span.events) == 0


class TestSpanLinks:
    def test_add_link(self):
        span = Span(name="op")
        span.add_link("a" * 32, "b" * 16, {"reason": "causal"})
        assert len(span.links) == 1
        assert span.links[0].trace_id == "a" * 32


class TestSpanStatus:
    def test_set_status_ok(self):
        span = Span(name="op")
        span.set_status(StatusCode.OK)
        assert span.status.code == StatusCode.OK

    def test_set_status_error(self):
        span = Span(name="op")
        span.set_status(StatusCode.ERROR, "something broke")
        assert span.status.code == StatusCode.ERROR
        assert span.status.description == "something broke"

    def test_ok_cannot_be_unset(self):
        span = Span(name="op")
        span.set_status(StatusCode.OK)
        span.set_status(StatusCode.UNSET)
        assert span.status.code == StatusCode.OK

    def test_record_exception(self):
        span = Span(name="op")
        span.record_exception(ValueError("bad input"))
        assert span.status.code == StatusCode.ERROR
        assert len(span.events) == 1
        ev = span.events[0]
        assert ev.name == "exception"
        assert ev.attributes["exception.type"] == "ValueError"
        assert ev.attributes["exception.message"] == "bad input"


class TestSpanSerialization:
    def test_to_dict(self):
        span = Span(name="op", attributes={"key": "val"})
        span.add_event("check")
        span.end()
        d = span.to_dict()
        assert d["name"] == "op"
        assert d["trace_id"] == span.trace_id
        assert d["attributes"]["key"] == "val"
        assert len(d["events"]) == 1
        assert d["duration_ns"] > 0

    def test_from_dict(self):
        original = Span(name="op", attributes={"x": 1})
        original.add_event("check", {"step": 1})
        original.set_status(StatusCode.OK)
        original.end()
        d = original.to_dict()
        restored = Span.from_dict(d)
        assert restored.name == original.name
        assert restored.trace_id == original.trace_id
        assert restored.span_id == original.span_id
        assert restored.attributes == original.attributes
        assert restored.status.code == StatusCode.OK
        assert len(restored.events) == 1

    def test_round_trip(self):
        span = Span(
            name="test",
            kind=SpanKind.SERVER,
            attributes={"http.method": "GET"},
        )
        span.end()
        d = span.to_dict()
        restored = Span.from_dict(d)
        assert restored.kind == SpanKind.SERVER
        assert restored.attributes["http.method"] == "GET"


class TestResource:
    def test_service_name(self):
        r = Resource(attributes={"service.name": "myservice"})
        assert r.service_name == "myservice"

    def test_default_service_name(self):
        r = Resource()
        assert r.service_name == "unknown"

    def test_merge(self):
        r1 = Resource(attributes={"service.name": "a", "version": "1.0"})
        r2 = Resource(attributes={"service.name": "b", "host": "localhost"})
        merged = r1.merge(r2)
        assert merged.service_name == "b"
        assert merged.attributes["host"] == "localhost"
        assert merged.attributes["version"] == "1.0"


class TestEvent:
    def test_event_creation(self):
        ev = Event(name="test")
        assert ev.name == "test"
        assert ev.timestamp_ns > 0
        assert ev.attributes == {}

    def test_event_to_dict(self):
        ev = Event(name="test", attributes={"key": "val"})
        d = ev.to_dict()
        assert d["name"] == "test"
        assert d["attributes"]["key"] == "val"


class TestSpanKind:
    def test_all_kinds(self):
        kinds = [SpanKind.INTERNAL, SpanKind.SERVER, SpanKind.CLIENT,
                 SpanKind.PRODUCER, SpanKind.CONSUMER]
        assert len(kinds) == 5
