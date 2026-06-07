"""
Basic tracing example — trace a simulated web request.

Shows: TracerProvider setup, span nesting, attributes, events,
context propagation, and console output.
"""

import time
from tracelite.tracer import TracerProvider
from tracelite.span import Resource, SpanKind, StatusCode
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import ConsoleExporter
from tracelite.visualizer import render_waterfall, render_span_tree


def main():
    # 1. Set up the tracing pipeline
    provider = TracerProvider(
        resource=Resource(attributes={
            "service.name": "user-api",
            "service.version": "1.2.0",
            "deployment.environment": "production",
        }),
    )
    provider.add_processor(SimpleSpanProcessor(ConsoleExporter(colored=True)))
    tracer = provider.get_tracer("basic-example")

    # 2. Trace a request
    with tracer.start_span("GET /users", kind=SpanKind.SERVER) as root:
        root.set_attribute("http.method", "GET")
        root.set_attribute("http.url", "/users?limit=50")

        # Auth check
        with tracer.start_span("validate_token") as auth:
            auth.set_attribute("auth.method", "JWT")
            time.sleep(0.005)
            auth.add_event("token_validated", {"user_id": "usr_42"})

        # Database query
        with tracer.start_span("fetch_users", kind=SpanKind.CLIENT) as fetch:
            fetch.set_attribute("db.system", "postgresql")
            fetch.set_attribute("db.statement", "SELECT * FROM users LIMIT 50")

            with tracer.start_span("connection_pool_acquire") as pool:
                time.sleep(0.002)

            with tracer.start_span("execute_query") as query:
                query.set_attribute("db.rows_returned", 50)
                time.sleep(0.015)

        # Serialize response
        with tracer.start_span("serialize_response") as ser:
            ser.set_attribute("response.format", "json")
            ser.set_attribute("response.size_bytes", 4096)
            time.sleep(0.003)

        root.set_attribute("http.status_code", 200)
        root.set_status(StatusCode.OK)

    # 3. Render visualizations
    print("\n" + "=" * 70)
    print("WATERFALL VIEW")
    print("=" * 70)
    spans = [s.to_dict() for s in
             provider._processors[0]._exporter._exported if hasattr(provider._processors[0]._exporter, '_exported')]

    # Use the InMemoryExporter for visualization
    from tracelite.exporter import InMemoryExporter

    # Re-run with in-memory export
    mem_exporter = InMemoryExporter()
    provider2 = TracerProvider(
        resource=Resource(attributes={"service.name": "user-api"}),
    )
    provider2.add_processor(SimpleSpanProcessor(mem_exporter))
    tracer2 = provider2.get_tracer()

    with tracer2.start_span("GET /users", kind=SpanKind.SERVER) as root:
        with tracer2.start_span("validate_token") as auth:
            time.sleep(0.005)
        with tracer2.start_span("fetch_users") as fetch:
            with tracer2.start_span("connection_pool") as pool:
                time.sleep(0.002)
            with tracer2.start_span("execute_query") as query:
                time.sleep(0.015)
        with tracer2.start_span("serialize") as ser:
            time.sleep(0.003)

    spans = [s.to_dict() for s in mem_exporter.get_spans()]
    print(render_waterfall(spans))
    print()
    print(render_span_tree(spans))


if __name__ == "__main__":
    main()
