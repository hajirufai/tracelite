"""Tests for sampling strategies."""

import time
import pytest
from tracelite.sampler import (
    AlwaysOnSampler, AlwaysOffSampler, ProbabilisticSampler,
    RateLimitingSampler, ParentBasedSampler, SamplingDecision,
)
from tracelite.context import SpanContext
from tracelite.utils import generate_trace_id


class TestAlwaysOnSampler:
    def test_always_samples(self):
        sampler = AlwaysOnSampler()
        result = sampler.should_sample(generate_trace_id(), "op")
        assert result.is_sampled is True
        assert result.is_recording is True
        assert result.decision == SamplingDecision.RECORD_AND_SAMPLE

    def test_description(self):
        assert AlwaysOnSampler().description == "AlwaysOnSampler"


class TestAlwaysOffSampler:
    def test_never_samples(self):
        sampler = AlwaysOffSampler()
        result = sampler.should_sample(generate_trace_id(), "op")
        assert result.is_sampled is False
        assert result.is_recording is False
        assert result.decision == SamplingDecision.DROP

    def test_description(self):
        assert AlwaysOffSampler().description == "AlwaysOffSampler"


class TestProbabilisticSampler:
    def test_rate_1_always_samples(self):
        sampler = ProbabilisticSampler(rate=1.0)
        for _ in range(100):
            result = sampler.should_sample(generate_trace_id(), "op")
            assert result.is_sampled is True

    def test_rate_0_never_samples(self):
        sampler = ProbabilisticSampler(rate=0.0)
        for _ in range(100):
            result = sampler.should_sample(generate_trace_id(), "op")
            assert result.is_sampled is False

    def test_deterministic(self):
        sampler = ProbabilisticSampler(rate=0.5)
        trace_id = generate_trace_id()
        results = [sampler.should_sample(trace_id, "op").is_sampled for _ in range(10)]
        # Same trace_id should always give same result
        assert len(set(results)) == 1

    def test_rate_0_5_approximately_half(self):
        sampler = ProbabilisticSampler(rate=0.5)
        sampled = sum(
            1 for _ in range(1000)
            if sampler.should_sample(generate_trace_id(), "op").is_sampled
        )
        # Should be roughly 500, allow wide margin
        assert 300 < sampled < 700

    def test_invalid_rate(self):
        with pytest.raises(ValueError):
            ProbabilisticSampler(rate=1.5)
        with pytest.raises(ValueError):
            ProbabilisticSampler(rate=-0.1)

    def test_description(self):
        s = ProbabilisticSampler(rate=0.25)
        assert "0.25" in s.description


class TestRateLimitingSampler:
    def test_allows_up_to_rate(self):
        sampler = RateLimitingSampler(max_traces_per_second=5)
        sampled = 0
        for _ in range(5):
            if sampler.should_sample(generate_trace_id(), "op").is_sampled:
                sampled += 1
        assert sampled > 0

    def test_rejects_over_rate(self):
        sampler = RateLimitingSampler(max_traces_per_second=2)
        results = []
        for _ in range(20):
            results.append(sampler.should_sample(generate_trace_id(), "op").is_sampled)
        # Should have some drops
        assert False in results

    def test_refills_over_time(self):
        sampler = RateLimitingSampler(max_traces_per_second=100)
        # Drain tokens
        for _ in range(100):
            sampler.should_sample(generate_trace_id(), "op")
        # Wait for refill
        time.sleep(0.05)
        result = sampler.should_sample(generate_trace_id(), "op")
        assert result.is_sampled is True

    def test_invalid_rate(self):
        with pytest.raises(ValueError):
            RateLimitingSampler(max_traces_per_second=-1)


class TestParentBasedSampler:
    def test_root_with_default(self):
        sampler = ParentBasedSampler()
        result = sampler.should_sample(generate_trace_id(), "op")
        assert result.is_sampled is True  # Default root is AlwaysOn

    def test_root_with_custom(self):
        sampler = ParentBasedSampler(root_sampler=AlwaysOffSampler())
        result = sampler.should_sample(generate_trace_id(), "op")
        assert result.is_sampled is False

    def test_parent_sampled(self):
        sampler = ParentBasedSampler()
        parent = SpanContext("a" * 32, "b" * 16, trace_flags=1)
        result = sampler.should_sample(generate_trace_id(), "op", parent)
        assert result.is_sampled is True

    def test_parent_not_sampled(self):
        sampler = ParentBasedSampler()
        parent = SpanContext("a" * 32, "b" * 16, trace_flags=0)
        result = sampler.should_sample(generate_trace_id(), "op", parent)
        assert result.is_sampled is False

    def test_description(self):
        s = ParentBasedSampler(root_sampler=ProbabilisticSampler(rate=0.1))
        assert "ParentBased" in s.description
        assert "Probabilistic" in s.description
