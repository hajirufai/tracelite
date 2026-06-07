"""
HTTP middleware for automatic request tracing.

Wraps incoming HTTP requests in SERVER spans, extracts
trace context from headers, and records HTTP metadata.
Compatible with WSGI applications.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from tracelite.span import Span, SpanKind, StatusCode, Resource
from tracelite.context import set_current_span, restore_span, SpanContext
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.processor import SpanProcessor


class TracingMiddleware:
    """
    WSGI middleware that creates a SERVER span for each request.

    Extracts W3C Trace Context from incoming headers and
    records HTTP method, path, status code, and errors.

    Usage:
        app = TracingMiddleware(
            app=my_wsgi_app,
            service_name="api-gateway",
            processors=[SimpleSpanProcessor(ConsoleExporter())],
        )
    """

    def __init__(
        self,
        app: Callable,
        service_name: str = "unknown",
        processors: Optional[list[SpanProcessor]] = None,
        propagator: Optional[W3CTraceContextPropagator] = None,
    ):
        self._app = app
        self._resource = Resource(attributes={"service.name": service_name})
        self._processors = processors or []
        self._propagator = propagator or W3CTraceContextPropagator()

    def __call__(self, environ: dict, start_response: Callable) -> Any:
        """WSGI entry point."""
        method = environ.get("REQUEST_METHOD", "UNKNOWN")
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        host = environ.get("HTTP_HOST", "")

        # Extract trace context from incoming headers
        headers = self._extract_headers(environ)
        parent_ctx = self._propagator.extract(headers)

        span = Span(
            name=f"{method} {path}",
            trace_id=parent_ctx.trace_id if parent_ctx else None,
            parent_span_id=parent_ctx.span_id if parent_ctx else None,
            kind=SpanKind.SERVER,
            resource=self._resource,
            attributes={
                "http.method": method,
                "http.url": f"{host}{path}{'?' + query if query else ''}",
                "http.target": path,
                "http.host": host,
                "http.scheme": environ.get("wsgi.url_scheme", "http"),
            },
        )

        token = set_current_span(span)
        for proc in self._processors:
            proc.on_start(span)

        status_code = [200]  # Mutable container for closure

        def traced_start_response(status: str, headers: list, exc_info=None):
            try:
                code = int(status.split(" ", 1)[0])
            except (ValueError, IndexError):
                code = 500
            status_code[0] = code
            return start_response(status, headers, exc_info)

        try:
            response = self._app(environ, traced_start_response)
            span.set_attribute("http.status_code", status_code[0])

            if status_code[0] >= 500:
                span.set_status(StatusCode.ERROR, f"HTTP {status_code[0]}")
            else:
                span.set_status(StatusCode.OK)

            return response

        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("http.status_code", 500)
            raise

        finally:
            span.end()
            for proc in self._processors:
                proc.on_end(span)
            restore_span(token)

    def _extract_headers(self, environ: dict) -> dict[str, str]:
        """Extract HTTP headers from WSGI environ dict."""
        headers = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                header_name = key[5:].lower().replace("_", "-")
                headers[header_name] = value
        return headers


def make_client_span(
    method: str,
    url: str,
    service_name: str = "http-client",
    processors: Optional[list[SpanProcessor]] = None,
) -> tuple[Span, dict[str, str]]:
    """
    Create a CLIENT span for an outgoing HTTP request.

    Returns the span and headers to inject into the request.

    Usage:
        span, headers = make_client_span("GET", "http://api.example.com/users")
        # Add headers to your HTTP request
        response = requests.get(url, headers=headers)
        span.set_attribute("http.status_code", response.status_code)
        span.end()
    """
    from tracelite.context import get_current_span

    parent = get_current_span()
    resource = Resource(attributes={"service.name": service_name})

    span = Span(
        name=f"{method} {url}",
        trace_id=parent.trace_id if parent else None,
        parent_span_id=parent.span_id if parent else None,
        kind=SpanKind.CLIENT,
        resource=resource,
        attributes={
            "http.method": method,
            "http.url": url,
        },
    )

    if processors:
        for proc in processors:
            proc.on_start(span)

    # Create headers for propagation
    propagator = W3CTraceContextPropagator()
    headers: dict[str, str] = {}
    ctx = SpanContext(
        trace_id=span.trace_id,
        span_id=span.span_id,
        trace_flags=1,
    )
    propagator.inject(ctx, headers)

    return span, headers
