"""Tests for the pure watchdog-tier and reconnect-backoff decision functions.

Both are plain functions of elapsed-seconds / attempt-count so the 60s/300s/
900s watchdog tiers and the 2s..120s backoff growth are provable without any
real-time sleeping.
"""

from __future__ import annotations

import random

import pytest

from custom_components.bedjet.pybedjet import (
    WatchdogAction,
    reconnect_backoff_seconds,
    watchdog_action,
)

RECONNECT_BACKOFF_MIN_S = 2.0
RECONNECT_BACKOFF_MAX_S = 120.0


class TestWatchdogAction:
    @pytest.mark.parametrize("elapsed", [0.0, 30.0, 59.999])
    def test_below_probe_threshold_is_none(self, elapsed: float) -> None:
        assert watchdog_action(elapsed) is WatchdogAction.NONE

    @pytest.mark.parametrize("elapsed", [60.0, 120.0, 299.999])
    def test_probe_tier(self, elapsed: float) -> None:
        assert watchdog_action(elapsed) is WatchdogAction.PROBE

    @pytest.mark.parametrize("elapsed", [300.0, 500.0, 899.999])
    def test_unavailable_tier(self, elapsed: float) -> None:
        assert watchdog_action(elapsed) is WatchdogAction.UNAVAILABLE

    @pytest.mark.parametrize("elapsed", [900.0, 1800.0, 1_000_000.0])
    def test_reconnect_tier(self, elapsed: float) -> None:
        assert watchdog_action(elapsed) is WatchdogAction.RECONNECT


class TestReconnectBackoffSeconds:
    def test_attempt_zero_is_within_min_and_double_min(self) -> None:
        rng = random.Random(1234)
        value = reconnect_backoff_seconds(0, rng)
        assert RECONNECT_BACKOFF_MIN_S <= value <= RECONNECT_BACKOFF_MIN_S * 2

    def test_grows_with_attempt_before_capping(self) -> None:
        # Full-jitter range widens monotonically until the cap: sample many
        # draws per attempt and compare maxima, which is robust to jitter.
        rng = random.Random(99)
        attempt1_samples = [reconnect_backoff_seconds(1, rng) for _ in range(200)]
        attempt3_samples = [reconnect_backoff_seconds(3, rng) for _ in range(200)]
        assert max(attempt3_samples) > max(attempt1_samples)
        assert min(attempt1_samples) >= RECONNECT_BACKOFF_MIN_S
        assert min(attempt3_samples) >= RECONNECT_BACKOFF_MIN_S

    def test_caps_at_max_for_large_attempt_counts(self) -> None:
        rng = random.Random(7)
        samples = [reconnect_backoff_seconds(20, rng) for _ in range(200)]
        assert max(samples) <= RECONNECT_BACKOFF_MAX_S
        assert min(samples) >= RECONNECT_BACKOFF_MIN_S
        # With the range fully saturated at the cap, samples should spread
        # across most of [MIN, MAX], not cluster near MIN as an uncapped
        # exponential would.
        assert max(samples) > RECONNECT_BACKOFF_MAX_S * 0.5

    def test_deterministic_with_seeded_random(self) -> None:
        expected = random.Random(42).uniform(
            RECONNECT_BACKOFF_MIN_S,
            min(RECONNECT_BACKOFF_MAX_S, RECONNECT_BACKOFF_MIN_S * 2**2),
        )
        actual = reconnect_backoff_seconds(2, random.Random(42))
        assert actual == pytest.approx(expected)
