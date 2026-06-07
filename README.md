# TraceLite

A distributed tracing system built entirely from scratch in Python — zero external dependencies.

TraceLite implements the core concepts of distributed tracing (spans, traces, context propagation, sampling, exporting) using only the Python standard library. It follows the [W3C Trace Context](https://www.w3.org/TR/trace-context/) specification for cross-service propagation and draws architectural inspiration from OpenTelemetry.

## Why TraceLite?

Modern observability stacks (Jaeger, Zipkin, OpenTelemetry) are powerful but opaque. TraceLite strips distributed tracing down to its fundamentals — every algorithm is visible, every data structure is transparent. Use it to:

- **Learn** how distributed tracing actually works under the hood
- **Trace** Python applications with zero dependency overhead
- **Teach** observability concepts with readable, well-tested code
- **Prototype** tracing pipelines before committing to a full framework

## Features

| Component | What it does |
|---|---|
| **Spans & Traces** | Full span lifecycle: attributes, events, links, status codes, parent-child nesting |
| **Context Propagation** | `contextvars`-based automatic parent-child linking across call stacks |
| **W3C Trace Context** | `traceparent` / `tracestate` header parsing and injection (RFC compliant) |
| **Sampling** | AlwaysOn, AlwaysOff, Probabilistic (deterministic), RateLimiting (token bucket), ParentBased |
| **Processing** | SimpleSpanProcessor (sync) and BatchSpanProcessor (background thread + queue) |
| **Exporters** | Console (colored), JSON file, in-memory (testing) |
| **SQLite Storage** | WAL-mode storage with indexes, batch insert, query filters, retention |
| **Query Builder** | Fluent API for filtering traces by service, operation, duration, error, time range |
| **Analysis** | Critical path detection, latency breakdown, gap analysis, error correlation |
| **Service Graph** | Dependency graph with edge metrics, DOT export, ASCII rendering, topological sort |
| **RED Metrics** | Rate, Errors, Duration with percentile computation (p50/p90/p95/p99) |
| **Decorators** | `@trace` decorator with argument recording and automatic nesting |
| **WSGI Middleware** | Drop-in middleware for HTTP request tracing |
| **HTTP Collector** | Standalone server that receives spans via POST and provides REST query endpoints |
| **Visualization** | ASCII waterfall diagrams and span trees for terminal output |
| **HTML Dashboard** | Self-contained dashboard with trace list, waterfall view, and service map |

## Quick Start

```python
from tracelite.tracer import TracerProvider
from tracelite.span import Resource, SpanKind
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import ConsoleExporter

# Set up
provider = TracerProvider(
    resource=Resource(attributes={"service.name": "my-api"})
)
provider.add_processor(SimpleSpanProcessor(ConsoleExporter(colored=True)))
tracer = provider.get_tracer("my-app")

# Trace a request
with tracer.start_span("GET /users", kind=SpanKind.SERVER) as span:
    span.set_attribute("http.method", "GET")

    with tracer.start_span("fetch_from_db") as db_span:
        db_span.set_attribute("db.system", "postgresql")
        # ... your database call ...

    span.set_attribute("http.status_code", 200)
```

Output:
```
[user-api] GET /users  SERVER  245.3ms  OK
  ├ http.method=GET
  ├ http.status_code=200
  └ events: []
  [user-api] fetch_from_db  INTERNAL  89.1ms  OK
    ├ db.system=postgresql
```

## Decorator-Based Tracing

```python
from tracelite.decorators import trace, configure_decorator_tracing
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import ConsoleExporter
from tracelite.span import Resource

configure_decorator_tracing(
    processors=[SimpleSpanProcessor(ConsoleExporter())],
    resource=Resource(attributes={"service.name": "order-service"}),
)

@trace(record_args=True)
def process_order(order_id: str, items: list):
    validate_inventory(items)
    charge_payment(order_id)

@trace
def validate_inventory(items):
    for item in items:
        check_stock(item)

@trace
def check_stock(item):
    pass  # your logic

@trace(attributes={"payment.provider": "stripe"})
def charge_payment(order_id):
    pass  # your logic
```

## Cross-Service Propagation

```python
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.context import SpanContext

propagator = W3CTraceContextPropagator()

# Service A: inject context into outgoing headers
with tracer.start_span("call-service-b", kind=SpanKind.CLIENT) as span:
    headers = {}
    ctx = SpanContext(span.trace_id, span.span_id, trace_flags=1)
    propagator.inject(ctx, headers)
    # headers now contains: {"traceparent": "00-{trace_id}-{span_id}-01"}
    # Pass headers to your HTTP client

# Service B: extract context from incoming headers
parent = propagator.extract(incoming_headers)
with tracer.start_span("handle-request", parent=parent, kind=SpanKind.SERVER) as span:
    pass  # Same trace, linked as child
```

## WSGI Middleware

```python
from tracelite.middleware import TracingMiddleware

app = TracingMiddleware(
    app=your_wsgi_app,
    service_name="api-gateway",
    processors=[SimpleSpanProcessor(ConsoleExporter())],
)
# Every request is now automatically traced
```

## Storage & Querying

```python
from tracelite.storage import SpanStorage
from tracelite.query import TraceQuery

storage = SpanStorage("traces.db")
storage.insert_spans(exported_spans)

# Query builder
query = (TraceQuery()
    .service("api-gateway")
    .min_duration_ms(100)
    .errors_only()
    .last_hours(1)
    .limit(20))

traces = storage.get_traces(**query.build())
```

## Analysis

```python
from tracelite.analyzer import critical_path, latency_breakdown, find_gaps, error_summary
from tracelite.graph import ServiceGraph
from tracelite.metrics import REDMetrics

# Critical path — the chain of spans determining end-to-end latency
path = critical_path(trace_spans)

# Latency breakdown — where time is spent
breakdown = latency_breakdown(trace_spans)

# Service dependency graph
graph = ServiceGraph()
graph.add_traces(all_traces)
print(graph.to_ascii())
print(graph.to_dot())  # For Graphviz

# RED metrics (Rate, Errors, Duration)
red = REDMetrics(storage)
metrics = red.compute_by_service(window_seconds=3600)
```

## Visualization

```python
from tracelite.visualizer import render_waterfall, render_span_tree

# ASCII waterfall (great for CI logs)
print(render_waterfall(spans))

# Span tree
print(render_span_tree(spans))
```

```
● GET /users (245ms)
├── ● validate_token (12ms)
├── ● fetch_users (198ms)
│   ├── ● connection_pool (3ms)
│   └── ● execute_query (89ms)
└── ● serialize (28ms)
```

## HTML Dashboard

```python
from tracelite.dashboard import save_dashboard

save_dashboard(storage, "dashboard.html", title="My Traces")
# Open dashboard.html in a browser — fully self-contained, no server needed
```

## Architecture

```
┌─────────────┐    ┌───────────────┐    ┌────────────┐
│   Tracer     │───▶│  Processor    │───▶│  Exporter   │
│  (creates    │    │  (batches &   │    │  (console,  │
│   spans)     │    │   forwards)   │    │   file, mem)│
└──────┬───────┘    └───────────────┘    └──────┬──────┘
       │                                        │
       │ context propagation                    ▼
       │                                ┌────────────┐
┌──────┴───────┐                        │  Storage    │
│  Sampler     │                        │  (SQLite)   │
│  (decides    │                        └──────┬──────┘
│   record/    │                               │
│   drop)      │                        ┌──────┴──────┐
└──────────────┘                        │  Analysis   │
                                        │  Metrics    │
                                        │  Dashboard  │
                                        └─────────────┘
```

## Project Structure

```
tracelite/
├── tracelite/
│   ├── span.py          # Span, Resource, Event, Link, StatusCode
│   ├── context.py       # contextvars propagation, SpanContext
│   ├── propagator.py    # W3C Trace Context (traceparent/tracestate)
│   ├── sampler.py       # Sampling strategies
│   ├── processor.py     # Simple and Batch span processors
│   ├── exporter.py      # Console, JSON, InMemory exporters
│   ├── tracer.py        # Tracer and TracerProvider
│   ├── storage.py       # SQLite backend
│   ├── query.py         # Fluent query builder
│   ├── analyzer.py      # Critical path, latency, gaps, errors
│   ├── graph.py         # Service dependency graph
│   ├── metrics.py       # RED metrics (Rate/Errors/Duration)
│   ├── decorators.py    # @trace decorator
│   ├── middleware.py     # WSGI middleware
│   ├── collector.py     # HTTP collector server
│   ├── visualizer.py    # ASCII waterfall and span tree
│   ├── dashboard.py     # HTML dashboard generator
│   ├── clock.py         # Monotonic + wall clock utilities
│   └── utils.py         # ID generation and validation
├── tests/               # 193 tests across 16 modules
├── examples/            # 4 runnable examples
├── docs/                # GitHub Pages landing page
└── pyproject.toml
```

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Running Examples

```bash
python examples/basic_tracing.py
python examples/microservices.py
python examples/decorator_tracing.py
python examples/dashboard_demo.py
```

## License

MIT
