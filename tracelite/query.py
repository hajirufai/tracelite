"""
Fluent trace query builder.

Provides a clean API for constructing trace queries
against the storage backend.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from tracelite.storage import SpanStorage


class TraceQuery:
    """
    Fluent builder for querying traces.

    Usage:
        results = (TraceQuery(storage)
            .service("api-gateway")
            .since(timedelta(hours=1))
            .min_duration(timedelta(milliseconds=100))
            .has_error()
            .limit(20)
            .execute())
    """

    def __init__(self, storage: SpanStorage):
        self._storage = storage
        self._service: Optional[str] = None
        self._operation: Optional[str] = None
        self._min_duration_ns: Optional[int] = None
        self._error_only: bool = False
        self._since_ns: Optional[int] = None
        self._until_ns: Optional[int] = None
        self._limit: int = 100

    def service(self, name: str) -> TraceQuery:
        """Filter by service name."""
        self._service = name
        return self

    def operation(self, name: str) -> TraceQuery:
        """Filter by operation name."""
        self._operation = name
        return self

    def min_duration(self, duration: timedelta) -> TraceQuery:
        """Only traces with root span >= this duration."""
        self._min_duration_ns = int(duration.total_seconds() * 1_000_000_000)
        return self

    def has_error(self) -> TraceQuery:
        """Only traces with ERROR status."""
        self._error_only = True
        return self

    def since(self, ago: timedelta) -> TraceQuery:
        """Traces started within the last `ago` duration."""
        self._since_ns = int((time.time() - ago.total_seconds()) * 1_000_000_000)
        return self

    def until(self, ago: timedelta) -> TraceQuery:
        """Traces started before `ago` duration from now."""
        self._until_ns = int((time.time() - ago.total_seconds()) * 1_000_000_000)
        return self

    def time_range(self, start_ns: int, end_ns: int) -> TraceQuery:
        """Absolute time range in nanoseconds."""
        self._since_ns = start_ns
        self._until_ns = end_ns
        return self

    def limit(self, n: int) -> TraceQuery:
        """Maximum number of traces to return."""
        self._limit = n
        return self

    def execute(self) -> list[list[dict]]:
        """Run the query and return matching traces."""
        return self._storage.get_traces(
            service_name=self._service,
            operation=self._operation,
            min_duration_ns=self._min_duration_ns,
            error_only=self._error_only,
            since_ns=self._since_ns,
            until_ns=self._until_ns,
            limit=self._limit,
        )

    def count(self) -> int:
        """Count matching traces without fetching all data."""
        traces = self.execute()
        return len(traces)
