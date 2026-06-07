"""
Span model — the fundamental unit of a distributed trace.

Each span represents one operation within a trace: an RPC call,
a database query, a function invocation. Spans form a tree via
parent_span_id references, all sharing the same trace_id.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from tracelite.clock import now_ns, monotonic_ns, format_duration, format_timestamp
from tracelite.utils import generate_trace_id, generate_span_id


class SpanKind(enum.Enum):
    """Describes the relationship between the span and its remote parent/child."""
    INTERNAL = 0
    SERVER = 1
    CLIENT = 2
    PRODUCER = 3
    CONSUMER = 4


class StatusCode(enum.Enum):
    """Status of a span: unset, ok, or error."""
    UNSET = 0
    OK = 1
    ERROR = 2


@dataclass
class SpanStatus:
    """Span completion status with optional description."""
    code: StatusCode = StatusCode.UNSET
    description: str = ""

    def __repr__(self) -> str:
        if self.description:
            return f"SpanStatus({self.code.name}: {self.description})"
        return f"SpanStatus({self.code.name})"


@dataclass
class Event:
    """A timestamped annotation within a span (e.g., log entry, exception)."""
    name: str
    timestamp_ns: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp_ns == 0:
            self.timestamp_ns = now_ns()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "timestamp": self.timestamp_ns,
            "attributes": dict(self.attributes),
        }


@dataclass
class Link:
    """A reference to a span in another trace (causal but not parent-child)."""
    trace_id: str
    span_id: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attributes": dict(self.attributes),
        }


@dataclass
class Resource:
    """Describes the entity producing telemetry (service, host, etc.)."""
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def service_name(self) -> str:
        return str(self.attributes.get("service.name", "unknown"))

    @property
    def service_version(self) -> str:
        return str(self.attributes.get("service.version", ""))

    def to_dict(self) -> dict:
        return dict(self.attributes)

    def merge(self, other: Resource) -> Resource:
        merged = dict(self.attributes)
        merged.update(other.attributes)
        return Resource(attributes=merged)


class Span:
    """
    A single operation in a distributed trace.

    Spans track timing, status, attributes, events, and links.
    They form a tree structure within a trace via parent references.
    """

    def __init__(
        self,
        name: str,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        kind: SpanKind = SpanKind.INTERNAL,
        resource: Optional[Resource] = None,
        attributes: Optional[dict[str, Any]] = None,
        start_time_ns: Optional[int] = None,
    ):
        self.name = name
        self.trace_id = trace_id or generate_trace_id()
        self.span_id = span_id or generate_span_id()
        self.parent_span_id = parent_span_id
        self.kind = kind
        self.resource = resource or Resource()
        self.status = SpanStatus()
        self.attributes: dict[str, Any] = dict(attributes) if attributes else {}
        self.events: list[Event] = []
        self.links: list[Link] = []

        self._start_time_ns = start_time_ns or now_ns()
        self._start_mono_ns = monotonic_ns()
        self._end_time_ns: Optional[int] = None
        self._ended = False

    @property
    def start_time_ns(self) -> int:
        return self._start_time_ns

    @property
    def end_time_ns(self) -> Optional[int]:
        return self._end_time_ns

    @property
    def duration_ns(self) -> int:
        """Duration in nanoseconds. Returns 0 if not ended."""
        if self._end_time_ns is None:
            return 0
        return self._end_time_ns - self._start_time_ns

    @property
    def is_ended(self) -> bool:
        return self._ended

    @property
    def is_recording(self) -> bool:
        return not self._ended

    def set_attribute(self, key: str, value: Any) -> Span:
        """Set a single attribute. No-op if span ended."""
        if not self._ended:
            self.attributes[key] = value
        return self

    def set_attributes(self, attrs: dict[str, Any]) -> Span:
        """Set multiple attributes. No-op if span ended."""
        if not self._ended:
            self.attributes.update(attrs)
        return self

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> Span:
        """Add a timestamped event to this span."""
        if not self._ended:
            self.events.append(Event(
                name=name,
                attributes=attributes or {},
            ))
        return self

    def add_link(self, trace_id: str, span_id: str,
                 attributes: Optional[dict[str, Any]] = None) -> Span:
        """Add a link to a span in another trace."""
        if not self._ended:
            self.links.append(Link(
                trace_id=trace_id,
                span_id=span_id,
                attributes=attributes or {},
            ))
        return self

    def set_status(self, code: StatusCode, description: str = "") -> Span:
        """Set the span's status. OK cannot be overwritten by UNSET."""
        if not self._ended:
            if self.status.code == StatusCode.OK and code == StatusCode.UNSET:
                return self
            self.status = SpanStatus(code=code, description=description)
        return self

    def record_exception(self, exception: BaseException,
                         attributes: Optional[dict[str, Any]] = None) -> Span:
        """Record an exception as a span event and set ERROR status."""
        attrs = {
            "exception.type": type(exception).__name__,
            "exception.message": str(exception),
        }
        if attributes:
            attrs.update(attributes)
        self.add_event("exception", attrs)
        self.set_status(StatusCode.ERROR, str(exception))
        return self

    def end(self, end_time_ns: Optional[int] = None) -> None:
        """Mark this span as ended. Records the wall-clock end time."""
        if self._ended:
            return
        self._ended = True
        if end_time_ns is not None:
            self._end_time_ns = end_time_ns
        else:
            elapsed = monotonic_ns() - self._start_mono_ns
            self._end_time_ns = self._start_time_ns + elapsed

    def to_dict(self) -> dict:
        """Serialize span to a dictionary."""
        d = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind.name,
            "status": {"code": self.status.code.name, "description": self.status.description},
            "attributes": dict(self.attributes),
            "events": [e.to_dict() for e in self.events],
            "links": [lnk.to_dict() for lnk in self.links],
            "resource": self.resource.to_dict(),
            "start_time_ns": self._start_time_ns,
            "end_time_ns": self._end_time_ns,
            "duration_ns": self.duration_ns,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Span:
        """Deserialize a span from a dictionary."""
        resource = Resource(attributes=data.get("resource", {}))
        span = cls(
            name=data["name"],
            trace_id=data["trace_id"],
            span_id=data["span_id"],
            parent_span_id=data.get("parent_span_id"),
            kind=SpanKind[data.get("kind", "INTERNAL")],
            resource=resource,
            attributes=data.get("attributes", {}),
            start_time_ns=data.get("start_time_ns"),
        )
        span._end_time_ns = data.get("end_time_ns")
        span._ended = span._end_time_ns is not None

        status_data = data.get("status", {})
        if isinstance(status_data, dict):
            code_name = status_data.get("code", "UNSET")
            span.status = SpanStatus(
                code=StatusCode[code_name],
                description=status_data.get("description", ""),
            )

        for ev in data.get("events", []):
            span.events.append(Event(
                name=ev["name"],
                timestamp_ns=ev.get("timestamp", 0),
                attributes=ev.get("attributes", {}),
            ))

        for lnk in data.get("links", []):
            span.links.append(Link(
                trace_id=lnk["trace_id"],
                span_id=lnk["span_id"],
                attributes=lnk.get("attributes", {}),
            ))

        return span

    def __repr__(self) -> str:
        dur = format_duration(self.duration_ns) if self._ended else "running"
        return (
            f"Span(name={self.name!r}, trace_id={self.trace_id[:8]}..., "
            f"span_id={self.span_id[:8]}..., duration={dur})"
        )

    def __enter__(self) -> Span:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_val is not None:
            self.record_exception(exc_val)
        self.end()
