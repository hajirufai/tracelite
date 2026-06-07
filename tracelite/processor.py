"""
Span processors handle finished spans before export.

SimpleSpanProcessor exports synchronously on span end.
BatchSpanProcessor queues spans and exports in batches
via a background thread, reducing overhead.
"""

from __future__ import annotations

import threading
import queue
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tracelite.span import Span
    from tracelite.exporter import SpanExporter


class SpanProcessor:
    """Base class for span processors."""

    def on_start(self, span: "Span") -> None:
        """Called when a span starts."""
        pass

    def on_end(self, span: "Span") -> None:
        """Called when a span ends."""
        pass

    def shutdown(self) -> None:
        """Clean up resources."""
        pass

    def force_flush(self, timeout_ms: int = 30000) -> bool:
        """Force export of all pending spans. Returns True on success."""
        return True


class SimpleSpanProcessor(SpanProcessor):
    """
    Exports each span synchronously when it ends.

    Good for debugging or low-throughput scenarios.
    Not suitable for production — blocks the calling thread.
    """

    def __init__(self, exporter: "SpanExporter"):
        self._exporter = exporter
        self._stopped = False

    def on_end(self, span: "Span") -> None:
        if self._stopped:
            return
        if span.is_ended:
            self._exporter.export([span])

    def shutdown(self) -> None:
        self._stopped = True
        self._exporter.shutdown()

    def force_flush(self, timeout_ms: int = 30000) -> bool:
        return True


class BatchSpanProcessor(SpanProcessor):
    """
    Batches spans and exports them via a background thread.

    Collects spans in a queue and periodically exports them
    when the batch size or delay threshold is reached.
    """

    def __init__(
        self,
        exporter: "SpanExporter",
        max_batch_size: int = 512,
        schedule_delay_ms: int = 5000,
        max_queue_size: int = 2048,
    ):
        self._exporter = exporter
        self._max_batch_size = max_batch_size
        self._schedule_delay_s = schedule_delay_ms / 1000.0
        self._max_queue_size = max_queue_size
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._stopped = False
        self._flush_event = threading.Event()
        self._done_event = threading.Event()

        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="tracelite-batch-processor",
        )
        self._worker.start()

    def on_end(self, span: "Span") -> None:
        if self._stopped:
            return
        if not span.is_ended:
            return
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            pass  # Drop span when queue is full (back-pressure)

    def _worker_loop(self) -> None:
        while not self._stopped:
            self._flush_event.wait(timeout=self._schedule_delay_s)
            self._flush_event.clear()
            self._export_batch()

        # Final drain on shutdown
        self._export_batch()
        self._done_event.set()

    def _export_batch(self) -> None:
        batch: list["Span"] = []
        while len(batch) < self._max_batch_size:
            try:
                span = self._queue.get_nowait()
                batch.append(span)
            except queue.Empty:
                break

        if batch:
            try:
                self._exporter.export(batch)
            except Exception:
                pass  # Don't crash the worker thread

    def force_flush(self, timeout_ms: int = 30000) -> bool:
        """Trigger immediate export of queued spans."""
        self._flush_event.set()
        return self._done_event.wait(timeout=timeout_ms / 1000.0) or self._queue.empty()

    def shutdown(self) -> None:
        """Stop the worker thread and export remaining spans."""
        self._stopped = True
        self._flush_event.set()
        self._done_event.wait(timeout=5.0)
        self._exporter.shutdown()

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
