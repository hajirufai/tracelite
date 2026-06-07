"""Tests for service dependency graph."""

import pytest
from tracelite.graph import ServiceGraph


def make_span_dict(name, span_id, parent_span_id=None, service="svc",
                   duration_ns=1000000, status="OK"):
    return {
        "name": name,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "trace_id": "a" * 32,
        "service_name": service,
        "status_code": status,
        "duration_ns": duration_ns,
        "resource": {"service.name": service},
    }


class TestServiceGraph:
    def test_empty(self):
        graph = ServiceGraph()
        assert graph.nodes == []
        assert graph.edges == []

    def test_single_service_no_edges(self):
        spans = [
            make_span_dict("root", "s1", service="api"),
            make_span_dict("child", "s2", parent_span_id="s1", service="api"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans])
        assert "api" in graph.nodes
        assert graph.edges == []

    def test_two_services(self):
        spans = [
            make_span_dict("root", "s1", service="api"),
            make_span_dict("query", "s2", parent_span_id="s1", service="db"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans])
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge["source"] == "api"
        assert edge["target"] == "db"
        assert edge["call_count"] == 1

    def test_multiple_calls(self):
        traces = []
        for _ in range(3):
            spans = [
                make_span_dict("root", f"s1_{_}", service="api"),
                make_span_dict("query", f"s2_{_}",
                              parent_span_id=f"s1_{_}", service="db"),
            ]
            traces.append(spans)

        graph = ServiceGraph()
        graph.add_traces(traces)
        edge = graph.edges[0]
        assert edge["call_count"] == 3

    def test_error_rate(self):
        spans_ok = [
            make_span_dict("root", "s1a", service="api"),
            make_span_dict("query", "s2a", parent_span_id="s1a",
                          service="db", status="OK"),
        ]
        spans_err = [
            make_span_dict("root", "s1b", service="api"),
            make_span_dict("query", "s2b", parent_span_id="s1b",
                          service="db", status="ERROR"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans_ok, spans_err])
        edge = graph.edges[0]
        assert edge["error_rate"] == 0.5

    def test_to_dot(self):
        spans = [
            make_span_dict("root", "s1", service="api"),
            make_span_dict("query", "s2", parent_span_id="s1", service="db"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans])
        dot = graph.to_dot()
        assert "digraph" in dot
        assert "api" in dot
        assert "db" in dot

    def test_to_ascii(self):
        spans = [
            make_span_dict("root", "s1", service="api"),
            make_span_dict("query", "s2", parent_span_id="s1", service="db"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans])
        ascii_out = graph.to_ascii()
        assert "api" in ascii_out
        assert "db" in ascii_out

    def test_topological_sort(self):
        spans = [
            make_span_dict("root", "s1", service="gateway"),
            make_span_dict("mid", "s2", parent_span_id="s1", service="api"),
            make_span_dict("leaf", "s3", parent_span_id="s2", service="db"),
        ]
        graph = ServiceGraph()
        graph.add_traces([spans])
        order = graph.topological_sort()
        assert order.index("gateway") < order.index("api")
        assert order.index("api") < order.index("db")

    def test_empty_ascii(self):
        graph = ServiceGraph()
        assert "no service dependencies" in graph.to_ascii()
