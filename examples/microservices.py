"""
Multi-service tracing example — W3C Trace Context propagation.

Simulates three services (gateway, user-service, database)
communicating via HTTP, with trace context flowing through headers.
"""

import time
from tracelite.tracer import TracerProvider
from tracelite.span import Resource, SpanKind, StatusCode
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.context import SpanContext
from tracelite.visualizer import render_waterfall, render_span_tree
from tracelite.graph import ServiceGraph
from tracelite.analyzer import critical_path, error_summary


# Shared propagator
propagator = W3CTraceContextPropagator()

# Shared exporter to collect all spans
all_spans = InMemoryExporter()


def make_provider(service_name: str) -> tuple:
    provider = TracerProvider(
        resource=Resource(attributes={"service.name": service_name}),
    )
    provider.add_processor(SimpleSpanProcessor(all_spans))
    return provider, provider.get_tracer(service_name)


def database_service(headers: dict):
    """Simulates a database service handling a query."""
    _, tracer = make_provider("database")

    parent = propagator.extract(headers)
    with tracer.start_span("SELECT users", kind=SpanKind.SERVER,
                           parent=parent) as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "SELECT * FROM users WHERE active = true")
        time.sleep(0.012)
        span.set_attribute("db.rows_returned", 142)
        span.set_status(StatusCode.OK)


def user_service(headers: dict):
    """Simulates a user service handling a request."""
    _, tracer = make_provider("user-service")

    parent = propagator.extract(headers)
    with tracer.start_span("GET /internal/users", kind=SpanKind.SERVER,
                           parent=parent) as span:
        span.set_attribute("http.method", "GET")

        # Validate cache
        with tracer.start_span("check_cache") as cache:
            cache.set_attribute("cache.hit", False)
            time.sleep(0.002)

        # Call database
        with tracer.start_span("db_query", kind=SpanKind.CLIENT) as client:
            db_headers = {}
            ctx = SpanContext(client.trace_id, client.span_id, 1)
            propagator.inject(ctx, db_headers)
            database_service(db_headers)

        span.set_attribute("http.status_code", 200)


def gateway_service():
    """Simulates an API gateway handling an external request."""
    _, tracer = make_provider("gateway")

    with tracer.start_span("GET /api/users", kind=SpanKind.SERVER) as span:
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.url", "https://api.example.com/users")

        # Auth middleware
        with tracer.start_span("auth_middleware") as auth:
            auth.set_attribute("auth.method", "API-Key")
            time.sleep(0.003)
            auth.add_event("authenticated", {"client_id": "app_123"})

        # Rate limiting
        with tracer.start_span("rate_limiter") as rl:
            rl.set_attribute("rate_limit.remaining", 95)
            time.sleep(0.001)

        # Forward to user service
        with tracer.start_span("call_user_service", kind=SpanKind.CLIENT) as client:
            headers = {}
            ctx = SpanContext(client.trace_id, client.span_id, 1)
            propagator.inject(ctx, headers)
            user_service(headers)

        span.set_attribute("http.status_code", 200)
        span.set_status(StatusCode.OK)


def main():
    # Run the simulated request
    print("Simulating multi-service request flow...\n")
    gateway_service()

    # Visualize
    spans = [s.to_dict() for s in all_spans.get_spans()]

    print("=" * 70)
    print("WATERFALL DIAGRAM")
    print("=" * 70)
    print(render_waterfall(spans))
    print()

    print("=" * 70)
    print("SPAN TREE")
    print("=" * 70)
    print(render_span_tree(spans))
    print()

    # Service graph
    print("=" * 70)
    print("SERVICE DEPENDENCY GRAPH")
    print("=" * 70)
    graph = ServiceGraph()
    graph.add_traces([spans])
    print(graph.to_ascii())
    print()
    print("DOT format:")
    print(graph.to_dot())

    # Critical path
    print("\n" + "=" * 70)
    print("CRITICAL PATH")
    print("=" * 70)
    path = critical_path(spans)
    for i, s in enumerate(path):
        svc = s.get("service_name", s.get("resource", {}).get("service.name", "?"))
        print(f"  {i+1}. [{svc}] {s['name']}")


if __name__ == "__main__":
    main()
