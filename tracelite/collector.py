"""
HTTP collector server for receiving and storing spans.

Receives span batches via HTTP POST and stores them in the
SQLite backend. Provides query endpoints for retrieving traces.
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from tracelite.storage import SpanStorage
from tracelite.span import Span
from tracelite.metrics import REDMetrics


class CollectorHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the trace collector."""

    storage: SpanStorage  # Set by the server

    def do_POST(self) -> None:
        if self.path == "/v1/traces":
            self._handle_ingest()
        else:
            self._respond(404, {"error": "not found"})

    def do_GET(self) -> None:
        if self.path == "/v1/services":
            self._handle_services()
        elif self.path.startswith("/v1/traces/"):
            trace_id = self.path.split("/v1/traces/", 1)[1].strip("/")
            self._handle_get_trace(trace_id)
        elif self.path == "/v1/traces":
            self._handle_list_traces()
        elif self.path == "/v1/metrics":
            self._handle_metrics()
        elif self.path == "/v1/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def _handle_ingest(self) -> None:
        """Receive and store a batch of spans."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            spans_data = data if isinstance(data, list) else data.get("spans", [])
            spans = [Span.from_dict(sd) for sd in spans_data]
            count = self.storage.insert_spans(spans)
            self._respond(200, {"accepted": count})
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self._respond(400, {"error": str(e)})

    def _handle_get_trace(self, trace_id: str) -> None:
        """Get all spans for a specific trace."""
        spans = self.storage.get_trace(trace_id)
        if not spans:
            self._respond(404, {"error": "trace not found"})
            return
        self._respond(200, {"trace_id": trace_id, "spans": spans})

    def _handle_list_traces(self) -> None:
        """List recent traces."""
        traces = self.storage.get_traces(limit=50)
        result = []
        for trace_spans in traces:
            if trace_spans:
                root = trace_spans[0]
                result.append({
                    "trace_id": root["trace_id"],
                    "root_operation": root["name"],
                    "service": root.get("service_name", "unknown"),
                    "duration_ns": root.get("duration_ns", 0),
                    "span_count": len(trace_spans),
                    "status": root.get("status_code", "UNSET"),
                    "start_time_ns": root.get("start_time_ns", 0),
                })
        self._respond(200, {"traces": result})

    def _handle_services(self) -> None:
        """List discovered services."""
        services = self.storage.get_services()
        self._respond(200, {"services": services})

    def _handle_metrics(self) -> None:
        """Return RED metrics."""
        red = REDMetrics(self.storage)
        metrics = red.compute_by_service()
        self._respond(200, {"metrics": metrics})

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode())

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass


class TraceCollector:
    """
    Standalone trace collector server.

    Runs an HTTP server that receives spans and stores them
    in a SQLite database. Provides REST endpoints for querying.

    Usage:
        collector = TraceCollector(port=4318, db_path="traces.db")
        collector.start()  # Non-blocking
        # ... send spans to http://localhost:4318/v1/traces
        collector.stop()
    """

    def __init__(
        self,
        port: int = 4318,
        host: str = "127.0.0.1",
        db_path: str = ":memory:",
    ):
        self._port = port
        self._host = host
        self._storage = SpanStorage(db_path=db_path)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Wire storage into handler
        CollectorHandler.storage = self._storage

    @property
    def storage(self) -> SpanStorage:
        return self._storage

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def start(self) -> None:
        """Start the collector in a background thread."""
        self._server = HTTPServer((self._host, self._port), CollectorHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="tracelite-collector",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the collector server."""
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._storage.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
