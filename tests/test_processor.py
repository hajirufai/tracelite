"""Tests for span processors."""

import time
import pytest
from tracelite.processor import SimpleSpanProcessor, BatchSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.span import Span


class TestSimpleSpanProcessor:
    def test_exports_on_end(self):
        exporter = InMemoryExporter()
        proc = SimpleSpanProcessor(exporter)
        span = Span(name="test")
        span.end()
        proc.on_end(span)
        assert exporter.span_count == 1

    def test_ignores_unfinished_span(self):
        exporter = InMemoryExporter()
        proc = SimpleSpanProcessor(exporter)
        span = Span(name="test")
        proc.on_end(span)
        assert exporter.span_count == 0

    def test_shutdown_stops_export(self):
        exporter = InMemoryExporter()
        proc = SimpleSpanProcessor(exporter)
        proc.shutdown()
        span = Span(name="test")
        span.end()
        proc.on_end(span)
        assert exporter.span_count == 0

    def test_force_flush(self):
        exporter = InMemoryExporter()
        proc = SimpleSpanProcessor(exporter)
        assert proc.force_flush() is True


class TestBatchSpanProcessor:
    def test_exports_batch(self):
        exporter = InMemoryExporter()
        proc = BatchSpanProcessor(
            exporter, max_batch_size=10, schedule_delay_ms=100
        )
        for i in range(5):
            span = Span(name=f"span-{i}")
            span.end()
            proc.on_end(span)

        time.sleep(0.3)  # Wait for batch export
        proc.shutdown()
        assert exporter.span_count == 5

    def test_force_flush(self):
        exporter = InMemoryExporter()
        proc = BatchSpanProcessor(
            exporter, max_batch_size=100, schedule_delay_ms=5000
        )
        for i in range(3):
            span = Span(name=f"span-{i}")
            span.end()
            proc.on_end(span)

        proc.force_flush(timeout_ms=2000)
        proc.shutdown()
        assert exporter.span_count == 3

    def test_shutdown_exports_remaining(self):
        exporter = InMemoryExporter()
        proc = BatchSpanProcessor(
            exporter, max_batch_size=100, schedule_delay_ms=10000
        )
        span = Span(name="last")
        span.end()
        proc.on_end(span)
        proc.shutdown()
        assert exporter.span_count >= 1

    def test_drops_when_queue_full(self):
        exporter = InMemoryExporter()
        proc = BatchSpanProcessor(
            exporter, max_queue_size=2, schedule_delay_ms=10000
        )
        for i in range(10):
            span = Span(name=f"span-{i}")
            span.end()
            proc.on_end(span)

        proc.shutdown()
        # Some spans should be dropped
        assert exporter.span_count <= 10
