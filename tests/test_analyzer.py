"""Tests for trace analysis."""

import pytest
from tracelite.analyzer import (
    critical_path, latency_breakdown, find_gaps, error_summary, span_depth
)


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
        "events": [],
        "resource": {"service.name": service},
    }


class TestCriticalPath:
    def test_single_span(self):
        spans = [make_span_dict("root", "s1", duration_ns=100)]
        path = critical_path(spans)
        assert len(path) == 1
        assert path[0]["name"] == "root"

    def test_linear_chain(self):
        spans = [
            make_span_dict("root", "s1", duration_ns=200),
            make_span_dict("child", "s2", parent_span_id="s1", duration_ns=150),
            make_span_dict("leaf", "s3", parent_span_id="s2", duration_ns=100),
        ]
        path = critical_path(spans)
        assert len(path) == 3
        assert [p["name"] for p in path] == ["root", "child", "leaf"]

    def test_branching_picks_longest(self):
        spans = [
            make_span_dict("root", "s1", duration_ns=200),
            make_span_dict("short", "s2", parent_span_id="s1", duration_ns=50),
            make_span_dict("long", "s3", parent_span_id="s1", duration_ns=150),
        ]
        path = critical_path(spans)
        assert len(path) == 2
        assert path[1]["name"] == "long"

    def test_empty(self):
        assert critical_path([]) == []


class TestLatencyBreakdown:
    def test_single_service(self):
        spans = [
            make_span_dict("op1", "s1", service="api", duration_ns=100),
            make_span_dict("op2", "s2", service="api", duration_ns=200),
        ]
        breakdown = latency_breakdown(spans)
        assert len(breakdown) == 2

    def test_multiple_services(self):
        spans = [
            make_span_dict("root", "s1", service="api", duration_ns=500),
            make_span_dict("query", "s2", parent_span_id="s1",
                          service="db", duration_ns=300),
        ]
        breakdown = latency_breakdown(spans)
        services = {b["service"] for b in breakdown}
        assert "api" in services
        assert "db" in services

    def test_empty(self):
        assert latency_breakdown([]) == []

    def test_percentage(self):
        spans = [
            make_span_dict("root", "s1", service="api", duration_ns=1000),
            make_span_dict("db", "s2", parent_span_id="s1",
                          service="db", duration_ns=500),
        ]
        breakdown = latency_breakdown(spans)
        root_entry = next(b for b in breakdown if b["operation"] == "root")
        assert root_entry["pct"] == 100.0


class TestFindGaps:
    def test_gap_between_children(self):
        spans = [
            make_span_dict("parent", "s1", start_ns=0, duration_ns=1000),
            make_span_dict("child1", "s2", parent_span_id="s1",
                          start_ns=100, duration_ns=200),
            make_span_dict("child2", "s3", parent_span_id="s1",
                          start_ns=500, duration_ns=200),
        ]
        gaps = find_gaps(spans)
        assert len(gaps) >= 1
        # Should find gap between child1 end (300) and child2 start (500)
        between_gaps = [g for g in gaps if g["type"] == "between_children"]
        assert len(between_gaps) == 1
        assert between_gaps[0]["gap_ns"] == 200

    def test_no_gaps(self):
        spans = [make_span_dict("solo", "s1")]
        gaps = find_gaps(spans)
        assert gaps == []

    def test_empty(self):
        assert find_gaps([]) == []


class TestErrorSummary:
    def test_no_errors(self):
        spans = [make_span_dict("op", "s1", status="OK")]
        summary = error_summary(spans)
        assert summary["total_errors"] == 0
        assert summary["error_rate"] == 0

    def test_with_errors(self):
        spans = [
            make_span_dict("op1", "s1", status="OK"),
            make_span_dict("op2", "s2", status="ERROR", service="db"),
        ]
        summary = error_summary(spans)
        assert summary["total_errors"] == 1
        assert summary["error_rate"] == 0.5
        assert summary["by_service"]["db"] == 1

    def test_exception_types(self):
        spans = [{
            "name": "fail",
            "span_id": "s1",
            "trace_id": "a" * 32,
            "service_name": "api",
            "status_code": "ERROR",
            "events": [
                {"name": "exception", "attributes": {"exception.type": "ValueError"}},
            ],
            "resource": {},
        }]
        summary = error_summary(spans)
        assert summary["exception_types"]["ValueError"] == 1


class TestSpanDepth:
    def test_single_span(self):
        spans = [make_span_dict("root", "s1")]
        assert span_depth(spans) == 1

    def test_two_levels(self):
        spans = [
            make_span_dict("root", "s1"),
            make_span_dict("child", "s2", parent_span_id="s1"),
        ]
        assert span_depth(spans) == 2

    def test_three_levels(self):
        spans = [
            make_span_dict("root", "s1"),
            make_span_dict("mid", "s2", parent_span_id="s1"),
            make_span_dict("leaf", "s3", parent_span_id="s2"),
        ]
        assert span_depth(spans) == 3

    def test_wide_tree(self):
        spans = [
            make_span_dict("root", "s1"),
            make_span_dict("c1", "s2", parent_span_id="s1"),
            make_span_dict("c2", "s3", parent_span_id="s1"),
            make_span_dict("c3", "s4", parent_span_id="s1"),
        ]
        assert span_depth(spans) == 2

    def test_empty(self):
        assert span_depth([]) == 0
