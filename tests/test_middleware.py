"""Tests for HTTP middleware."""

import pytest
from tracelite.middleware import TracingMiddleware, make_client_span
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import InMemoryExporter


def simple_wsgi_app(environ, start_response):
    """Minimal WSGI app for testing."""
    path = environ.get("PATH_INFO", "/")
    if path == "/error":
        start_response("500 Internal Server Error", [])
        return [b"error"]
    if path == "/exception":
        raise RuntimeError("boom")
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]


class TestTracingMiddleware:
    def setup_method(self):
        self.exporter = InMemoryExporter()
        self.app = TracingMiddleware(
            app=simple_wsgi_app,
            service_name="test-api",
            processors=[SimpleSpanProcessor(self.exporter)],
        )

    def _make_environ(self, method="GET", path="/", headers=None):
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "localhost:8080",
            "wsgi.url_scheme": "http",
        }
        if headers:
            for k, v in headers.items():
                env[f"HTTP_{k.upper().replace('-', '_')}"] = v
        return env

    def _make_start_response(self):
        self._response_status = None
        def start_response(status, headers, exc_info=None):
            self._response_status = status
        return start_response

    def test_basic_request(self):
        environ = self._make_environ("GET", "/users")
        start_response = self._make_start_response()
        result = self.app(environ, start_response)

        assert result == [b"ok"]
        assert self.exporter.span_count == 1

        span = self.exporter.get_spans()[0]
        assert span.name == "GET /users"
        assert span.attributes["http.method"] == "GET"
        assert span.attributes["http.status_code"] == 200

    def test_error_response(self):
        environ = self._make_environ("GET", "/error")
        start_response = self._make_start_response()
        self.app(environ, start_response)

        span = self.exporter.get_spans()[0]
        assert span.attributes["http.status_code"] == 500
        assert span.status.code.name == "ERROR"

    def test_exception(self):
        environ = self._make_environ("GET", "/exception")
        start_response = self._make_start_response()
        with pytest.raises(RuntimeError):
            self.app(environ, start_response)

        span = self.exporter.get_spans()[0]
        assert span.status.code.name == "ERROR"
        assert len(span.events) >= 1

    def test_trace_context_extraction(self):
        environ = self._make_environ(
            "GET", "/users",
            headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        )
        start_response = self._make_start_response()
        self.app(environ, start_response)

        span = self.exporter.get_spans()[0]
        assert span.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span.parent_span_id == "00f067aa0ba902b7"


class TestMakeClientSpan:
    def test_creates_span_and_headers(self):
        span, headers = make_client_span("GET", "http://api.example.com/users")
        assert span.name == "GET http://api.example.com/users"
        assert "traceparent" in headers
        span.end()

    def test_propagates_trace_id(self):
        span, headers = make_client_span("POST", "http://api.example.com/data")
        tp = headers["traceparent"]
        parts = tp.split("-")
        assert parts[1] == span.trace_id
        assert parts[2] == span.span_id
        span.end()
