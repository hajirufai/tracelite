"""
Trace analysis — critical path, latency breakdown, error correlation.

Operates on a list of span dicts (a complete trace) to extract
performance insights.
"""

from __future__ import annotations

from typing import Optional
from tracelite.clock import format_duration


def _get_status_code(span: dict) -> str:
    """Extract status code from a span dict, handling both storage and to_dict formats."""
    # Storage format: {"status_code": "ERROR"}
    if "status_code" in span:
        return span["status_code"]
    # to_dict format: {"status": {"code": "ERROR", ...}}
    status = span.get("status")
    if isinstance(status, dict):
        return status.get("code", "UNSET")
    return "UNSET"


def _get_service_name(span: dict) -> str:
    """Extract service name from a span dict."""
    svc = span.get("service_name", "unknown")
    if svc == "unknown" and "resource" in span:
        res = span["resource"]
        if isinstance(res, dict):
            svc = res.get("service.name", "unknown")
            if svc == "unknown":
                attrs = res.get("attributes", {})
                if isinstance(attrs, dict):
                    svc = attrs.get("service.name", "unknown")
    return svc


def critical_path(spans: list[dict]) -> list[dict]:
    """
    Find the critical path — the longest sequential chain of spans.

    The critical path determines the end-to-end latency:
    it's the chain of spans where any slowdown would increase
    the total trace duration.

    Returns the ordered list of spans on the critical path.
    """
    if not spans:
        return []

    # Build a tree: parent_span_id -> children
    children_map: dict[Optional[str], list[dict]] = {}
    span_map: dict[str, dict] = {}
    for s in spans:
        sid = s["span_id"]
        pid = s.get("parent_span_id")
        span_map[sid] = s
        children_map.setdefault(pid, []).append(s)

    # Find root span(s) — those with no parent or parent not in this trace
    roots = children_map.get(None, [])
    if not roots:
        # Try finding spans whose parent isn't in this trace
        all_ids = set(span_map.keys())
        roots = [s for s in spans if s.get("parent_span_id") not in all_ids]

    if not roots:
        return [spans[0]]

    # DFS to find the longest path by total duration
    def _find_longest(span: dict) -> list[dict]:
        sid = span["span_id"]
        kids = children_map.get(sid, [])
        if not kids:
            return [span]

        longest_child_path: list[dict] = []
        for child in kids:
            path = _find_longest(child)
            child_dur = sum(s.get("duration_ns", 0) for s in path)
            best_dur = sum(s.get("duration_ns", 0) for s in longest_child_path)
            if child_dur > best_dur:
                longest_child_path = path

        return [span] + longest_child_path

    # Try each root and return the longest overall path
    best_path: list[dict] = []
    best_total = 0
    for root in roots:
        path = _find_longest(root)
        total = sum(s.get("duration_ns", 0) for s in path)
        if total > best_total:
            best_path = path
            best_total = total

    return best_path


def latency_breakdown(spans: list[dict]) -> list[dict]:
    """
    Break down latency by service and operation.

    Returns a sorted list of:
    [{"service": str, "operation": str, "total_ns": int,
      "count": int, "avg_ns": float, "pct": float}]
    """
    if not spans:
        return []

    total_root_ns = 0
    roots = [s for s in spans if s.get("parent_span_id") is None]
    if roots:
        total_root_ns = max(s.get("duration_ns", 0) for s in roots)

    buckets: dict[tuple[str, str], list[int]] = {}
    for s in spans:
        svc = _get_service_name(s)
        op = s.get("name", "unknown")
        key = (svc, op)
        dur = s.get("duration_ns", 0)
        buckets.setdefault(key, []).append(dur)

    result = []
    for (svc, op), durations in buckets.items():
        total = sum(durations)
        count = len(durations)
        pct = (total / total_root_ns * 100) if total_root_ns > 0 else 0.0
        result.append({
            "service": svc,
            "operation": op,
            "total_ns": total,
            "count": count,
            "avg_ns": total / count if count > 0 else 0,
            "pct": round(pct, 1),
        })

    result.sort(key=lambda x: x["total_ns"], reverse=True)
    return result


def find_gaps(spans: list[dict]) -> list[dict]:
    """
    Find idle gaps between spans (network latency, queueing, etc.).

    A gap is the time between a parent span starting and its first
    child starting, or between consecutive children.
    """
    if not spans:
        return []

    children_map: dict[Optional[str], list[dict]] = {}
    for s in spans:
        pid = s.get("parent_span_id")
        children_map.setdefault(pid, []).append(s)

    gaps = []
    for parent_id, kids in children_map.items():
        if parent_id is None:
            continue

        # Find the parent span
        parent = None
        for s in spans:
            if s["span_id"] == parent_id:
                parent = s
                break
        if parent is None:
            continue

        sorted_kids = sorted(kids, key=lambda s: s.get("start_time_ns", 0))

        # Gap between parent start and first child start
        if sorted_kids:
            first_start = sorted_kids[0].get("start_time_ns", 0)
            parent_start = parent.get("start_time_ns", 0)
            gap_ns = first_start - parent_start
            if gap_ns > 0:
                gaps.append({
                    "type": "pre_child",
                    "parent": parent.get("name", "unknown"),
                    "child": sorted_kids[0].get("name", "unknown"),
                    "gap_ns": gap_ns,
                    "gap_formatted": format_duration(gap_ns),
                })

        # Gaps between consecutive children
        for i in range(len(sorted_kids) - 1):
            end_ns = sorted_kids[i].get("end_time_ns") or sorted_kids[i].get("start_time_ns", 0)
            next_start = sorted_kids[i + 1].get("start_time_ns", 0)
            gap_ns = next_start - end_ns
            if gap_ns > 0:
                gaps.append({
                    "type": "between_children",
                    "after": sorted_kids[i].get("name", "unknown"),
                    "before": sorted_kids[i + 1].get("name", "unknown"),
                    "gap_ns": gap_ns,
                    "gap_formatted": format_duration(gap_ns),
                })

    gaps.sort(key=lambda g: g["gap_ns"], reverse=True)
    return gaps


def error_summary(spans: list[dict]) -> dict:
    """
    Summarize errors in a trace.

    Returns counts by service, operation, and error type.
    """
    errors_by_service: dict[str, int] = {}
    errors_by_operation: dict[str, int] = {}
    error_types: dict[str, int] = {}
    total_errors = 0

    for s in spans:
        if _get_status_code(s) == "ERROR":
            total_errors += 1
            svc = _get_service_name(s)
            op = s.get("name", "unknown")
            errors_by_service[svc] = errors_by_service.get(svc, 0) + 1
            errors_by_operation[op] = errors_by_operation.get(op, 0) + 1

            for event in s.get("events", []):
                if event.get("name") == "exception":
                    exc_type = event.get("attributes", {}).get("exception.type", "Unknown")
                    error_types[exc_type] = error_types.get(exc_type, 0) + 1

    return {
        "total_errors": total_errors,
        "total_spans": len(spans),
        "error_rate": total_errors / len(spans) if spans else 0,
        "by_service": errors_by_service,
        "by_operation": errors_by_operation,
        "exception_types": error_types,
    }


def span_depth(spans: list[dict]) -> int:
    """Calculate the maximum nesting depth in a trace."""
    if not spans:
        return 0

    children_map: dict[Optional[str], list[dict]] = {}
    all_ids = set()
    for s in spans:
        sid = s["span_id"]
        pid = s.get("parent_span_id")
        all_ids.add(sid)
        children_map.setdefault(pid, []).append(s)

    roots = [s for s in spans if s.get("parent_span_id") not in all_ids]
    if not roots:
        roots = children_map.get(None, spans[:1])

    def _depth(span: dict) -> int:
        kids = children_map.get(span["span_id"], [])
        if not kids:
            return 1
        return 1 + max(_depth(k) for k in kids)

    return max(_depth(r) for r in roots)
