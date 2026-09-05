"""Tests for pybedjet's pure codec: decode_frame, merge_tail, build_command.

Byte tables are cross-checked against the ESPHome ``bedjet`` component (the
protocol oracle - esphome/components/bedjet/bedjet_codec.{h,cpp} and
bedjet_const.h) and the two live captures recorded against the physical
BedJet V3 (see conftest.py). Nothing here invents protocol: every assertion
traces to one of those two sources.
"""

from __future__ import annotations

import pytest

from custom_components.bedjet.pybedjet import (
    BedJetButton,
    BedJetCommand,
    BedJetFrameError,
    BedJetMode,
    BedJetNotification,
    build_command,
    decode_frame,
    merge_tail,
)
from custom_components.bedjet.pybedjet.codec import is_meaningful_change


# --- decode_frame: real captures --------------------------------------------


class TestDecodeRealStandbyFrame:
    def test_fields_match_live_capture(self, standby_notify: bytes) -> None:
        state = decode_frame(standby_notify, None)

        assert state.is_partial is True
        assert state.mode is BedJetMode.STANDBY
        assert state.actual_temp_c == pytest.approx(25.0)
        assert state.target_temp_c == pytest.approx(40.0)
        assert state.fan_step == 0
        assert state.fan_percent == 5  # 5 * step + 5
        assert state.ambient_temp_c == pytest.approx(24.5)
        assert state.min_temp_c == pytest.approx(10.0)
        assert state.max_temp_c == pytest.approx(40.0)
        assert state.turbo_time == 0
        assert state.shutdown_reason == 0
        assert state.raw == standby_notify

    def test_tail_unknown_until_merged(self, standby_notify: bytes) -> None:
        state = decode_frame(standby_notify, None)
        for attr in (
            "leds_enabled",
            "beeps_muted",
            "units_setup",
            "connection_test_passed",
            "dual_zone",
        ):
            assert getattr(state, attr) is None
        assert state.notification is None
        assert state.update_phase is None
        assert state.bio_sequence_step is None


class TestMergeTailRealCapture:
    def test_flags_and_notification_match_live_capture(
        self, standby_notify: bytes, standby_tail: bytes
    ) -> None:
        state = decode_frame(standby_notify, None)
        merged = merge_tail(state, standby_tail)

        # tail flags byte 0x25 = 0b00100101:
        # conn_test_passed(0x20) + units_setup(0x04) + beeps_muted(0x01) set;
        # leds_enabled(0x10) clear.
        assert merged.connection_test_passed is True
        assert merged.units_setup is True
        assert merged.beeps_muted is True
        assert merged.leds_enabled is False
        assert merged.dual_zone is False  # tail[2]=0x01, bit 0x02 clear
        assert merged.update_phase == 0x15
        assert merged.bio_sequence_step == 0
        assert merged.notification is BedJetNotification.CLEAN_FILTER

    def test_merge_preserves_head_fields(
        self, standby_notify: bytes, standby_tail: bytes
    ) -> None:
        state = decode_frame(standby_notify, None)
        merged = merge_tail(state, standby_tail)

        assert merged.mode is state.mode
        assert merged.actual_temp_c == state.actual_temp_c
        assert merged.target_temp_c == state.target_temp_c
        assert merged.fan_step == state.fan_step


# --- decode_frame: turbo_time byte order ------------------------------------


def test_turbo_time_is_little_endian(notify_builder) -> None:
    frame = notify_builder(mode=2, turbo_time=0x1234)
    state = decode_frame(frame, None)
    assert state.turbo_time == 0x1234


def test_turbo_time_zero_low_byte(notify_builder) -> None:
    # Distinguishes LE from BE: 0x0034 only decodes correctly both ways when
    # low != high, so also check the case where the high byte alone is set.
    frame = notify_builder(mode=2, turbo_time=0x0500)
    state = decode_frame(frame, None)
    assert state.turbo_time == 0x0500


# --- decode_frame: validation (ESPHome's decode_notify gate) ----------------


class TestFrameValidation:
    @pytest.mark.parametrize("bad_mode", [7, 200])
    def test_rejects_mode_out_of_range(self, notify_builder, bad_mode: int) -> None:
        frame = notify_builder(mode=bad_mode)
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    @pytest.mark.parametrize("bad_target", [37, 87, 0])
    def test_rejects_target_temp_out_of_range(
        self, notify_builder, bad_target: int
    ) -> None:
        frame = notify_builder(target_temp_step=bad_target)
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    @pytest.mark.parametrize("boundary_target", [38, 86])
    def test_accepts_target_temp_at_boundaries(
        self, notify_builder, boundary_target: int
    ) -> None:
        frame = notify_builder(target_temp_step=boundary_target)
        decode_frame(frame, None)  # must not raise

    @pytest.mark.parametrize("bad_actual", [0, 1, 101])
    def test_rejects_actual_temp_out_of_range(
        self, notify_builder, bad_actual: int
    ) -> None:
        frame = notify_builder(actual_temp_step=bad_actual)
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    @pytest.mark.parametrize("bad_ambient", [0, 1, 101])
    def test_rejects_ambient_temp_out_of_range(
        self, notify_builder, bad_ambient: int
    ) -> None:
        frame = notify_builder(ambient_temp_step=bad_ambient)
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    def test_rejects_wrong_packet_format(self, notify_builder) -> None:
        frame = notify_builder(packet_format=0x05)  # PACKET_FORMAT_DEBUG
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    def test_rejects_wrong_packet_type(self, notify_builder) -> None:
        frame = notify_builder(packet_type=0x02)  # PACKET_TYPE_DEBUG
        with pytest.raises(BedJetFrameError):
            decode_frame(frame, None)

    def test_rejects_short_frame(self) -> None:
        with pytest.raises(BedJetFrameError):
            decode_frame(bytes([0x01, 0x56, 0x1B, 0x01]), None)


# --- build_command: byte-exact vs. the ESPHome opcode table -----------------


class TestBuildCommandButton:
    @pytest.mark.parametrize(
        ("button", "expected"),
        [
            (BedJetButton.OFF, bytes([0x01, 0x01])),
            (BedJetButton.COOL, bytes([0x01, 0x02])),
            (BedJetButton.HEAT, bytes([0x01, 0x03])),
            (BedJetButton.TURBO, bytes([0x01, 0x04])),
            (BedJetButton.DRY, bytes([0x01, 0x05])),
            (BedJetButton.EXTENDED_HEAT, bytes([0x01, 0x06])),
            (BedJetButton.M1, bytes([0x01, 0x20])),
            (BedJetButton.M2, bytes([0x01, 0x21])),
            (BedJetButton.M3, bytes([0x01, 0x22])),
            (BedJetButton.NOTIFY_ACK, bytes([0x01, 0x52])),
        ],
    )
    def test_button_bytes(self, button: BedJetButton, expected: bytes) -> None:
        assert build_command(BedJetCommand.BUTTON, button) == expected


class TestBuildCommandSetTemp:
    def test_40_celsius(self) -> None:
        assert build_command(BedJetCommand.SET_TEMP, 40.0) == bytes([0x03, 0x50])

    def test_min_boundary_19c(self) -> None:
        assert build_command(BedJetCommand.SET_TEMP, 19.0) == bytes([0x03, 38])

    def test_max_boundary_43c(self) -> None:
        assert build_command(BedJetCommand.SET_TEMP, 43.0) == bytes([0x03, 86])

    @pytest.mark.parametrize("celsius", [18.5, 43.5])
    def test_out_of_range_raises(self, celsius: float) -> None:
        with pytest.raises(ValueError):
            build_command(BedJetCommand.SET_TEMP, celsius)


class TestBuildCommandSetFan:
    def test_5_percent_is_step_zero(self) -> None:
        assert build_command(BedJetCommand.SET_FAN, 5) == bytes([0x07, 0x00])

    def test_100_percent_is_step_19(self) -> None:
        assert build_command(BedJetCommand.SET_FAN, 100) == bytes([0x07, 0x13])

    def test_50_percent_is_step_9(self) -> None:
        assert build_command(BedJetCommand.SET_FAN, 50) == bytes([0x07, 0x09])

    @pytest.mark.parametrize("percent", [0, 4, 101, 7])
    def test_invalid_percent_raises(self, percent: int) -> None:
        with pytest.raises(ValueError):
            build_command(BedJetCommand.SET_FAN, percent)


class TestBuildCommandClockAndRuntime:
    def test_set_clock(self) -> None:
        assert build_command(BedJetCommand.SET_CLOCK, 13, 45) == bytes([0x08, 13, 45])

    def test_set_runtime(self) -> None:
        assert build_command(BedJetCommand.SET_RUNTIME, 2, 30) == bytes(
            [0x02, 2, 30]
        )

    @pytest.mark.parametrize(("hour", "minute"), [(24, 0), (-1, 0)])
    def test_set_clock_invalid_hour_raises(self, hour: int, minute: int) -> None:
        with pytest.raises(ValueError):
            build_command(BedJetCommand.SET_CLOCK, hour, minute)

    @pytest.mark.parametrize(("hour", "minute"), [(0, 60), (0, -1)])
    def test_set_clock_invalid_minute_raises(self, hour: int, minute: int) -> None:
        with pytest.raises(ValueError):
            build_command(BedJetCommand.SET_CLOCK, hour, minute)


class TestBuildCommandStatus:
    def test_status_is_single_byte(self) -> None:
        assert build_command(BedJetCommand.STATUS) == bytes([0x06])


class TestBuildCommandFirmwareButton:
    def test_update_firmware_button_byte(self) -> None:
        assert build_command(BedJetCommand.BUTTON, BedJetButton.UPDATE_FIRMWARE) == bytes(
            [0x01, 0x43]
        )


class TestDebugFrameAmbientPatch:
    """decode_notify's debug-format branch (ESPHome bedjet_codec.cpp:123-134):
    patches only ambient_temp_c onto the existing status, from byte [6].
    """

    def test_patches_ambient_only_leaves_rest_untouched(self, standby_notify: bytes) -> None:
        previous = decode_frame(standby_notify, None)
        debug_frame = bytes([0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0x28])  # [6]=0x28 -> 20.0C

        patched = decode_frame(debug_frame, previous)

        assert patched.ambient_temp_c == pytest.approx(20.0)
        assert patched.mode == previous.mode
        assert patched.actual_temp_c == previous.actual_temp_c
        assert patched.target_temp_c == previous.target_temp_c
        assert patched.raw == debug_frame

    def test_debug_frame_without_prior_status_raises(self) -> None:
        debug_frame = bytes([0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0x28])
        with pytest.raises(BedJetFrameError):
            decode_frame(debug_frame, None)


class TestMergeTailValidation:
    def test_rejects_unrecognized_notification_code(
        self, standby_notify: bytes, tail_builder
    ) -> None:
        state = decode_frame(standby_notify, None)
        bad_tail = tail_builder(notify_code=0xFE)
        with pytest.raises(BedJetFrameError):
            merge_tail(state, bad_tail)

    def test_rejects_short_tail(self, standby_notify: bytes) -> None:
        state = decode_frame(standby_notify, None)
        with pytest.raises(BedJetFrameError):
            merge_tail(state, bytes(5))


class TestIsMeaningfulChange:
    """Pure gate the connection layer uses to decide immediate vs.
    rate-limited listener fan-out (mode/fan/target/notification/tail flags
    publish immediately; actual/ambient temperature do not gate on their own).
    """

    def test_first_state_after_none_is_always_meaningful(self, standby_notify: bytes) -> None:
        state = decode_frame(standby_notify, None)
        assert is_meaningful_change(None, state) is True

    def test_identical_state_is_not_meaningful(self, standby_notify: bytes) -> None:
        state = decode_frame(standby_notify, None)
        same = decode_frame(standby_notify, None)
        assert is_meaningful_change(state, same) is False

    def test_mode_change_is_meaningful(self, notify_builder) -> None:
        previous = decode_frame(notify_builder(mode=0), None)
        current = decode_frame(notify_builder(mode=1), None)
        assert is_meaningful_change(previous, current) is True

    def test_fan_step_change_is_meaningful(self, notify_builder) -> None:
        previous = decode_frame(notify_builder(fan_step=0), None)
        current = decode_frame(notify_builder(fan_step=5), None)
        assert is_meaningful_change(previous, current) is True

    def test_target_temp_change_is_meaningful(self, notify_builder) -> None:
        previous = decode_frame(notify_builder(target_temp_step=80), None)
        current = decode_frame(notify_builder(target_temp_step=82), None)
        assert is_meaningful_change(previous, current) is True

    def test_actual_or_ambient_temp_alone_is_not_meaningful(self, notify_builder) -> None:
        previous = decode_frame(notify_builder(actual_temp_step=50, ambient_temp_step=49), None)
        current = decode_frame(notify_builder(actual_temp_step=52, ambient_temp_step=51), None)
        assert is_meaningful_change(previous, current) is False

    def test_notification_change_is_meaningful(
        self, standby_notify: bytes, tail_builder
    ) -> None:
        state = decode_frame(standby_notify, None)
        previous = merge_tail(state, tail_builder(notify_code=0))
        current = merge_tail(state, tail_builder(notify_code=1))
        assert is_meaningful_change(previous, current) is True
