"""Tests for the Tracer and TracerProvider."""

import pytest
from tracelite.tracer import Tracer, TracerProvider
from tracelite.span import Span, SpanKind, StatusCode, Resource
from tracelite.sampler import AlwaysOnSampler, AlwaysOffSampler
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.context import get_current_span


class TestTracerProvider:
    def test_create_provider(self):
        provider = TracerProvider(
            resource=Resource(attributes={"service.name": "test-svc"})
        )
        assert provider.resource.service_name == "test-svc"

    def test_get_tracer(self):
        provider = TracerProvider()
        tracer = provider.get_tracer("my-tracer")
        assert tracer.name == "my-tracer"

    def test_add_processor(self):
        provider = TracerProvider()
        exporter = InMemoryExporter()
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer()
        with tracer.start_span("test") as span:
            pass
        assert exporter.span_count == 1

    def test_shutdown(self):
        provider = TracerProvider()
        exporter = InMemoryExporter()
        proc = SimpleSpanProcessor(exporter)
        provider.add_processor(proc)
        provider.shutdown()
        # Shutdown should be idempotent
        provider.shutdown()

    def test_force_flush(self):
        provider = TracerProvider()
        assert provider.force_flush() is True


class TestTracer:
    def setup_method(self):
        self.exporter = InMemoryExporter()
        self.provider = TracerProvider(
            resource=Resource(attributes={"service.name": "test-svc"}),
            sampler=AlwaysOnSampler(),
        )
        self.provider.add_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("test")

    def test_start_span_basic(self):
        with self.tracer.start_span("my-op") as span:
            assert span.name == "my-op"
            assert span.is_recording
            assert get_current_span() is span
        assert span.is_ended
        assert self.exporter.span_count == 1

    def test_span_auto_parent(self):
        with self.tracer.start_span("parent") as parent:
            with self.tracer.start_span("child") as child:
                assert child.parent_span_id == parent.span_id
                assert child.trace_id == parent.trace_id

    def test_span_three_levels(self):
        with self.tracer.start_span("root") as root:
            with self.tracer.start_span("mid") as mid:
                with self.tracer.start_span("leaf") as leaf:
                    assert leaf.parent_span_id == mid.span_id
                    assert mid.parent_span_id == root.span_id
                    assert leaf.trace_id == root.trace_id

        assert self.exporter.span_count == 3

    def test_context_restored_after_span(self):
        with self.tracer.start_span("first") as first:
            pass
        assert get_current_span() is None

    def test_span_with_kind(self):
        with self.tracer.start_span("server", kind=SpanKind.SERVER) as span:
            assert span.kind == SpanKind.SERVER

    def test_span_with_attributes(self):
        with self.tracer.start_span("op", attributes={"key": "val"}) as span:
            assert span.attributes["key"] == "val"

    def test_span_resource(self):
        with self.tracer.start_span("op") as span:
            assert span.resource.service_name == "test-svc"

    def test_exception_recorded(self):
        with pytest.raises(RuntimeError):
            with self.tracer.start_span("op") as span:
                raise RuntimeError("boom")
        assert span.status.code == StatusCode.ERROR
        assert len(span.events) == 1

    def test_sampling_off(self):
        provider = TracerProvider(sampler=AlwaysOffSampler())
        exporter = InMemoryExporter()
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer()

        with tracer.start_span("op") as span:
            pass
        # Span is created but not exported
        assert exporter.span_count == 0

    def test_create_span_manual(self):
        span = self.tracer.create_span("manual")
        assert span.name == "manual"
        assert not span.is_ended
        span.end()
