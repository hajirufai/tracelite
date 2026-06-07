"""Tests for SQLite span storage."""

import time
import pytest
from tracelite.storage import SpanStorage
from tracelite.span import Span, SpanKind, StatusCode, Resource


def make_span(name, trace_id=None, parent_span_id=None, service="test-svc",
              status=StatusCode.OK, duration_ms=10):
    span = Span(
        name=name,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        resource=Resource(attributes={"service.name": service}),
    )
    span.set_status(status)
    span.end(end_time_ns=span.start_time_ns + duration_ms * 1_000_000)
    return span


class TestSpanStorage:
    def setup_method(self):
        self.storage = SpanStorage(":memory:")

    def teardown_method(self):
        self.storage.close()

    def test_insert_and_count(self):
        span = make_span("op")
        count = self.storage.insert_spans([span])
        assert count == 1
        assert self.storage.span_count() == 1

    def test_insert_batch(self):
        spans = [make_span(f"op-{i}") for i in range(5)]
        count = self.storage.insert_spans(spans)
        assert count == 5
        assert self.storage.span_count() == 5

    def test_insert_empty(self):
        count = self.storage.insert_spans([])
        assert count == 0

    def test_get_trace(self):
        tid = "a" * 32
        root = make_span("root", trace_id=tid, service="api")
        child = make_span("child", trace_id=tid,
                         parent_span_id=root.span_id, service="db")
        self.storage.insert_spans([root, child])

        trace = self.storage.get_trace(tid)
        assert len(trace) == 2
        assert trace[0]["name"] == "root"

    def test_get_trace_not_found(self):
        trace = self.storage.get_trace("nonexistent")
        assert trace == []

    def test_get_traces(self):
        for i in range(3):
            span = make_span(f"root-{i}", service="api")
            self.storage.insert_spans([span])

        traces = self.storage.get_traces(limit=10)
        assert len(traces) == 3

    def test_get_traces_by_service(self):
        self.storage.insert_spans([make_span("op1", service="api")])
        self.storage.insert_spans([make_span("op2", service="db")])

        traces = self.storage.get_traces(service_name="api")
        assert len(traces) == 1

    def test_get_traces_by_operation(self):
        self.storage.insert_spans([make_span("GET /users")])
        self.storage.insert_spans([make_span("POST /users")])

        traces = self.storage.get_traces(operation="GET /users")
        assert len(traces) == 1

    def test_get_traces_min_duration(self):
        self.storage.insert_spans([make_span("fast", duration_ms=5)])
        self.storage.insert_spans([make_span("slow", duration_ms=100)])

        traces = self.storage.get_traces(min_duration_ns=50_000_000)
        assert len(traces) == 1
        assert traces[0][0]["name"] == "slow"

    def test_get_traces_error_only(self):
        self.storage.insert_spans([make_span("ok", status=StatusCode.OK)])
        self.storage.insert_spans([make_span("err", status=StatusCode.ERROR)])

        traces = self.storage.get_traces(error_only=True)
        assert len(traces) == 1

    def test_get_services(self):
        self.storage.insert_spans([make_span("op1", service="api")])
        self.storage.insert_spans([make_span("op2", service="api")])
        self.storage.insert_spans([make_span("op3", service="db")])

        services = self.storage.get_services()
        assert len(services) == 2
        assert services[0]["service_name"] == "api"
        assert services[0]["span_count"] == 2

    def test_get_operations(self):
        self.storage.insert_spans([make_span("GET /users")])
        self.storage.insert_spans([make_span("GET /users")])
        self.storage.insert_spans([make_span("POST /users")])

        ops = self.storage.get_operations()
        assert len(ops) == 2

    def test_trace_count(self):
        t1 = "a" * 32
        t2 = "b" * 32
        self.storage.insert_spans([make_span("op1", trace_id=t1)])
        self.storage.insert_spans([make_span("op2", trace_id=t1)])
        self.storage.insert_spans([make_span("op3", trace_id=t2)])

        assert self.storage.trace_count() == 2

    def test_duplicate_span_id_ignored(self):
        span = make_span("op")
        self.storage.insert_spans([span])
        self.storage.insert_spans([span])  # Same span_id
        assert self.storage.span_count() == 1

    def test_context_manager(self):
        with SpanStorage(":memory:") as storage:
            storage.insert_spans([make_span("op")])
            assert storage.span_count() == 1

    def test_compact(self):
        self.storage.insert_spans([make_span("op")])
        self.storage.compact()  # Should not raise
        assert self.storage.span_count() == 1
