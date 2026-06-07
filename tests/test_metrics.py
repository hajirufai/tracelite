"""Tests for RED metrics computation."""

import pytest
from tracelite.metrics import REDMetrics
from tracelite.storage import SpanStorage
from tracelite.span import Span, StatusCode, Resource


def make_span(name, service="api", status=StatusCode.OK, duration_ms=10):
    span = Span(
        name=name,
        resource=Resource(attributes={"service.name": service}),
    )
    span.set_status(status)
    span.end(end_time_ns=span.start_time_ns + duration_ms * 1_000_000)
    return span


class TestREDMetrics:
    def setup_method(self):
        self.storage = SpanStorage(":memory:")
        self.red = REDMetrics(self.storage)

    def teardown_method(self):
        self.storage.close()

    def test_compute_empty(self):
        metrics = self.red.compute()
        assert metrics["total_requests"] == 0
        assert metrics["rate"] == 0
        assert metrics["error_rate"] == 0

    def test_compute_basic(self):
        for i in range(10):
            self.storage.insert_spans([make_span(f"op-{i}")])

        metrics = self.red.compute(window_seconds=3600)
        assert metrics["total_requests"] == 10

    def test_error_rate(self):
        for i in range(8):
            self.storage.insert_spans([make_span(f"ok-{i}", status=StatusCode.OK)])
        for i in range(2):
            self.storage.insert_spans([make_span(f"err-{i}", status=StatusCode.ERROR)])

        metrics = self.red.compute(window_seconds=3600)
        assert metrics["total_errors"] == 2

    def test_duration_percentiles(self):
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            self.storage.insert_spans([make_span("op", duration_ms=ms)])

        metrics = self.red.compute(window_seconds=3600)
        dur = metrics["duration"]
        assert dur["min"] > 0
        assert dur["max"] >= dur["min"]
        assert dur["p50"] <= dur["p90"]
        assert dur["p90"] <= dur["p99"]

    def test_compute_by_service(self):
        self.storage.insert_spans([make_span("op1", service="api")])
        self.storage.insert_spans([make_span("op2", service="db")])

        by_service = self.red.compute_by_service()
        assert len(by_service) == 2
        services = {m["service"] for m in by_service}
        assert "api" in services
        assert "db" in services

    def test_format_summary(self):
        self.storage.insert_spans([make_span("op")])
        metrics = self.red.compute()
        summary = self.red.format_summary(metrics)
        assert "Rate:" in summary
        assert "Errors:" in summary
        assert "Duration:" in summary

    def test_percentile_edge_case_single(self):
        p = REDMetrics._compute_percentiles([100])
        assert p["p50"] == 100
        assert p["min"] == 100
        assert p["max"] == 100

    def test_percentile_empty(self):
        p = REDMetrics._compute_percentiles([])
        assert p["p50"] == 0
