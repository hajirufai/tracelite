"""
Span exporters — destinations for finished spans.

Exporters receive batches of spans from processors and
send them to backends: console, files, or remote collectors.
"""

from __future__ import annotations

import json
import sys
import threading
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tracelite.span import Span

from tracelite.clock import format_duration, format_timestamp


class ExportResult(Enum):
    SUCCESS = 0
    FAILURE = 1


class SpanExporter:
    """Base class for span exporters."""

    def export(self, spans: list["Span"]) -> ExportResult:
        raise NotImplementedError

    def shutdown(self) -> None:
        pass


class ConsoleExporter(SpanExporter):
    """
    Prints spans to stdout in a readable format.

    Good for development and debugging.
    """

    def __init__(self, colored: bool = True, output=None):
        self._colored = colored
        self._output = output or sys.stdout
        self._lock = threading.Lock()

    def export(self, spans: list["Span"]) -> ExportResult:
        with self._lock:
            for span in spans:
                self._print_span(span)
        return ExportResult.SUCCESS

    def _print_span(self, span: "Span") -> None:
        from tracelite.span import StatusCode

        dur = format_duration(span.duration_ns)
        status = span.status.code.name
        svc = span.resource.service_name

        if self._colored:
            if span.status.code == StatusCode.ERROR:
                color, reset = "\033[31m", "\033[0m"
            elif span.status.code == StatusCode.OK:
                color, reset = "\033[32m", "\033[0m"
            else:
                color, reset = "\033[33m", "\033[0m"
        else:
            color = reset = ""

        line = (
            f"{color}[{svc}] {span.name} "
            f"trace={span.trace_id[:8]}.. span={span.span_id[:8]}.. "
            f"parent={span.parent_span_id[:8] + '..' if span.parent_span_id else 'root'} "
            f"duration={dur} status={status}{reset}"
        )
        print(line, file=self._output)

        if span.attributes:
            attrs = " ".join(f"{k}={v}" for k, v in span.attributes.items())
            print(f"  attrs: {attrs}", file=self._output)

        for event in span.events:
            print(f"  event: {event.name} {event.attributes}", file=self._output)


class JSONFileExporter(SpanExporter):
    """
    Writes spans as newline-delimited JSON to a file.

    Each line is one span — easy to parse, grep, and tail.
    """

    def __init__(self, file_path: str):
        self._file_path = file_path
        self._lock = threading.Lock()

    def export(self, spans: list["Span"]) -> ExportResult:
        try:
            with self._lock:
                with open(self._file_path, "a") as f:
                    for span in spans:
                        json.dump(span.to_dict(), f, default=str)
                        f.write("\n")
            return ExportResult.SUCCESS
        except OSError:
            return ExportResult.FAILURE


class InMemoryExporter(SpanExporter):
    """
    Stores spans in a list for testing and inspection.

    Not for production — unbounded memory usage.
    """

    def __init__(self):
        self._spans: list["Span"] = []
        self._lock = threading.Lock()

    def export(self, spans: list["Span"]) -> ExportResult:
        with self._lock:
            self._spans.extend(spans)
        return ExportResult.SUCCESS

    def get_spans(self) -> list["Span"]:
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    @property
    def span_count(self) -> int:
        with self._lock:
            return len(self._spans)

    def find_by_name(self, name: str) -> list["Span"]:
        with self._lock:
            return [s for s in self._spans if s.name == name]

    def find_by_trace(self, trace_id: str) -> list["Span"]:
        with self._lock:
            return [s for s in self._spans if s.trace_id == trace_id]
