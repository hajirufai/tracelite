"""Tests for ASCII waterfall visualization."""

import pytest
from tracelite.visualizer import render_waterfall, render_span_tree


def make_span_dict(name, span_id, parent_span_id=None, service="svc",
                   start_ns=0, duration_ns=1000000, status="OK"):
    return {
        "name": name,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "trace_id": "a" * 32,
        "service_name": service,
        "status_code": status,
        "start_time_ns": start_ns,
        "end_time_ns": start_ns + duration_ns,
        "duration_ns": duration_ns,
        "resource": {"service.name": service},
    }


class TestRenderWaterfall:
    def test_single_span(self):
        spans = [make_span_dict("GET /users", "s1", service="api",
                                duration_ns=245_000_000)]
        output = render_waterfall(spans)
        assert "GET /users" in output
        assert "api" in output
        assert "245.0ms" in output
        assert "Trace:" in output

    def test_parent_child(self):
        spans = [
            make_span_dict("GET /users", "s1", service="api",
                          start_ns=0, duration_ns=200_000_000),
            make_span_dict("SELECT users", "s2", parent_span_id="s1",
                          service="db", start_ns=10_000_000, duration_ns=80_000_000),
        ]
        output = render_waterfall(spans)
        assert "GET /users" in output
        assert "SELECT users" in output
        assert "█" in output

    def test_empty(self):
        output = render_waterfall([])
        assert "empty" in output

    def test_width_parameter(self):
        spans = [make_span_dict("op", "s1")]
        output = render_waterfall(spans, width=30)
        assert len(output) > 0

    def test_multiple_services(self):
        spans = [
            make_span_dict("root", "s1", service="gateway", start_ns=0, duration_ns=500000000),
            make_span_dict("auth", "s2", parent_span_id="s1", service="auth", start_ns=10000000, duration_ns=50000000),
            make_span_dict("fetch", "s3", parent_span_id="s1", service="api", start_ns=70000000, duration_ns=300000000),
            make_span_dict("query", "s4", parent_span_id="s3", service="db", start_ns=80000000, duration_ns=150000000),
        ]
        output = render_waterfall(spans)
        assert "gateway" in output
        assert "auth" in output
        assert "api" in output
        assert "db" in output


class TestRenderSpanTree:
    def test_single_span(self):
        spans = [make_span_dict("GET /users", "s1", duration_ns=100_000_000)]
        output = render_span_tree(spans)
        assert "GET /users" in output
        assert "100.0ms" in output

    def test_tree_structure(self):
        spans = [
            make_span_dict("root", "s1", duration_ns=200_000_000),
            make_span_dict("child1", "s2", parent_span_id="s1", duration_ns=50_000_000),
            make_span_dict("child2", "s3", parent_span_id="s1", duration_ns=80_000_000),
        ]
        output = render_span_tree(spans)
        assert "├──" in output or "└──" in output
        assert "child1" in output
        assert "child2" in output

    def test_error_marker(self):
        spans = [
            make_span_dict("root", "s1"),
            make_span_dict("fail", "s2", parent_span_id="s1", status="ERROR"),
        ]
        output = render_span_tree(spans)
        assert "✗" in output  # Error marker

    def test_empty(self):
        output = render_span_tree([])
        assert "empty" in output
