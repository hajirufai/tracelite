"""Integration tests — end-to-end tracing scenarios."""

import time
import pytest
from tracelite.tracer import TracerProvider
from tracelite.span import Resource, SpanKind, StatusCode
from tracelite.sampler import AlwaysOnSampler, ProbabilisticSampler
from tracelite.processor import SimpleSpanProcessor, BatchSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.storage import SpanStorage
from tracelite.analyzer import critical_path, error_summary, span_depth
from tracelite.graph import ServiceGraph
from tracelite.metrics import REDMetrics
from tracelite.visualizer import render_waterfall, render_span_tree
from tracelite.decorators import trace, configure_decorator_tracing
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.context import SpanContext, set_current_span, restore_span
from tracelite.middleware import TracingMiddleware, make_client_span


class TestEndToEndTracing:
    """Test the full tracing pipeline."""

    def teardown_method(self):
        """Ensure no context leaks between tests."""
        set_current_span(None)
    """Test the full tracing pipeline."""

    def test_simple_pipeline(self):
        """Create spans → export → store → analyze."""
        exporter = InMemoryExporter()
        provider = TracerProvider(
            resource=Resource(attributes={"service.name": "api"}),
            sampler=AlwaysOnSampler(),
        )
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("integration")

        # Simulate a request
        with tracer.start_span("GET /users", kind=SpanKind.SERVER) as root:
            root.set_attribute("http.method", "GET")
            with tracer.start_span("validate_token") as auth:
                time.sleep(0.001)
            with tracer.start_span("fetch_users") as fetch:
                with tracer.start_span("SELECT * FROM users") as db:
                    db.set_attribute("db.system", "postgresql")
                    time.sleep(0.002)
            with tracer.start_span("serialize") as ser:
                time.sleep(0.001)
            root.set_attribute("http.status_code", 200)

        # Verify export
        assert exporter.span_count == 5
        spans = exporter.get_spans()

        # All should share same trace_id
        trace_ids = {s.trace_id for s in spans}
        assert len(trace_ids) == 1

        # Parent-child relationships
        root_span = next(s for s in spans if s.name == "GET /users")
        db_span = next(s for s in spans if "SELECT" in s.name)
        fetch_span = next(s for s in spans if s.name == "fetch_users")
        assert db_span.parent_span_id == fetch_span.span_id
        assert fetch_span.parent_span_id == root_span.span_id

    def test_store_and_query(self):
        """Export spans, store in SQLite, query them back."""
        storage = SpanStorage(":memory:")
        exporter = InMemoryExporter()
        provider = TracerProvider(
            resource=Resource(attributes={"service.name": "api"}),
        )
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer()

        with tracer.start_span("request") as root:
            with tracer.start_span("db_query") as db:
                time.sleep(0.001)

        # Store exported spans
        storage.insert_spans(exporter.get_spans())

        # Query back
        assert storage.span_count() == 2
        assert storage.trace_count() == 1

        trace = storage.get_trace(root.trace_id)
        assert len(trace) == 2

        services = storage.get_services()
        assert services[0]["service_name"] == "api"

        storage.close()

    def test_analysis_pipeline(self):
        """Create a trace and run all analyzers."""
        exporter = InMemoryExporter()
        provider = TracerProvider(
            resource=Resource(attributes={"service.name": "api"}),
        )
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer()

        with tracer.start_span("root") as root:
            with tracer.start_span("fast") as fast:
                time.sleep(0.001)
            with tracer.start_span("slow") as slow:
                slow.set_status(StatusCode.ERROR, "timeout")
                time.sleep(0.005)

        spans = [s.to_dict() for s in exporter.get_spans()]

        # Critical path
        path = critical_path(spans)
        assert len(path) >= 2

        # Error summary
        errors = error_summary(spans)
        assert errors["total_errors"] == 1

        # Depth
        depth = span_depth(spans)
        assert depth == 2

        # Visualization
        waterfall = render_waterfall(spans)
        assert "root" in waterfall

        tree = render_span_tree(spans)
        assert "root" in tree

    def test_service_graph_from_multiservice_trace(self):
        """Build a service graph from multi-service traces."""
        exporter = InMemoryExporter()

        # API service
        api_provider = TracerProvider(
            resource=Resource(attributes={"service.name": "api"}),
        )
        api_provider.add_processor(SimpleSpanProcessor(exporter))
        api_tracer = api_provider.get_tracer()

        # DB service
        db_provider = TracerProvider(
            resource=Resource(attributes={"service.name": "db"}),
        )
        db_provider.add_processor(SimpleSpanProcessor(exporter))
        db_tracer = db_provider.get_tracer()

        # Simulate cross-service trace
        with api_tracer.start_span("GET /users", kind=SpanKind.SERVER) as api_span:
            # Simulate internal DB call (same trace) by using parent context
            parent_ctx = SpanContext(
                trace_id=api_span.trace_id,
                span_id=api_span.span_id,
                trace_flags=1,
            )
            db_span = db_tracer.create_span(
                "SELECT users",
                parent=parent_ctx,
            )
            db_span.end()
            for proc in db_provider._processors:
                proc.on_end(db_span)

        spans_dicts = [s.to_dict() for s in exporter.get_spans()]
        graph = ServiceGraph()
        graph.add_traces([spans_dicts])

        assert "api" in graph.nodes
        assert "db" in graph.nodes
        assert len(graph.edges) == 1
        assert graph.edges[0]["source"] == "api"
        assert graph.edges[0]["target"] == "db"

    def test_context_propagation_across_services(self):
        """Simulate W3C trace context propagation."""
        propagator = W3CTraceContextPropagator()

        # Service A creates a span and injects context
        exporter_a = InMemoryExporter()
        provider_a = TracerProvider(
            resource=Resource(attributes={"service.name": "service-a"}),
        )
        provider_a.add_processor(SimpleSpanProcessor(exporter_a))
        tracer_a = provider_a.get_tracer()

        with tracer_a.start_span("outgoing-request", kind=SpanKind.CLIENT) as span_a:
            ctx = SpanContext(span_a.trace_id, span_a.span_id, 1)
            headers = {}
            propagator.inject(ctx, headers)

        # Service B extracts context and creates child span
        exporter_b = InMemoryExporter()
        provider_b = TracerProvider(
            resource=Resource(attributes={"service.name": "service-b"}),
        )
        provider_b.add_processor(SimpleSpanProcessor(exporter_b))
        tracer_b = provider_b.get_tracer()

        parent_ctx = propagator.extract(headers)
        assert parent_ctx is not None

        span_b = tracer_b.create_span(
            "handle-request",
            parent=parent_ctx,
            kind=SpanKind.SERVER,
        )
        span_b.end()
        for proc in provider_b._processors:
            proc.on_end(span_b)

        # Verify same trace
        assert exporter_b.get_spans()[0].trace_id == exporter_a.get_spans()[0].trace_id
        assert exporter_b.get_spans()[0].parent_span_id == exporter_a.get_spans()[0].span_id

    def test_red_metrics(self):
        """Test RED metrics computation from stored traces."""
        storage = SpanStorage(":memory:")
        exporter = InMemoryExporter()
        provider = TracerProvider(
            resource=Resource(attributes={"service.name": "api"}),
        )
        provider.add_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer()

        # Generate some traces
        for i in range(10):
            with tracer.start_span(f"request-{i}") as span:
                if i % 3 == 0:
                    span.set_status(StatusCode.ERROR, "fail")
                time.sleep(0.001)

        storage.insert_spans(exporter.get_spans())

        red = REDMetrics(storage)
        metrics = red.compute(window_seconds=3600)
        assert metrics["total_requests"] == 10
        assert metrics["total_errors"] >= 3

        storage.close()
