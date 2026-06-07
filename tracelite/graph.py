"""
Service dependency graph — built from collected trace data.

Discovers which services call which other services,
with edge weights for call count, avg latency, and error rate.
"""

from __future__ import annotations

from typing import Optional
from tracelite.clock import format_duration


class ServiceGraph:
    """
    Directed graph of service-to-service dependencies.

    Nodes are services. Edges represent calls from one service
    to another, annotated with call count, latency, and error info.
    """

    def __init__(self):
        self._nodes: set[str] = set()
        self._edges: dict[tuple[str, str], dict] = {}

    def add_traces(self, traces: list[list[dict]]) -> None:
        """Build the graph from a list of traces."""
        for trace_spans in traces:
            self._process_trace(trace_spans)

    def _process_trace(self, spans: list[dict]) -> None:
        """Extract service dependencies from a single trace."""
        span_map = {}
        for s in spans:
            span_map[s["span_id"]] = s
            svc = s.get("service_name", "unknown")
            if svc == "unknown" and "resource" in s:
                svc = s["resource"].get("service.name", "unknown")
            self._nodes.add(svc)

        for s in spans:
            parent_id = s.get("parent_span_id")
            if parent_id and parent_id in span_map:
                parent = span_map[parent_id]
                parent_svc = parent.get("service_name", "unknown")
                if parent_svc == "unknown" and "resource" in parent:
                    parent_svc = parent["resource"].get("service.name", "unknown")
                child_svc = s.get("service_name", "unknown")
                if child_svc == "unknown" and "resource" in s:
                    child_svc = s["resource"].get("service.name", "unknown")

                if parent_svc != child_svc:
                    edge_key = (parent_svc, child_svc)
                    if edge_key not in self._edges:
                        self._edges[edge_key] = {
                            "call_count": 0,
                            "total_duration_ns": 0,
                            "error_count": 0,
                            "operations": set(),
                        }
                    edge = self._edges[edge_key]
                    edge["call_count"] += 1
                    edge["total_duration_ns"] += s.get("duration_ns", 0)
                    if s.get("status_code") == "ERROR":
                        edge["error_count"] += 1
                    edge["operations"].add(s.get("name", "unknown"))

    @property
    def nodes(self) -> list[str]:
        """List of service names."""
        return sorted(self._nodes)

    @property
    def edges(self) -> list[dict]:
        """List of edges with metrics."""
        result = []
        for (src, dst), data in self._edges.items():
            count = data["call_count"]
            result.append({
                "source": src,
                "target": dst,
                "call_count": count,
                "avg_duration_ns": data["total_duration_ns"] / count if count else 0,
                "error_rate": data["error_count"] / count if count else 0,
                "operations": sorted(data["operations"]),
            })
        result.sort(key=lambda e: e["call_count"], reverse=True)
        return result

    def to_dot(self, title: str = "Service Dependencies") -> str:
        """Export as Graphviz DOT format."""
        lines = [f'digraph "{title}" {{']
        lines.append("  rankdir=LR;")
        lines.append('  node [shape=box, style=filled, fillcolor="#e8e8e8"];')

        for node in sorted(self._nodes):
            lines.append(f'  "{node}";')

        for (src, dst), data in self._edges.items():
            count = data["call_count"]
            avg_ns = data["total_duration_ns"] / count if count else 0
            avg_str = format_duration(int(avg_ns))
            err_rate = data["error_count"] / count if count else 0

            label = f"{count} calls\\n{avg_str} avg"
            if err_rate > 0:
                label += f"\\n{err_rate:.0%} errors"

            color = "red" if err_rate > 0.1 else "black"
            lines.append(f'  "{src}" -> "{dst}" [label="{label}", color="{color}"];')

        lines.append("}")
        return "\n".join(lines)

    def to_ascii(self) -> str:
        """Simple ASCII representation of the graph."""
        if not self._edges:
            return "(no service dependencies found)"

        lines = ["Service Dependency Graph", "=" * 50]

        for (src, dst), data in sorted(self._edges.items()):
            count = data["call_count"]
            avg_ns = data["total_duration_ns"] / count if count else 0
            avg_str = format_duration(int(avg_ns))
            err_rate = data["error_count"] / count if count else 0

            arrow = f"  {src} ──> {dst}"
            stats = f"    {count} calls, {avg_str} avg"
            if err_rate > 0:
                stats += f", {err_rate:.0%} errors"
            lines.append(arrow)
            lines.append(stats)

        return "\n".join(lines)

    def topological_sort(self) -> list[str]:
        """
        Topological ordering of services.

        Returns services in dependency order (dependencies first).
        Falls back to alphabetical if cycles exist.
        """
        adj: dict[str, set[str]] = {n: set() for n in self._nodes}
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}

        for (src, dst) in self._edges:
            adj[src].add(dst)
            in_degree[dst] = in_degree.get(dst, 0) + 1

        queue = sorted([n for n in self._nodes if in_degree.get(n, 0) == 0])
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in sorted(adj.get(node, set())):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort()

        # If cycle exists, add remaining nodes
        remaining = sorted(set(self._nodes) - set(result))
        result.extend(remaining)
        return result
