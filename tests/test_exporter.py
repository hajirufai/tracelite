"""Tests for span exporters."""

import os
import json
import tempfile
import io
import pytest
from tracelite.exporter import (
    ConsoleExporter, JSONFileExporter, InMemoryExporter, ExportResult
)
from tracelite.span import Span, StatusCode, Resource


class TestConsoleExporter:
    def test_export_basic(self):
        output = io.StringIO()
        exporter = ConsoleExporter(colored=False, output=output)
        span = Span(name="test-op", resource=Resource(attributes={"service.name": "myservice"}))
        span.end()
        result = exporter.export([span])
        assert result == ExportResult.SUCCESS
        text = output.getvalue()
        assert "myservice" in text
        assert "test-op" in text

    def test_export_with_attributes(self):
        output = io.StringIO()
        exporter = ConsoleExporter(colored=False, output=output)
        span = Span(name="op", attributes={"key": "value"})
        span.end()
        exporter.export([span])
        text = output.getvalue()
        assert "key=value" in text

    def test_export_with_events(self):
        output = io.StringIO()
        exporter = ConsoleExporter(colored=False, output=output)
        span = Span(name="op")
        span.add_event("checkpoint")
        span.end()
        exporter.export([span])
        text = output.getvalue()
        assert "checkpoint" in text

    def test_colored_output(self):
        output = io.StringIO()
        exporter = ConsoleExporter(colored=True, output=output)
        span = Span(name="op")
        span.set_status(StatusCode.ERROR, "fail")
        span.end()
        exporter.export([span])
        text = output.getvalue()
        assert "\033[31m" in text  # Red for errors


class TestJSONFileExporter:
    def test_export_to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            exporter = JSONFileExporter(path)
            span = Span(name="test", attributes={"x": 1})
            span.end()
            result = exporter.export([span])
            assert result == ExportResult.SUCCESS

            with open(path) as f:
                line = f.readline()
                data = json.loads(line)
                assert data["name"] == "test"
                assert data["attributes"]["x"] == 1
        finally:
            os.unlink(path)

    def test_append_multiple(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            exporter = JSONFileExporter(path)
            for i in range(3):
                span = Span(name=f"span-{i}")
                span.end()
                exporter.export([span])

            with open(path) as f:
                lines = f.readlines()
                assert len(lines) == 3
        finally:
            os.unlink(path)

    def test_export_failure(self):
        exporter = JSONFileExporter("/nonexistent/path/file.json")
        span = Span(name="test")
        span.end()
        result = exporter.export([span])
        assert result == ExportResult.FAILURE


class TestInMemoryExporter:
    def test_export(self):
        exporter = InMemoryExporter()
        span = Span(name="test")
        span.end()
        exporter.export([span])
        assert exporter.span_count == 1
        assert exporter.get_spans()[0].name == "test"

    def test_clear(self):
        exporter = InMemoryExporter()
        span = Span(name="test")
        span.end()
        exporter.export([span])
        exporter.clear()
        assert exporter.span_count == 0

    def test_find_by_name(self):
        exporter = InMemoryExporter()
        for name in ["op-a", "op-b", "op-a"]:
            span = Span(name=name)
            span.end()
            exporter.export([span])

        found = exporter.find_by_name("op-a")
        assert len(found) == 2

    def test_find_by_trace(self):
        exporter = InMemoryExporter()
        tid = "a" * 32
        span1 = Span(name="op1", trace_id=tid)
        span2 = Span(name="op2", trace_id=tid)
        span3 = Span(name="op3")  # Different trace
        for s in [span1, span2, span3]:
            s.end()
            exporter.export([s])

        found = exporter.find_by_trace(tid)
        assert len(found) == 2
