"""
Dashboard generation example.

Creates sample trace data and generates a self-contained
HTML dashboard with trace list, waterfall, and service map.
"""

import time
import random
from tracelite.tracer import TracerProvider
from tracelite.span import Resource, SpanKind, StatusCode
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.storage import SpanStorage
from tracelite.dashboard import save_dashboard


def main():
    storage = SpanStorage("demo_traces.db")
    exporter = InMemoryExporter()

    services = {
        "gateway": TracerProvider(resource=Resource(attributes={"service.name": "gateway"})),
        "user-api": TracerProvider(resource=Resource(attributes={"service.name": "user-api"})),
        "database": TracerProvider(resource=Resource(attributes={"service.name": "database"})),
    }
    for provider in services.values():
        provider.add_processor(SimpleSpanProcessor(exporter))

    tracers = {name: prov.get_tracer(name) for name, prov in services.items()}

    # Generate sample traces
    endpoints = ["GET /users", "POST /users", "GET /users/:id", "PUT /users/:id", "DELETE /users/:id"]

    for i in range(30):
        endpoint = random.choice(endpoints)
        has_error = random.random() < 0.15

        with tracers["gateway"].start_span(endpoint, kind=SpanKind.SERVER) as gw:
            gw.set_attribute("http.method", endpoint.split()[0])
            time.sleep(random.uniform(0.001, 0.005))

            with tracers["user-api"].start_span(f"handle_{endpoint.split()[0].lower()}", kind=SpanKind.SERVER) as api:
                time.sleep(random.uniform(0.002, 0.008))

                with tracers["database"].start_span("SQL query", kind=SpanKind.CLIENT) as db:
                    db.set_attribute("db.system", "postgresql")
                    time.sleep(random.uniform(0.005, 0.020))

                    if has_error:
                        db.set_status(StatusCode.ERROR, "connection timeout")
                        api.set_status(StatusCode.ERROR, "upstream failure")
                        gw.set_attribute("http.status_code", 500)
                    else:
                        gw.set_attribute("http.status_code", 200)

    # Store all spans
    storage.insert_spans(exporter.get_spans())

    # Generate dashboard
    output = save_dashboard(storage, "dashboard.html", title="TraceLite Demo Dashboard")
    print(f"Dashboard saved to: {output}")
    print(f"Traces: {storage.trace_count()}, Spans: {storage.span_count()}")

    storage.close()


if __name__ == "__main__":
    main()
