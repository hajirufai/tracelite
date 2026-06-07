"""
Utility functions for ID generation, validation, and formatting.
"""

import os
import struct


def generate_trace_id() -> str:
    """Generate a 128-bit trace ID as 32 hex characters."""
    return os.urandom(16).hex()


def generate_span_id() -> str:
    """Generate a 64-bit span ID as 16 hex characters."""
    return os.urandom(8).hex()


def is_valid_trace_id(trace_id: str) -> bool:
    """Check if trace_id is a valid 32-char hex string and not all zeros."""
    if not isinstance(trace_id, str) or len(trace_id) != 32:
        return False
    try:
        val = int(trace_id, 16)
        return val != 0
    except ValueError:
        return False


def is_valid_span_id(span_id: str) -> bool:
    """Check if span_id is a valid 16-char hex string and not all zeros."""
    if not isinstance(span_id, str) or len(span_id) != 16:
        return False
    try:
        val = int(span_id, 16)
        return val != 0
    except ValueError:
        return False


def trace_id_to_int(trace_id: str) -> int:
    """Convert hex trace ID to integer for hashing/sampling."""
    return int(trace_id, 16)


def truncate(s: str, max_len: int = 80) -> str:
    """Truncate string with ellipsis."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def flatten_attributes(attrs: dict, prefix: str = "") -> dict:
    """Flatten nested dict into dot-separated keys."""
    result = {}
    for k, v in attrs.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(flatten_attributes(v, key))
        else:
            result[key] = v
    return result
