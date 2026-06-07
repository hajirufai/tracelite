"""
Clock utilities for precise span timing.

Uses monotonic clock for duration and wall clock for timestamps.
"""

import time


def now_ns() -> int:
    """Wall-clock time in nanoseconds since epoch."""
    return int(time.time() * 1_000_000_000)


def monotonic_ns() -> int:
    """Monotonic clock in nanoseconds for duration measurement."""
    return time.perf_counter_ns()


def duration_ms(start_ns: int, end_ns: int) -> float:
    """Convert nanosecond duration to milliseconds."""
    return (end_ns - start_ns) / 1_000_000


def duration_us(start_ns: int, end_ns: int) -> float:
    """Convert nanosecond duration to microseconds."""
    return (end_ns - start_ns) / 1_000


def format_duration(ns: int) -> str:
    """Human-readable duration string from nanoseconds."""
    if ns < 1_000:
        return f"{ns}ns"
    elif ns < 1_000_000:
        return f"{ns / 1_000:.1f}µs"
    elif ns < 1_000_000_000:
        return f"{ns / 1_000_000:.1f}ms"
    else:
        return f"{ns / 1_000_000_000:.2f}s"


def format_timestamp(ns: int) -> str:
    """ISO 8601 timestamp from nanoseconds since epoch."""
    seconds = ns / 1_000_000_000
    t = time.gmtime(seconds)
    frac = seconds - int(seconds)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + f".{int(frac * 1_000_000):06d}Z"
