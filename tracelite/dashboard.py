"""
Static HTML dashboard generator for trace data.

Generates a self-contained HTML page with trace list,
waterfall views, and service map — no JavaScript frameworks,
just clean HTML/CSS/vanilla JS.
"""

from __future__ import annotations

import json
from typing import Optional

from tracelite.storage import SpanStorage
from tracelite.metrics import REDMetrics
from tracelite.graph import ServiceGraph
from tracelite.clock import format_duration, format_timestamp
from tracelite.analyzer import critical_path, latency_breakdown


def generate_dashboard(
    storage: SpanStorage,
    title: str = "TraceLite Dashboard",
    max_traces: int = 50,
) -> str:
    """
    Generate a self-contained HTML dashboard from stored trace data.

    Includes: trace list, trace detail (waterfall), service map, and metrics.
    """
    traces = storage.get_traces(limit=max_traces)
    services = storage.get_services()
    red = REDMetrics(storage)
    metrics_by_service = red.compute_by_service()

    graph = ServiceGraph()
    graph.add_traces(traces)

    # Build trace summaries for the list view
    trace_summaries = []
    for trace_spans in traces:
        if not trace_spans:
            continue
        root = trace_spans[0]
        trace_summaries.append({
            "trace_id": root["trace_id"],
            "operation": root["name"],
            "service": root.get("service_name", "unknown"),
            "duration_ns": root.get("duration_ns", 0),
            "duration": format_duration(root.get("duration_ns", 0)),
            "span_count": len(trace_spans),
            "status": root.get("status_code", "UNSET"),
            "start_time": format_timestamp(root.get("start_time_ns", 0)),
            "spans": trace_spans,
        })

    html = _build_html(title, trace_summaries, services, metrics_by_service, graph)
    return html


def save_dashboard(
    storage: SpanStorage,
    output_path: str,
    title: str = "TraceLite Dashboard",
) -> str:
    """Generate and save dashboard to a file. Returns the file path."""
    html = generate_dashboard(storage, title)
    with open(output_path, "w") as f:
        f.write(html)
    return output_path


def _build_html(
    title: str,
    traces: list[dict],
    services: list[dict],
    metrics: list[dict],
    graph: ServiceGraph,
) -> str:
    """Build the complete HTML dashboard."""

    traces_json = json.dumps(traces, default=str)
    metrics_json = json.dumps(metrics, default=str)
    graph_nodes = json.dumps(graph.nodes)
    graph_edges = json.dumps(graph.edges, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --bg: oklch(96% 0.008 220);
  --ink: oklch(18% 0.012 220);
  --accent: oklch(58% 0.16 250);
  --surface: oklch(99% 0.005 220);
  --border: oklch(88% 0.008 220);
  --muted: oklch(56% 0.01 220);
  --ok: oklch(55% 0.14 145);
  --err: oklch(55% 0.18 25);
  --warn: oklch(65% 0.14 80);
  --mono: "Geist Mono", "SF Mono", "Cascadia Code", monospace;
  --sans: "Geist", "Inter", system-ui, sans-serif;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: var(--sans);
  background: var(--bg);
  color: var(--ink);
  line-height: 1.55;
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}}
h1 {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.2rem; font-weight: 600; margin: 2rem 0 1rem; }}
.tabs {{ display: flex; gap: 0; border-bottom: 2px solid var(--border); margin-bottom: 1.5rem; }}
.tab {{
  padding: 0.6rem 1.2rem;
  cursor: pointer;
  border: none;
  background: none;
  font-family: var(--sans);
  font-size: 0.9rem;
  color: var(--muted);
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: color 0.15s, border-color 0.15s;
}}
.tab:hover {{ color: var(--ink); }}
.tab.active {{ color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }}
.panel {{ display: none; }}
.panel.active {{ display: block; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.6rem; border-bottom: 2px solid var(--border); font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }}
td {{ padding: 0.6rem; border-bottom: 1px solid var(--border); }}
tr:hover {{ background: oklch(94% 0.005 220); }}
.mono {{ font-family: var(--mono); font-size: 0.8rem; }}
.badge {{
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
  font-size: 0.75rem; font-weight: 600;
}}
.badge-ok {{ background: oklch(92% 0.06 145); color: oklch(30% 0.1 145); }}
.badge-err {{ background: oklch(92% 0.06 25); color: oklch(30% 0.1 25); }}
.badge-unset {{ background: oklch(92% 0.03 220); color: oklch(40% 0.02 220); }}
.metric-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.2rem;
  display: inline-block;
  min-width: 180px;
  margin: 0.5rem;
}}
.metric-value {{ font-size: 1.8rem; font-weight: 700; font-family: var(--mono); }}
.metric-label {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.3rem; }}
.waterfall {{ font-family: var(--mono); font-size: 0.8rem; white-space: pre; overflow-x: auto; }}
.clickable {{ cursor: pointer; color: var(--accent); }}
.clickable:hover {{ text-decoration: underline; }}
.graph-ascii {{ font-family: var(--mono); font-size: 0.85rem; white-space: pre; background: var(--surface); padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p style="color: var(--muted); margin-bottom: 1.5rem;">
  {len(traces)} traces &middot; {sum(t['span_count'] for t in traces)} spans &middot; {len(services)} services
</p>

<div class="tabs">
  <button class="tab active" onclick="showTab('traces')">Traces</button>
  <button class="tab" onclick="showTab('metrics')">Metrics</button>
  <button class="tab" onclick="showTab('graph')">Service Map</button>
</div>

<div id="traces" class="panel active">
<table>
<thead>
<tr><th>Trace ID</th><th>Service</th><th>Operation</th><th>Duration</th><th>Spans</th><th>Status</th><th>Started</th></tr>
</thead>
<tbody id="trace-list"></tbody>
</table>
<div id="trace-detail" style="margin-top: 1.5rem;"></div>
</div>

<div id="metrics" class="panel">
<div id="metrics-cards"></div>
<h2>Metrics by Service</h2>
<table id="metrics-table">
<thead><tr><th>Service</th><th>Rate</th><th>Errors</th><th>p50</th><th>p90</th><th>p95</th><th>p99</th></tr></thead>
<tbody></tbody>
</table>
</div>

<div id="graph" class="panel">
<h2>Service Dependencies</h2>
<div class="graph-ascii" id="graph-content"></div>
</div>

<script>
const traces = {traces_json};
const metrics = {metrics_json};
const graphNodes = {graph_nodes};
const graphEdges = {graph_edges};

function showTab(name) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  event.target.classList.add('active');
}}

function formatDur(ns) {{
  if (ns < 1000) return ns + 'ns';
  if (ns < 1e6) return (ns/1e3).toFixed(1) + 'µs';
  if (ns < 1e9) return (ns/1e6).toFixed(1) + 'ms';
  return (ns/1e9).toFixed(2) + 's';
}}

function badge(status) {{
  const cls = status === 'ERROR' ? 'badge-err' : status === 'OK' ? 'badge-ok' : 'badge-unset';
  return '<span class="badge ' + cls + '">' + status + '</span>';
}}

// Populate trace list
const tbody = document.getElementById('trace-list');
traces.forEach((t, i) => {{
  const tr = document.createElement('tr');
  tr.innerHTML = '<td class="mono clickable" onclick="showTrace(' + i + ')">' + t.trace_id.slice(0,16) + '…</td>'
    + '<td>' + t.service + '</td>'
    + '<td class="mono">' + t.operation + '</td>'
    + '<td class="mono">' + t.duration + '</td>'
    + '<td>' + t.span_count + '</td>'
    + '<td>' + badge(t.status) + '</td>'
    + '<td class="mono">' + t.start_time + '</td>';
  tbody.appendChild(tr);
}});

function showTrace(i) {{
  const t = traces[i];
  const spans = t.spans || [];
  const detail = document.getElementById('trace-detail');
  let html = '<h2>Trace ' + t.trace_id.slice(0,16) + '… — ' + t.operation + '</h2>';
  html += '<div class="waterfall">';
  const tStart = Math.min(...spans.map(s => s.start_time_ns || 0));
  const tEnd = Math.max(...spans.map(s => s.end_time_ns || s.start_time_ns || 0));
  const tDur = tEnd - tStart || 1;
  const W = 40;
  spans.sort((a,b) => (a.start_time_ns||0) - (b.start_time_ns||0));
  spans.forEach(s => {{
    const svc = (s.service_name || (s.resource || {{}})['service.name'] || '???').slice(0,16).padEnd(16);
    const op = (s.name || '???').slice(0,22).padEnd(22);
    const dur = formatDur(s.duration_ns || 0).padStart(8);
    const bStart = Math.floor(((s.start_time_ns||0) - tStart) / tDur * W);
    const bEnd = Math.floor(((s.end_time_ns||s.start_time_ns||0) - tStart) / tDur * W);
    const bLen = Math.max(bEnd - bStart, 1);
    const bar = ' '.repeat(bStart) + '█'.repeat(bLen);
    html += svc + ' ' + op + ' ' + dur + '  ' + bar + '\\n';
  }});
  html += '</div>';
  detail.innerHTML = html;
}}

// Populate metrics
const mCards = document.getElementById('metrics-cards');
const totalReqs = metrics.reduce((s,m) => s + m.total_requests, 0);
const totalErrs = metrics.reduce((s,m) => s + m.total_errors, 0);
mCards.innerHTML = '<div class="metric-card"><div class="metric-value">' + totalReqs + '</div><div class="metric-label">Total Requests</div></div>'
  + '<div class="metric-card"><div class="metric-value">' + totalErrs + '</div><div class="metric-label">Total Errors</div></div>'
  + '<div class="metric-card"><div class="metric-value">' + metrics.length + '</div><div class="metric-label">Services</div></div>';

const mBody = document.querySelector('#metrics-table tbody');
metrics.forEach(m => {{
  const d = m.duration || {{}};
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + m.service + '</td>'
    + '<td class="mono">' + m.rate.toFixed(1) + '/s</td>'
    + '<td class="mono">' + (m.error_rate * 100).toFixed(1) + '%</td>'
    + '<td class="mono">' + formatDur(d.p50||0) + '</td>'
    + '<td class="mono">' + formatDur(d.p90||0) + '</td>'
    + '<td class="mono">' + formatDur(d.p95||0) + '</td>'
    + '<td class="mono">' + formatDur(d.p99||0) + '</td>';
  mBody.appendChild(tr);
}});

// Service graph
const gc = document.getElementById('graph-content');
let gText = 'Services: ' + graphNodes.join(', ') + '\\n\\n';
if (graphEdges.length === 0) {{
  gText += '(no cross-service calls detected)';
}} else {{
  graphEdges.forEach(e => {{
    gText += e.source + ' ──▶ ' + e.target + '  (' + e.call_count + ' calls, '
      + formatDur(e.avg_duration_ns) + ' avg, '
      + (e.error_rate * 100).toFixed(0) + '% errors)\\n';
  }});
}}
gc.textContent = gText;
</script>
</body>
</html>"""
