"""
TraceLite — A zero-dependency distributed tracing library.

Built from scratch using only the Python standard library.
Implements W3C Trace Context, sampling strategies, batch processing,
and waterfall visualization.
"""

from tracelite.span import Span, SpanKind, StatusCode, SpanStatus, Event, Link, Resource
from tracelite.tracer import Tracer, TracerProvider
from tracelite.context import get_current_span, set_current_span
from tracelite.propagator import W3CTraceContextPropagator
from tracelite.sampler import (
    AlwaysOnSampler,
    AlwaysOffSampler,
    ProbabilisticSampler,
    RateLimitingSampler,
    ParentBasedSampler,
    SamplingResult,
    SamplingDecision,
)
from tracelite.processor import SimpleSpanProcessor, BatchSpanProcessor
from tracelite.exporter import ConsoleExporter, JSONFileExporter, InMemoryExporter
from tracelite.decorators import trace
from tracelite.middleware import TracingMiddleware
from tracelite.metrics import REDMetrics

__version__ = "1.0.0"
__all__ = [
    "Span", "SpanKind", "StatusCode", "SpanStatus", "Event", "Link", "Resource",
    "Tracer", "TracerProvider",
    "get_current_span", "set_current_span",
    "W3CTraceContextPropagator",
    "AlwaysOnSampler", "AlwaysOffSampler", "ProbabilisticSampler",
    "RateLimitingSampler", "ParentBasedSampler", "SamplingResult", "SamplingDecision",
    "SimpleSpanProcessor", "BatchSpanProcessor",
    "ConsoleExporter", "JSONFileExporter", "InMemoryExporter",
    "trace",
    "TracingMiddleware",
    "REDMetrics",
]
