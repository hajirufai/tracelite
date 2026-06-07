"""
W3C Trace Context propagation.

Implements the W3C Trace Context specification for propagating
trace identity across service boundaries via HTTP headers.

Header format:
  traceparent: {version}-{trace_id}-{span_id}-{trace_flags}
  tracestate:  vendor1=value1,vendor2=value2

Reference: https://www.w3.org/TR/trace-context/
"""

from __future__ import annotations

import re
from typing import Optional

from tracelite.context import SpanContext

_TRACEPARENT_HEADER = "traceparent"
_TRACESTATE_HEADER = "tracestate"
_VERSION = "00"

_TRACEPARENT_RE = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)

_TRACESTATE_ENTRY_RE = re.compile(
    r"^([a-z][a-z0-9_\-*/]{0,255})=([^\s,]{1,256})$"
)


class W3CTraceContextPropagator:
    """
    Injects and extracts trace context using W3C traceparent/tracestate headers.
    """

    def inject(self, span_context: SpanContext, carrier: dict[str, str]) -> None:
        """
        Inject trace context into a carrier (dict of HTTP headers).

        Sets traceparent and optionally tracestate headers.
        """
        if not span_context.is_valid:
            return

        flags = f"{span_context.trace_flags:02x}"
        traceparent = f"{_VERSION}-{span_context.trace_id}-{span_context.span_id}-{flags}"
        carrier[_TRACEPARENT_HEADER] = traceparent

        if span_context.trace_state:
            entries = [f"{k}={v}" for k, v in span_context.trace_state.items()]
            carrier[_TRACESTATE_HEADER] = ",".join(entries)

    def extract(self, carrier: dict[str, str]) -> Optional[SpanContext]:
        """
        Extract trace context from a carrier (dict of HTTP headers).

        Returns None if no valid traceparent is found.
        """
        traceparent = carrier.get(_TRACEPARENT_HEADER) or carrier.get(
            _TRACEPARENT_HEADER.title()
        )
        if not traceparent:
            return None

        match = _TRACEPARENT_RE.match(traceparent.strip().lower())
        if not match:
            return None

        version, trace_id, span_id, flags_hex = match.groups()

        # Version 255 (ff) is invalid
        if version == "ff":
            return None

        trace_flags = int(flags_hex, 16)

        # Parse tracestate
        trace_state = {}
        tracestate_raw = carrier.get(_TRACESTATE_HEADER) or carrier.get(
            _TRACESTATE_HEADER.title()
        )
        if tracestate_raw:
            trace_state = self._parse_tracestate(tracestate_raw)

        ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=trace_flags,
            trace_state=trace_state,
            is_remote=True,
        )

        return ctx if ctx.is_valid else None

    def _parse_tracestate(self, raw: str) -> dict[str, str]:
        """Parse tracestate header into a dict."""
        result = {}
        entries = raw.split(",")
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            match = _TRACESTATE_ENTRY_RE.match(entry)
            if match:
                result[match.group(1)] = match.group(2)
        return result
