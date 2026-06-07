"""
Tracer — the main entry point for creating spans.

A Tracer belongs to a TracerProvider and creates spans that
are automatically linked via context propagation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional, Any, Generator, TYPE_CHECKING

from tracelite.span import Span, SpanKind, Resource
from tracelite.context import (
    get_current_span, set_current_span, restore_span, SpanContext
)
from tracelite.sampler import Sampler, AlwaysOnSampler, SamplingDecision
from tracelite.processor import SpanProcessor

if TYPE_CHECKING:
    pass


class Tracer:
    """
    Creates and manages spans for a single instrumentation scope.

    Spans are automatically nested via context: starting a span
    while another is active makes the new span a child.
    """

    def __init__(
        self,
        name: str,
        resource: Resource,
        sampler: Sampler,
        processors: list[SpanProcessor],
    ):
        self._name = name
        self._resource = resource
        self._sampler = sampler
        self._processors = processors

    @property
    def name(self) -> str:
        return self._name

    @contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[dict[str, Any]] = None,
        parent: Optional[SpanContext] = None,
    ) -> Generator[Span, None, None]:
        """
        Start a new span as a context manager.

        The span becomes the active span in context. When the
        block exits, the span is ended and sent to processors.

        Usage:
            with tracer.start_span("my-operation") as span:
                span.set_attribute("key", "value")
                # ... do work ...
        """
        # Determine parent
        parent_trace_id = None
        parent_span_id = None

        if parent is not None:
            parent_trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            current = get_current_span()
            if current is not None:
                parent_trace_id = current.trace_id
                parent_span_id = current.span_id

        trace_id = parent_trace_id or None  # Will be generated if None

        # Sampling decision
        parent_ctx = None
        if parent is not None:
            parent_ctx = parent
        elif parent_span_id is not None:
            current = get_current_span()
            if current is not None:
                parent_ctx = SpanContext(
                    trace_id=current.trace_id,
                    span_id=current.span_id,
                    trace_flags=1,
                )

        span = Span(
            name=name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            kind=kind,
            resource=self._resource,
            attributes=attributes,
        )

        result = self._sampler.should_sample(
            span.trace_id, name, parent_ctx, attributes
        )

        if result.decision == SamplingDecision.DROP:
            # Return a no-op span that won't be exported
            yield span
            return

        if result.attributes:
            span.set_attributes(result.attributes)

        # Set as current span
        token = set_current_span(span)

        for proc in self._processors:
            proc.on_start(span)

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            for proc in self._processors:
                proc.on_end(span)
            restore_span(token)

    def create_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[dict[str, Any]] = None,
        parent: Optional[SpanContext] = None,
    ) -> Span:
        """
        Create a span without context management.

        Caller is responsible for ending the span and managing context.
        Prefer start_span() for most use cases.
        """
        parent_trace_id = None
        parent_span_id = None

        if parent is not None:
            parent_trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            current = get_current_span()
            if current is not None:
                parent_trace_id = current.trace_id
                parent_span_id = current.span_id

        span = Span(
            name=name,
            trace_id=parent_trace_id,
            parent_span_id=parent_span_id,
            kind=kind,
            resource=self._resource,
            attributes=attributes,
        )
        return span


class TracerProvider:
    """
    Central factory for creating Tracers.

    Holds configuration shared across all tracers:
    resource identity, sampling strategy, and processors.
    """

    def __init__(
        self,
        resource: Optional[Resource] = None,
        sampler: Optional[Sampler] = None,
    ):
        self._resource = resource or Resource(attributes={"service.name": "unknown"})
        self._sampler = sampler or AlwaysOnSampler()
        self._processors: list[SpanProcessor] = []
        self._shutdown = False

    def add_processor(self, processor: SpanProcessor) -> None:
        """Register a span processor."""
        self._processors.append(processor)

    def get_tracer(self, name: str = "default") -> Tracer:
        """Create a Tracer for the given instrumentation scope."""
        return Tracer(
            name=name,
            resource=self._resource,
            sampler=self._sampler,
            processors=list(self._processors),
        )

    def shutdown(self) -> None:
        """Shut down all processors."""
        if self._shutdown:
            return
        self._shutdown = True
        for proc in self._processors:
            proc.shutdown()

    def force_flush(self, timeout_ms: int = 30000) -> bool:
        """Force flush all processors."""
        success = True
        for proc in self._processors:
            if not proc.force_flush(timeout_ms):
                success = False
        return success

    @property
    def resource(self) -> Resource:
        return self._resource

    @property
    def sampler(self) -> Sampler:
        return self._sampler
