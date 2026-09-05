"""Shared test setup.

Installs the Home Assistant stubs (when real HA is absent) *before* any test
module imports ``custom_components``, and exposes byte-level fixtures built
from the two real BedJet V3 notify/tail captures recorded live against the
physical device (see the project brief's "Ground truth" section) plus the
ESPHome ``bedjet`` component's field tables, which are the protocol oracle.

NEVER hand-edit the ground-truth hex blobs below to make a test pass: if a
byte offset looks wrong, re-derive it from
https://github.com/esphome/esphome/tree/dev/esphome/components/bedjet instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ha_stubs  # noqa: E402

HA_STUBBED = ha_stubs.install()

# --- Real captures (live BedJet V3, 2026-09-05) -----------------------------
# 20-byte partial notify frame from char ...2000: standby, 25.0C outlet temp,
# 40C target, fan step 0, 24.5C ambient.
STANDBY_NOTIFY_HEX = "01561b0100000032500000000014500000310012"

# 11-byte tail, read from char ...2000 at global offsets 20..30, matching the
# STANDBY_NOTIFY_HEX capture above: conn_test_passed + units_setup +
# beeps_muted set, LEDs off, update_phase=0x15, notification=CLEAN_FILTER(1).
STANDBY_TAIL_HEX = "01990100ff00152500018f"


def frame_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


@pytest.fixture
def standby_notify() -> bytes:
    return frame_bytes(STANDBY_NOTIFY_HEX)


@pytest.fixture
def standby_tail() -> bytes:
    return frame_bytes(STANDBY_TAIL_HEX)


def build_notify_frame(
    *,
    is_partial: int = 1,
    packet_format: int = 0x56,
    expecting_length: int = 0x1B,
    packet_type: int = 0x01,
    time_remaining_hrs: int = 0,
    time_remaining_mins: int = 0,
    time_remaining_secs: int = 0,
    actual_temp_step: int = 50,
    target_temp_step: int = 80,
    mode: int = 0,
    fan_step: int = 0,
    max_hrs: int = 0,
    max_mins: int = 0,
    min_temp_step: int = 20,
    max_temp_step: int = 80,
    turbo_time: int = 0,
    ambient_temp_step: int = 49,
    shutdown_reason: int = 0,
    trailing_byte: int = 0x12,
) -> bytes:
    """Build a synthetic 20-byte notify frame from the ESPHome field map.

    Field map (index -> meaning), as read by BedjetCodec::decode_notify /
    BedjetStatusPacket (esphome/components/bedjet/bedjet_codec.{h,cpp}):
      [0]     is_partial
      [1]     packet_format (0x56 == PACKET_FORMAT_V3_HOME)
      [2]     expecting_length
      [3]     packet_type (0x01 == PACKET_TYPE_STATUS)
      [4:7]   time remaining hrs/mins/secs
      [7]     actual_temp_step (C * 2)
      [8]     target_temp_step (C * 2)
      [9]     mode
      [10]    fan_step (0-19)
      [11:13] max_hrs/max_mins
      [13]    min_temp_step (C * 2)
      [14]    max_temp_step (C * 2)
      [15:17] turbo_time, little-endian u16
      [17]    ambient_temp_step (C * 2)
      [18]    shutdown_reason
      [19]    first byte of the tail continuation (opaque here)
    """
    turbo_lo = turbo_time & 0xFF
    turbo_hi = (turbo_time >> 8) & 0xFF
    return bytes(
        [
            is_partial,
            packet_format,
            expecting_length,
            packet_type,
            time_remaining_hrs,
            time_remaining_mins,
            time_remaining_secs,
            actual_temp_step,
            target_temp_step,
            mode,
            fan_step,
            max_hrs,
            max_mins,
            min_temp_step,
            max_temp_step,
            turbo_lo,
            turbo_hi,
            ambient_temp_step,
            shutdown_reason,
            trailing_byte,
        ]
    )


def build_tail(
    *,
    byte20: int = 0x01,
    byte21: int = 0x99,
    dual_zone_flags: int = 0x01,
    byte23: int = 0x00,
    byte24: int = 0xFF,
    byte25: int = 0x00,
    update_phase: int = 0x15,
    flags_packed: int = 0x25,
    bio_sequence_step: int = 0x00,
    notify_code: int = 0x01,
) -> bytes:
    """Build a synthetic 11-byte tail (global offsets 20..30).

    Field map, derived from BedjetStatusPacket and the live capture in
    STANDBY_TAIL_HEX:
      [20]  unused_1
      [21]  unused_2
      [22]  dual_zone_flags (bit 0x02 == is_dual_zone)
      [23]  unused_3
      [24]  unused_4
      [25]  unused_5
      [26]  update_phase
      [27]  flags_packed: 0x20 conn_test_passed, 0x10 leds_enabled,
            0x04 units_setup, 0x01 beeps_muted
      [28]  bio_sequence_step
      [29]  notify_code (BedJetNotification)
    """
    return bytes(
        [
            byte20,
            byte21,
            dual_zone_flags,
            byte23,
            byte24,
            byte25,
            update_phase,
            flags_packed,
            bio_sequence_step,
            notify_code,
            0x8F,  # [30]: unused_7 low byte, unread by any decoded field
        ]
    )


@pytest.fixture
def notify_builder():
    return build_notify_frame


@pytest.fixture
def tail_builder():
    return build_tail
