"""
Sampling strategies for controlling which traces are recorded.

Sampling at the head of a trace ensures consistent decisions:
once a trace is sampled (or not), all spans inherit that decision.
"""

from __future__ import annotations

import enum
import time
import threading
from typing import Optional, Any

from tracelite.context import SpanContext
from tracelite.utils import trace_id_to_int


class SamplingDecision(enum.Enum):
    """Outcome of a sampling decision."""
    DROP = 0
    RECORD_ONLY = 1
    RECORD_AND_SAMPLE = 2


class SamplingResult:
    """Result from a sampler, including the decision and any extra attributes."""

    __slots__ = ("decision", "attributes")

    def __init__(self, decision: SamplingDecision,
                 attributes: Optional[dict[str, Any]] = None):
        self.decision = decision
        self.attributes = attributes or {}

    @property
    def is_sampled(self) -> bool:
        return self.decision == SamplingDecision.RECORD_AND_SAMPLE

    @property
    def is_recording(self) -> bool:
        return self.decision != SamplingDecision.DROP

    def __repr__(self) -> str:
        return f"SamplingResult({self.decision.name})"


class Sampler:
    """Base class for sampling strategies."""

    def should_sample(
        self,
        trace_id: str,
        name: str,
        parent_context: Optional[SpanContext] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> SamplingResult:
        raise NotImplementedError

    @property
    def description(self) -> str:
        return self.__class__.__name__


class AlwaysOnSampler(Sampler):
    """Records every span."""

    def should_sample(self, trace_id, name, parent_context=None,
                      attributes=None) -> SamplingResult:
        return SamplingResult(SamplingDecision.RECORD_AND_SAMPLE)

    @property
    def description(self) -> str:
        return "AlwaysOnSampler"


class AlwaysOffSampler(Sampler):
    """Drops every span."""

    def should_sample(self, trace_id, name, parent_context=None,
                      attributes=None) -> SamplingResult:
        return SamplingResult(SamplingDecision.DROP)

    @property
    def description(self) -> str:
        return "AlwaysOffSampler"


class ProbabilisticSampler(Sampler):
    """
    Samples traces based on a probability (0.0 to 1.0).

    Uses the trace_id for deterministic sampling so the same
    trace is always sampled or dropped across services.
    """

    def __init__(self, rate: float = 1.0):
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"rate must be between 0.0 and 1.0, got {rate}")
        self._rate = rate
        # Threshold: trace_ids below this value are sampled
        self._bound = int(rate * (2**128 - 1))

    @property
    def rate(self) -> float:
        return self._rate

    def should_sample(self, trace_id, name, parent_context=None,
                      attributes=None) -> SamplingResult:
        if self._rate == 0.0:
            return SamplingResult(SamplingDecision.DROP)
        if self._rate == 1.0:
            return SamplingResult(SamplingDecision.RECORD_AND_SAMPLE)

        tid_int = trace_id_to_int(trace_id)
        if tid_int < self._bound:
            return SamplingResult(SamplingDecision.RECORD_AND_SAMPLE)
        return SamplingResult(SamplingDecision.DROP)

    @property
    def description(self) -> str:
        return f"ProbabilisticSampler(rate={self._rate})"


class RateLimitingSampler(Sampler):
    """
    Token bucket sampler: allows at most N traces per second.

    Tokens refill continuously. Each sampled trace consumes one token.
    Thread-safe via a lock.
    """

    def __init__(self, max_traces_per_second: float = 10.0):
        if max_traces_per_second < 0:
            raise ValueError("max_traces_per_second must be non-negative")
        self._max_rate = max_traces_per_second
        self._tokens = max_traces_per_second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def should_sample(self, trace_id, name, parent_context=None,
                      attributes=None) -> SamplingResult:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._max_rate,
                self._tokens + elapsed * self._max_rate,
            )
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return SamplingResult(SamplingDecision.RECORD_AND_SAMPLE)

        return SamplingResult(SamplingDecision.DROP)

    @property
    def description(self) -> str:
        return f"RateLimitingSampler(max={self._max_rate}/s)"


class ParentBasedSampler(Sampler):
    """
    Delegates to the parent span's sampling decision.

    - If the parent is sampled, this span is sampled.
    - If the parent is not sampled, this span is dropped.
    - If there's no parent, delegates to a root sampler.
    """

    def __init__(self, root_sampler: Optional[Sampler] = None):
        self._root_sampler = root_sampler or AlwaysOnSampler()

    def should_sample(self, trace_id, name, parent_context=None,
                      attributes=None) -> SamplingResult:
        if parent_context is None:
            return self._root_sampler.should_sample(
                trace_id, name, parent_context, attributes
            )

        if parent_context.is_sampled:
            return SamplingResult(SamplingDecision.RECORD_AND_SAMPLE)
        return SamplingResult(SamplingDecision.DROP)

    @property
    def description(self) -> str:
        return f"ParentBasedSampler(root={self._root_sampler.description})"
