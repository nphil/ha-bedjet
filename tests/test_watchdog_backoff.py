"""Tests for the pure watchdog-tier, reconnect-backoff and drop-window logic.

All three are plain functions of elapsed-seconds / attempt-count / timestamps
so the 60s/300s/900s watchdog tiers, the 1-2-5-10-30-60s reconnect schedule
and the trailing-hour drop count are provable without any real-time sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime
import random

import pytest

from custom_components.bedjet.pybedjet import (
    DropTracker,
    WatchdogAction,
    reconnect_backoff_seconds,
    watchdog_action,
)

SCHEDULE = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
JITTER = 0.2


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
    @pytest.mark.parametrize(("attempt", "base"), list(enumerate(SCHEDULE)))
    def test_each_attempt_stays_within_jitter_of_its_scheduled_delay(
        self, attempt: int, base: float
    ) -> None:
        rng = random.Random(1234)
        samples = [reconnect_backoff_seconds(attempt, rng) for _ in range(200)]
        assert min(samples) >= base * (1 - JITTER)
        assert max(samples) <= base * (1 + JITTER)

    @pytest.mark.parametrize("attempt", [len(SCHEDULE), 20, 10_000])
    def test_saturates_at_the_last_scheduled_delay_and_never_gives_up(
        self, attempt: int
    ) -> None:
        # The hold is meant to be permanent: past the end of the schedule the
        # supervisor keeps retrying at ~60s forever rather than growing the
        # delay without bound.
        rng = random.Random(7)
        samples = [reconnect_backoff_seconds(attempt, rng) for _ in range(100)]
        assert min(samples) >= SCHEDULE[-1] * (1 - JITTER)
        assert max(samples) <= SCHEDULE[-1] * (1 + JITTER)

    def test_jitter_actually_spreads_retries(self) -> None:
        # Several devices reconnecting after one proxy reboot must not retry
        # in lockstep, so the delay may not be a constant.
        rng = random.Random(3)
        samples = [reconnect_backoff_seconds(2, rng) for _ in range(200)]
        assert max(samples) - min(samples) > SCHEDULE[2] * JITTER

    def test_deterministic_with_seeded_random(self) -> None:
        expected = SCHEDULE[2] * random.Random(42).uniform(1 - JITTER, 1 + JITTER)
        actual = reconnect_backoff_seconds(2, random.Random(42))
        assert actual == pytest.approx(expected)


class TestDropTracker:
    def test_counts_only_drops_inside_the_trailing_window(self) -> None:
        tracker = DropTracker(window_s=3600.0)
        when = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)
        tracker.record(1_000.0, when)
        tracker.record(2_000.0, when)

        assert tracker.count(2_000.0) == 2
        # 1_000.0 has aged out of the hour, 2_000.0 has not.
        assert tracker.count(4_700.0) == 1
        assert tracker.count(5_700.0) == 0

    def test_last_drop_survives_the_window_it_aged_out_of(self) -> None:
        tracker = DropTracker(window_s=60.0)
        when = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)
        tracker.record(100.0, when)

        assert tracker.count(10_000.0) == 0
        assert tracker.last_drop == when

    def test_no_drops_yet_reports_zero_and_none(self) -> None:
        tracker = DropTracker()
        assert tracker.count(12_345.0) == 0
        assert tracker.last_drop is None

    def test_last_drop_is_the_most_recent_one(self) -> None:
        tracker = DropTracker()
        first = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)
        second = datetime(2026, 9, 8, 3, 30, tzinfo=UTC)
        tracker.record(100.0, first)
        tracker.record(200.0, second)
        assert tracker.last_drop == second
