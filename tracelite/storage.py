"""
SQLite-backed persistent storage for spans.

Stores finished spans with full metadata, events, and attributes.
Supports querying by trace_id, service, time range, and duration.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tracelite.span import Span


_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL UNIQUE,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    service_name TEXT NOT NULL DEFAULT 'unknown',
    status_code TEXT NOT NULL DEFAULT 'UNSET',
    status_description TEXT DEFAULT '',
    start_time_ns INTEGER NOT NULL,
    end_time_ns INTEGER,
    duration_ns INTEGER DEFAULT 0,
    attributes_json TEXT DEFAULT '{}',
    events_json TEXT DEFAULT '[]',
    links_json TEXT DEFAULT '[]',
    resource_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_service ON spans(service_name);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans(start_time_ns);
CREATE INDEX IF NOT EXISTS idx_spans_status ON spans(status_code);
CREATE INDEX IF NOT EXISTS idx_spans_name ON spans(name);
CREATE INDEX IF NOT EXISTS idx_spans_duration ON spans(duration_ns);
"""


class SpanStorage:
    """
    SQLite-backed span storage with thread-safe access.

    Supports insert, query, and retention policies.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert_spans(self, spans: list["Span"]) -> int:
        """Insert a batch of spans. Returns number inserted."""
        if not spans:
            return 0

        rows = []
        for span in spans:
            rows.append((
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.name,
                span.kind.name,
                span.resource.service_name,
                span.status.code.name,
                span.status.description,
                span.start_time_ns,
                span.end_time_ns,
                span.duration_ns,
                json.dumps(span.attributes, default=str),
                json.dumps([e.to_dict() for e in span.events], default=str),
                json.dumps([lnk.to_dict() for lnk in span.links], default=str),
                json.dumps(span.resource.to_dict(), default=str),
            ))

        sql = """
            INSERT OR IGNORE INTO spans (
                trace_id, span_id, parent_span_id, name, kind,
                service_name, status_code, status_description,
                start_time_ns, end_time_ns, duration_ns,
                attributes_json, events_json, links_json, resource_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._lock:
            cursor = self._conn.executemany(sql, rows)
            self._conn.commit()
            return cursor.rowcount

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get all spans for a trace, ordered by start time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time_ns",
                (trace_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_traces(
        self,
        service_name: Optional[str] = None,
        operation: Optional[str] = None,
        min_duration_ns: Optional[int] = None,
        error_only: bool = False,
        since_ns: Optional[int] = None,
        until_ns: Optional[int] = None,
        limit: int = 100,
    ) -> list[list[dict]]:
        """
        Query traces matching filters.

        Returns a list of traces, where each trace is a list of span dicts.
        Only returns root-span-matching traces.
        """
        conditions = ["parent_span_id IS NULL"]
        params: list = []

        if service_name:
            conditions.append("service_name = ?")
            params.append(service_name)
        if operation:
            conditions.append("name = ?")
            params.append(operation)
        if min_duration_ns is not None:
            conditions.append("duration_ns >= ?")
            params.append(min_duration_ns)
        if error_only:
            conditions.append("status_code = 'ERROR'")
        if since_ns is not None:
            conditions.append("start_time_ns >= ?")
            params.append(since_ns)
        if until_ns is not None:
            conditions.append("start_time_ns <= ?")
            params.append(until_ns)

        where = " AND ".join(conditions)
        sql = f"SELECT trace_id FROM spans WHERE {where} ORDER BY start_time_ns DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            trace_ids = [r["trace_id"] for r in rows]

        traces = []
        for tid in trace_ids:
            spans = self.get_trace(tid)
            if spans:
                traces.append(spans)
        return traces

    def get_services(self) -> list[dict]:
        """List distinct services with span counts."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT service_name, COUNT(*) as span_count "
                "FROM spans GROUP BY service_name ORDER BY span_count DESC"
            ).fetchall()
        return [{"service_name": r["service_name"], "span_count": r["span_count"]} for r in rows]

    def get_operations(self, service_name: Optional[str] = None) -> list[dict]:
        """List distinct operations, optionally filtered by service."""
        if service_name:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT name, COUNT(*) as count FROM spans "
                    "WHERE service_name = ? GROUP BY name ORDER BY count DESC",
                    (service_name,),
                ).fetchall()
        else:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT name, COUNT(*) as count FROM spans "
                    "GROUP BY name ORDER BY count DESC"
                ).fetchall()
        return [{"operation": r["name"], "count": r["count"]} for r in rows]

    def span_count(self) -> int:
        """Total number of stored spans."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM spans").fetchone()
        return row["cnt"]

    def trace_count(self) -> int:
        """Total number of distinct traces."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT trace_id) as cnt FROM spans"
            ).fetchone()
        return row["cnt"]

    def apply_retention(self, max_age_hours: float = 24.0) -> int:
        """Delete spans older than max_age_hours. Returns deleted count."""
        cutoff_ns = int((time.time() - max_age_hours * 3600) * 1_000_000_000)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM spans WHERE start_time_ns < ?", (cutoff_ns,)
            )
            self._conn.commit()
            return cursor.rowcount

    def compact(self) -> None:
        """Run VACUUM to reclaim disk space."""
        with self._lock:
            self._conn.execute("VACUUM")

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a span dictionary."""
        d = dict(row)
        d["attributes"] = json.loads(d.pop("attributes_json", "{}"))
        d["events"] = json.loads(d.pop("events_json", "[]"))
        d["links"] = json.loads(d.pop("links_json", "[]"))
        d["resource"] = json.loads(d.pop("resource_json", "{}"))
        d.pop("id", None)
        d.pop("created_at", None)
        return d

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
