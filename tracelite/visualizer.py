"""
Terminal-based waterfall trace visualization.

Renders a trace as an ASCII waterfall diagram showing
span hierarchy, timing, and duration — ideal for CLI
debugging and CI output.
"""

from __future__ import annotations

from typing import Optional
from tracelite.clock import format_duration


def render_waterfall(
    spans: list[dict],
    width: int = 60,
    colorize: bool = False,
) -> str:
    """
    Render a trace as an ASCII waterfall diagram.

    Args:
        spans: List of span dicts (a complete trace).
        width: Width of the timeline bar in characters.
        colorize: Whether to use ANSI color codes.

    Returns:
        Multi-line string with the waterfall visualization.
    """
    if not spans:
        return "(empty trace)"

    # Sort by start time
    spans = sorted(spans, key=lambda s: s.get("start_time_ns", 0))

    # Find global time range
    trace_start = min(s.get("start_time_ns", 0) for s in spans)
    trace_end = max(
        (s.get("end_time_ns") or s.get("start_time_ns", 0)) for s in spans
    )
    trace_duration = trace_end - trace_start

    if trace_duration == 0:
        trace_duration = 1  # Avoid division by zero

    # Find the trace ID
    trace_id = spans[0].get("trace_id", "unknown")

    # Build tree structure for indentation
    children_map: dict[Optional[str], list[dict]] = {}
    all_ids = set()
    for s in spans:
        sid = s["span_id"]
        pid = s.get("parent_span_id")
        all_ids.add(sid)
        children_map.setdefault(pid, []).append(s)

    # Find roots
    roots = [s for s in spans if s.get("parent_span_id") not in all_ids]
    if not roots:
        roots = children_map.get(None, spans[:1])

    # Flatten tree with depth info
    ordered: list[tuple[dict, int]] = []

    def _walk(span: dict, depth: int):
        ordered.append((span, depth))
        kids = children_map.get(span["span_id"], [])
        kids.sort(key=lambda s: s.get("start_time_ns", 0))
        for child in kids:
            _walk(child, depth + 1)

    for root in roots:
        _walk(root, 0)

    # Column widths
    svc_width = 18
    op_width = 24
    dur_width = 10

    # Build output
    lines = []

    # Header
    total_dur_str = format_duration(trace_duration)
    lines.append(
        f"Trace: {trace_id[:16]}  Duration: {total_dur_str}  Spans: {len(spans)}"
    )
    lines.append("")

    # Column headers
    header = (
        f"{'Service':<{svc_width}} "
        f"{'Operation':<{op_width}} "
        f"{'Duration':>{dur_width}}  "
        f"Timeline"
    )
    lines.append(header)
    lines.append("─" * (svc_width + op_width + dur_width + width + 6))

    # Render each span
    for span, depth in ordered:
        svc = span.get("service_name", "unknown")
        if svc == "unknown" and "resource" in span:
            svc = span["resource"].get("service.name", "unknown")
        op = span.get("name", "unknown")
        dur_ns = span.get("duration_ns", 0)
        start = span.get("start_time_ns", 0)
        end = span.get("end_time_ns", start)

        # Indent for depth
        indent = "  " * depth
        svc_str = f"{indent}{svc}"
        if len(svc_str) > svc_width:
            svc_str = svc_str[: svc_width - 1] + "…"

        op_str = op
        if len(op_str) > op_width:
            op_str = op_str[: op_width - 1] + "…"

        dur_str = format_duration(dur_ns)

        # Timeline bar
        bar_start = int((start - trace_start) / trace_duration * width)
        bar_end = int((end - trace_start) / trace_duration * width)
        bar_len = max(bar_end - bar_start, 1)

        bar = " " * bar_start + "█" * bar_len

        # Color based on status
        status = span.get("status_code", "UNSET")
        if colorize:
            if status == "ERROR":
                bar = f"\033[31m{bar}\033[0m"
            elif status == "OK":
                bar = f"\033[32m{bar}\033[0m"
            else:
                bar = f"\033[33m{bar}\033[0m"

        line = (
            f"{svc_str:<{svc_width}} "
            f"{op_str:<{op_width}} "
            f"{dur_str:>{dur_width}}  "
            f"{bar}"
        )
        lines.append(line)

    return "\n".join(lines)


def render_span_tree(spans: list[dict]) -> str:
    """
    Render a trace as a simple tree showing parent-child relationships.

    Example:
        GET /users (245ms)
        ├── validate_token (12ms)
        ├── fetch_users (198ms)
        │   ├── SELECT users (45ms)
        │   └── SELECT profiles (89ms)
        └── serialize_response (28ms)
    """
    if not spans:
        return "(empty trace)"

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

    lines = []

    def _render(span: dict, prefix: str, is_last: bool):
        dur = format_duration(span.get("duration_ns", 0))
        name = span.get("name", "unknown")
        status = span.get("status_code", "UNSET")
        marker = "✗" if status == "ERROR" else "●"

        connector = "└── " if is_last else "├── "
        line = f"{prefix}{connector}{marker} {name} ({dur})"
        lines.append(line)

        children = children_map.get(span["span_id"], [])
        children.sort(key=lambda s: s.get("start_time_ns", 0))
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            _render(child, child_prefix, i == len(children) - 1)

    for i, root in enumerate(roots):
        if i == 0:
            dur = format_duration(root.get("duration_ns", 0))
            name = root.get("name", "unknown")
            lines.append(f"● {name} ({dur})")
            children = children_map.get(root["span_id"], [])
            children.sort(key=lambda s: s.get("start_time_ns", 0))
            for j, child in enumerate(children):
                _render(child, "", j == len(children) - 1)
        else:
            _render(root, "", i == len(roots) - 1)

    return "\n".join(lines)
