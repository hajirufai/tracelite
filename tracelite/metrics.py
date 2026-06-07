"""
RED metrics computed from trace data.

RED = Rate, Errors, Duration — the three golden signals
for monitoring request-driven services.
"""

from __future__ import annotations

import statistics
import time
from typing import Optional

from tracelite.storage import SpanStorage
from tracelite.clock import format_duration


class REDMetrics:
    """
    Compute Rate, Errors, and Duration metrics from stored spans.

    Operates on the SpanStorage backend and can compute metrics
    per service, per operation, or globally.
    """

    def __init__(self, storage: SpanStorage):
        self._storage = storage

    def compute(
        self,
        service_name: Optional[str] = None,
        operation: Optional[str] = None,
        window_seconds: float = 3600.0,
    ) -> dict:
        """
        Compute RED metrics for the given time window.

        Returns:
            {
                "rate": requests per second,
                "error_rate": fraction of errors,
                "duration": {
                    "p50": ..., "p90": ..., "p95": ..., "p99": ...,
                    "min": ..., "max": ..., "mean": ...
                },
                "total_requests": int,
                "total_errors": int,
                "window_seconds": float
            }
        """
        since_ns = int((time.time() - window_seconds) * 1_000_000_000)
        traces = self._storage.get_traces(
            service_name=service_name,
            operation=operation,
            since_ns=since_ns,
            limit=10000,
        )

        # Collect all matching spans (root spans from the query)
        all_spans = []
        for trace in traces:
            for span in trace:
                svc = span.get("service_name", "unknown")
                if svc == "unknown" and "resource" in span:
                    svc = span["resource"].get("service.name", "unknown")
                op = span.get("name", "")

                matches = True
                if service_name and svc != service_name:
                    matches = False
                if operation and op != operation:
                    matches = False
                if matches:
                    all_spans.append(span)

        total = len(all_spans)
        errors = sum(1 for s in all_spans if s.get("status_code") == "ERROR")
        durations = [s.get("duration_ns", 0) for s in all_spans if s.get("duration_ns", 0) > 0]

        rate = total / window_seconds if window_seconds > 0 else 0
        error_rate = errors / total if total > 0 else 0

        duration_stats = self._compute_percentiles(durations) if durations else {
            "p50": 0, "p90": 0, "p95": 0, "p99": 0,
            "min": 0, "max": 0, "mean": 0,
        }

        return {
            "rate": round(rate, 3),
            "error_rate": round(error_rate, 4),
            "duration": duration_stats,
            "total_requests": total,
            "total_errors": errors,
            "window_seconds": window_seconds,
        }

    def compute_by_service(self, window_seconds: float = 3600.0) -> list[dict]:
        """Compute RED metrics for each service."""
        services = self._storage.get_services()
        results = []
        for svc in services:
            name = svc["service_name"]
            metrics = self.compute(service_name=name, window_seconds=window_seconds)
            metrics["service"] = name
            results.append(metrics)
        results.sort(key=lambda x: x["total_requests"], reverse=True)
        return results

    def compute_by_operation(
        self, service_name: Optional[str] = None, window_seconds: float = 3600.0
    ) -> list[dict]:
        """Compute RED metrics for each operation."""
        operations = self._storage.get_operations(service_name)
        results = []
        for op in operations:
            name = op["operation"]
            metrics = self.compute(
                service_name=service_name, operation=name,
                window_seconds=window_seconds,
            )
            metrics["operation"] = name
            results.append(metrics)
        results.sort(key=lambda x: x["total_requests"], reverse=True)
        return results

    def format_summary(self, metrics: dict) -> str:
        """Format metrics as a readable string."""
        dur = metrics["duration"]
        lines = [
            f"Rate:     {metrics['rate']:.1f} req/s ({metrics['total_requests']} total)",
            f"Errors:   {metrics['error_rate']:.1%} ({metrics['total_errors']} total)",
            f"Duration: p50={format_duration(dur['p50'])} "
            f"p90={format_duration(dur['p90'])} "
            f"p95={format_duration(dur['p95'])} "
            f"p99={format_duration(dur['p99'])}",
            f"          min={format_duration(dur['min'])} "
            f"max={format_duration(dur['max'])} "
            f"mean={format_duration(dur['mean'])}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _compute_percentiles(values: list[int]) -> dict:
        """Compute latency percentiles from a list of nanosecond durations."""
        if not values:
            return {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "mean": 0}

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        def percentile(p: float) -> int:
            k = (n - 1) * p / 100.0
            f = int(k)
            c = f + 1 if f + 1 < n else f
            d = k - f
            return int(sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f]))

        return {
            "p50": percentile(50),
            "p90": percentile(90),
            "p95": percentile(95),
            "p99": percentile(99),
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "mean": int(statistics.mean(sorted_vals)),
        }
