"""BedJet V3 protocol codec: pure frame/tail decoding and command encoding.

This module has no I/O, no asyncio, and no bleak imports. Every function is a
pure transformation of bytes <-> :class:`BedJetState` / bytes, so it can be
exercised without a device, a scanner, or an event loop.

Provenance
==========
Field offsets, opcodes, and validation ranges are taken from ESPHome's own
BedJet component - the only actively-maintained, community-verified BedJet V3
protocol implementation - fetched from
``github.com/esphome/esphome/dev/esphome/components/bedjet/`` (``dev`` branch)
on 2026-09-05:

    - bedjet_const.h   (opcodes, buttons, modes, fan-step<->percent formula)
    - bedjet_codec.h   (BedjetStatusPacket struct layout, BedjetPacket command
                        struct, BedjetNotification enum)
    - bedjet_codec.cpp (encoders, decode_notify validation, debug-packet
                        ambient patch, meaningful-change compare())
    - bedjet_hub.h     (notify-throttle / status-timeout constants)
    - bedjet_hub.cpp   (how those constants and compare() are actually used)

Every citation below is ``file:line`` against that snapshot. Anything not
directly backed by an ESPHome citation is marked ``[INFERENCE]`` and explains
its own reasoning - either because ESPHome does not implement that part of
the protocol at all (bio-data name reads, LED/mute/biorhythm buttons, the
proactive status probe) or because it is a Python-level design decision with
no C++ analogue (when to re-read the tail, what counts as a "meaningful"
change worth publishing immediately).

Status notify frame (20 bytes, characteristic ...2000, notify)
================================================================
BedJet V3 pushes ~4 notifications/second on this characteristic, even in
standby. Layout is ``BedjetStatusPacket`` (bedjet_codec.h:38-126), copied
verbatim into a 20-byte notification because a single BLE notification can't
carry the full ~32-byte struct (doc comment, bedjet_codec.h:136-139); the
remaining 11 bytes ("tail") are fetched with a plain characteristic read -
see the next section.

====== ==================== =========================== ========================================
Offset Field                ESPHome citation            Notes
====== ==================== =========================== ========================================
0      is_partial           bedjet_codec.h:40           1 = more data readable via plain GATT read
1      packet_format        bedjet_codec.h:42,17-18     0x56 = V3_HOME status, 0x05 = DEBUG
2      expecting_length     bedjet_codec.h:44           total length after merge; not decoded here
3      packet_type          bedjet_codec.h:45,22-23     0x01 = STATUS, 0x02 = DEBUG
4      time_remaining_hrs   bedjet_codec.h:48
5      time_remaining_mins  bedjet_codec.h:49
6      time_remaining_secs  bedjet_codec.h:50
7      actual_temp_step     bedjet_codec.h:53           degrees_C = step / 2
8      target_temp_step     bedjet_codec.h:55           degrees_C = step / 2
9      mode                 bedjet_codec.h:58,19-31     BedjetMode 0-6
10     fan_step             bedjet_codec.h:61           percent = 5*step + 5 (bedjet_const.h:13)
11     max_hrs              bedjet_codec.h:63
12     max_mins             bedjet_codec.h:64
13     min_temp_step        bedjet_codec.h:65           per-mode limit; not used as entity bounds
14     max_temp_step        bedjet_codec.h:66           (see "Design notes" below)
15-16  turbo_time           bedjet_codec.h:69           uint16, little-endian (see "bug fix" below)
17     ambient_temp_step    bedjet_codec.h:72           degrees_C = step / 2; see "debug ambient patch"
18     shutdown_reason      bedjet_codec.h:74           opaque code, no ESPHome table
19     (unused)             bedjet_codec.h:76-78        first byte of the tail region; not decoded
====== ==================== =========================== ========================================

Validation (bedjet_codec.cpp:112-114, function ``decode_notify``): a frame is
accepted only if ``mode < 7 and 38 <= target_temp_step <= 86 and
1 < actual_temp_step <= 100 and 1 < ambient_temp_step <= 100``. Anything else
raises :class:`BedJetFrameError` here. [INFERENCE] ESPHome instead nulls out
its cached status and logs a warning (bedjet_codec.cpp:119); this module
deliberately does *not* discard the caller's last-known-good state on a bad
frame - the caller keeps serving the last valid :class:`BedJetState` and logs
the rejection, since one corrupt frame out of ~4/second must never flap every
entity to unavailable.

**Bug fix - turbo_time endianness**: ``BedjetStatusPacket`` is a
``__attribute__((packed))`` C struct (bedjet_codec.h:126) filled by
``memcpy`` from the raw notification bytes (bedjet_codec.cpp:108) on an ESP32
(Xtensa/RISC-V), which is little-endian. A ``uint16_t turbo_time : 16``
bitfield populated that way from bytes ``[15, 16]`` is therefore
``data[15] | (data[16] << 8)`` - little-endian. The prior version of this
library decoded it big-endian (``int.from_bytes(data[15:17], "big")``), which
only happens to be correct while the high byte is zero (turbo_time < 256s);
fixed here.

**Debug-format ambient patch** (bedjet_codec.cpp:96,123-134, function
``decode_notify``): when a frame's format is 0x05 (``PACKET_FORMAT_DEBUG``,
bedjet_codec.h:17) OR its type is 0x02 (``PACKET_TYPE_DEBUG``,
bedjet_codec.h:23), it is not a status frame - ESPHome does not know its
layout ("We don't actually know the packet format for this.",
bedjet_codec.cpp:125) except that byte 6 carries a more precise ambient
reading, which it patches directly onto the *existing* decoded status
(``this->status_packet_->ambient_temp_step = data[6]``, bedjet_codec.cpp:134).
Nothing else in the frame is touched. ``decode_frame`` reproduces this:
given ``previous is not None``, it returns ``replace(previous,
ambient_temp_c=data[6] / 2.0, raw=bytes(data))``. A debug frame with no
``previous`` raises :class:`BedJetFrameError` (nothing to patch onto -
ESPHome's equivalent guard is ``has_status()``, bedjet_codec.cpp:133).

Tail (11 bytes, characteristic ...2000, plain read, global offsets 20-30)
================================================================
``BedjetStatusPacket`` continues past the 20-byte notification
(bedjet_codec.h:76: "the initial partial packet cuts off here after [19]").
ESPHome fetches the rest with a plain characteristic read whenever
``decode_notify`` returns ``true`` (i.e. ``is_partial``)
(bedjet_hub.cpp:378-390) and merges it at the byte offset the notification
stopped at (``decode_extra``, bedjet_codec.cpp:70-86, ``offset =
this->last_buffer_size_``). Since the notification is always 20 bytes for a
V3, the tail always starts at global offset 20; ``merge_tail(state, tail)``
takes that 11-byte read directly (``tail[0]`` is global offset 20) and only
decodes what ESPHome's struct documents from that point on:

======== ============== ================= ======================== ===============================================
tail idx global offset  Field             ESPHome citation         Bit / notes
======== ============== ================= ======================== ===============================================
2        22             dual_zone_flags   bedjet_codec.h:82-92     bit 0x02 = is_dual_zone
6        26             update_phase      bedjet_codec.h:98-101    opaque phase code
7        27             flags             bedjet_codec.h:103-117   0x20 conn_test_passed, 0x10 leds_enabled,
                                                                    0x04 units_setup, 0x01 beeps_muted
8        28             bio_sequence_step bedjet_codec.h:119-120
9        29             notify_code       bedjet_codec.h:121-122   BedJetNotification
======== ============== ================= ======================== ===============================================

Verified against a live capture (ground truth, 2026-09-05): tail bytes
``01990100ff00152500018f`` decode to dual_zone=False (``0x01 & 0x02 == 0``),
update_phase=0x15, flags=0x25 -> conn_test_passed+units_setup+beeps_muted
set, leds_enabled clear, bio_sequence_step=0, notify_code=1 (CLEAN_FILTER) -
exactly matches this table and the base fork's pre-existing (correct) tail
offsets.

All eight tail-derived ``BedJetState`` fields (``notification``,
``update_phase``, ``leds_enabled``, ``beeps_muted``, ``units_setup``,
``connection_test_passed``, ``dual_zone``, ``bio_sequence_step``) are
``None`` until the first successful ``merge_tail``, and then persist across
subsequent plain ``decode_frame`` calls (which never touch them) until the
next ``merge_tail`` call - see the Contract's "None until tail known".

*When* the tail is (re)read is a connection-lifecycle decision, not a codec
decision - see ``pybedjet/__init__.py``'s tail-refresh logic. [INFERENCE] The
15-second staleness threshold used there is ESPHome's own notify-processing
throttle, ``MIN_NOTIFY_THROTTLE = 15000`` ms (bedjet_hub.h:147), reused here
for the same purpose: ESPHome refreshes its whole decoded packet (tail
included) at that same cadence unless something changed sooner
(bedjet_hub.cpp:378).

Command encoding (characteristic ...2004, write-without-response)
================================================================
``write_bedjet_packet_`` writes exactly ``data_length + 1`` bytes - the
command byte followed by ``data_length`` payload bytes, never padded
(bedjet_hub.cpp:134-136: ``pkt->data_length + 1, (uint8_t *) &pkt->command``,
``ESP_GATT_WRITE_TYPE_NO_RSP``). ``build_command`` reproduces this exactly
and additionally validates every input against the device's accepted range,
raising ``ValueError`` (a caller bug, not a protocol/connection failure) if
violated:

=============  ======  ================================================ ========================== ============ ====================================================
BedJetCommand  opcode  ESPHome citation                                 args (natural units)        wire bytes   encoding
=============  ======  ================================================ ========================== ============ ====================================================
BUTTON         0x01    bedjet_const.h:85; bedjet_codec.cpp:29-31        button: BedJetButton        [01,btn]     passthrough
SET_RUNTIME    0x02    bedjet_const.h:86; bedjet_codec.cpp:62-67        hours: int, minutes: int    [02,h,m]     passthrough, 0<=hours<=255, 0<=minutes<=59
SET_TEMP       0x03    bedjet_const.h:87; bedjet_codec.cpp:37-41        temperature_c: float        [03,raw]     raw=round(c*2), validated 38<=raw<=86 (codec.cpp:112)
STATUS         0x06    bedjet_const.h:88                                (none)                      [06]         [INFERENCE] see note below
SET_FAN        0x07    bedjet_const.h:89; bedjet_codec.cpp:45-49        fan_percent: int             [07,step]    step=percent//5-1 (const.h:15), 5<=percent<=100, %5==0
SET_CLOCK      0x08    bedjet_const.h:90; bedjet_codec.cpp:53-58        hour: int, minute: int      [08,h,m]     validated 0<=hour<=23, 0<=minute<=59
GET_BIO        0x41    [INFERENCE] not in ESPHome at all                bio_type: BioDataRequest,   [41,t,tag]   kept per assignment carve-out (ESPHome lacks this)
                                                                         tag: int
=============  ======  ================================================ ========================== ============ ====================================================

STATUS (0x06) [INFERENCE]: the opcode itself is declared by ESPHome
(bedjet_const.h:88) but is never sent anywhere in ESPHome's own hub/codec -
there is no ``get_status_request()`` on ``BedjetCodec`` and nothing in
``bedjet_hub.cpp`` writes ``CMD_STATUS``. ESPHome relies purely on the
passive notify subscription. This library adds an explicit, zero-payload
probe (``[0x06]``) as a watchdog nudge per the ground truth ("Still keep
CMD_STATUS (0x06) as an explicit probe"); zero data bytes is the natural
reading of a parameterless "request".

``SET_STEP`` (0x04) and ``SET_HACKS`` (0x05), present in the prior fork's
``const.py`` but referenced nowhere in ESPHome, the ground-truth opcode
table, or any caller anywhere in this fork, have been removed as
unverified/invented protocol surface - "nothing beyond these tables may be
sent to the device." ``SET_BIO`` (0x40) is removed for the same reason
(declared, never used, never verified); only ``GET_BIO`` reads are kept, per
the explicit bio-data carve-out.

Buttons: ``BedJetButton`` is unchanged from the prior fork. OFF/COOL/HEAT/
TURBO/DRY/EXTENDED_HEAT/M1/M2/M3/DEBUG_ON/DEBUG_OFF/CONNECTION_TEST/
UPDATE_FIRMWARE/NOTIFY_ACK all match ESPHome's ``BedjetButton``
(bedjet_const.h:52-81) byte-for-byte. LED_ON/LED_OFF/MUTE/UNMUTE/
BIORHYTHM_1/2/3 have no ESPHome citation (that component implements neither
LED, mute, nor biorhythm-start control) but are kept per the ground truth,
which explicitly lists them as real, additional protocol knowledge the base
fork has beyond ESPHome's.

Meaningful-change detection
================================================================
ESPHome's own ``BedjetCodec::compare()`` (bedjet_codec.cpp:144-169) decides
whether an incoming notification is worth decoding early, bypassing its
15-second throttle, by checking only ``mode``, ``fan_step``, and
``target_temp_step`` (bedjet_codec.cpp:167) - deliberately excluding
ambient/actual temperature because "those are environmental"
(bedjet_codec.cpp:164-166). ``is_meaningful_change`` [INFERENCE] extends that
same idea to gate how the *connection-lifecycle* layer fans out updates to
listeners (not how often frames are decoded - decoding every frame is cheap
in Python and happens every time regardless): ``mode``, ``fan_step``,
``target_temp_c``, ``notification``, and every tail-derived flag
(``leds_enabled``, ``beeps_muted``, ``units_setup``,
``connection_test_passed``, ``dual_zone``, ``bio_sequence_step``,
``update_phase``) are "meaningful" and publish immediately; actual/ambient
temperature are the only continuous fields, left for the connection layer's
2-second listener rate limit.

Design notes (Python-level, no ESPHome citation)
================================================================
- ``raw`` reflects the bytes of whichever frame most recently produced this
  ``BedJetState`` (a status frame, or a debug-ambient patch) - a diagnostic
  convenience, not a protocol fact.
- ``min_temp_c``/``max_temp_c`` are decoded and exposed for diagnostics, but
  per the Contract must never be used as HA climate entity bounds (upstream
  issue #61 was repeated churn from doing exactly that); the climate entity
  uses static 19-43C bounds instead.
- ``BedJetNotification`` stays a plain ``Enum`` (not ``IntEnum``): several
  callers test ``if state.notification:`` to distinguish "not yet known"
  (``None``) from "known, no active notification" (``BedJetNotification.NONE``,
  value 0). A plain ``Enum`` member is always truthy regardless of its
  value; an ``IntEnum`` member with value 0 would be falsy and collapse that
  distinction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from .const import BedJetButton, BedJetCommand, BedJetMode, BedJetNotification

# BedjetPacketFormat, bedjet_codec.h:16-19
PACKET_FORMAT_V3_HOME = 0x56
PACKET_FORMAT_DEBUG = 0x05

# BedjetPacketType, bedjet_codec.h:21-24
PACKET_TYPE_STATUS = 0x01
PACKET_TYPE_DEBUG = 0x02

# Device-enforced target temperature range, raw step units (bedjet_codec.cpp:112).
TEMP_STEP_MIN = 38
TEMP_STEP_MAX = 86

# Fan step range, bedjet_hub.h:58 (`fan_speed_index > 19` is rejected).
FAN_STEP_MIN = 0
FAN_STEP_MAX = 19

# Minimum tail-read length needed to decode every known field (through local
# index 9 / global offset 29); real reads are 11 bytes.
TAIL_MIN_LENGTH = 10


class BedJetFrameError(Exception):
    """A notification or tail read could not be decoded into a BedJetState."""


@dataclass(frozen=True)
class BedJetState:
    """A fully- or partially-known decoded BedJet V3 status.

    See the module docstring for the byte-level provenance of every field.
    """

    mode: BedJetMode
    target_temp_c: float
    actual_temp_c: float
    ambient_temp_c: float
    fan_step: int
    fan_percent: int
    time_remaining: timedelta
    max_runtime: timedelta
    min_temp_c: float
    max_temp_c: float
    turbo_time: int
    shutdown_reason: int
    notification: BedJetNotification | None
    update_phase: int | None
    leds_enabled: bool | None
    beeps_muted: bool | None
    units_setup: bool | None
    connection_test_passed: bool | None
    dual_zone: bool | None
    bio_sequence_step: int | None
    is_partial: bool
    raw: bytes


def decode_frame(data: bytes, previous: BedJetState | None) -> BedJetState:
    """Decode one notification from characteristic ...2000.

    `data` is normally 20 bytes (the BedJet V3 notification length). `previous` is
    the last successfully decoded state, if any; it supplies the tail-derived
    fields a plain notification never carries (see module docstring), and is
    required to make sense of a debug-format ambient patch. Raises
    `BedJetFrameError` if the frame is too short, of an unrecognized
    format/type, fails ESPHome's numeric validation, or is a debug patch with
    no `previous` to patch onto.
    """
    if len(data) < 5:
        raise BedJetFrameError(f"frame too short: {len(data)} bytes (need >= 5)")

    packet_format = data[1]
    packet_type = data[3]

    if packet_format == PACKET_FORMAT_DEBUG or packet_type == PACKET_TYPE_DEBUG:
        # bedjet_codec.cpp:123-134: patches ambient onto the existing status only.
        if previous is None:
            raise BedJetFrameError("debug frame received before any status frame")
        if len(data) < 7:
            raise BedJetFrameError(f"debug frame too short: {len(data)} bytes (need >= 7)")
        return replace(previous, ambient_temp_c=data[6] / 2.0, raw=bytes(data))

    if packet_format != PACKET_FORMAT_V3_HOME or packet_type != PACKET_TYPE_STATUS:
        raise BedJetFrameError(
            f"unrecognized frame: format=0x{packet_format:02x} type=0x{packet_type:02x}"
        )
    if len(data) < 19:
        raise BedJetFrameError(f"status frame too short: {len(data)} bytes (need >= 19)")

    mode_raw = data[9]
    target_temp_step = data[8]
    actual_temp_step = data[7]
    ambient_temp_step = data[17]

    # bedjet_codec.cpp:112-114
    if not (
        mode_raw < 7
        and TEMP_STEP_MIN <= target_temp_step <= TEMP_STEP_MAX
        and 1 < actual_temp_step <= 100
        and 1 < ambient_temp_step <= 100
    ):
        raise BedJetFrameError(
            "frame failed validation: "
            f"mode={mode_raw} target_step={target_temp_step} "
            f"actual_step={actual_temp_step} ambient_step={ambient_temp_step}"
        )

    fan_step = data[10]
    # bedjet_codec.h:69; little-endian on ESP32 - see module docstring "bug fix".
    turbo_time = int.from_bytes(data[15:17], byteorder="little")

    return BedJetState(
        mode=BedJetMode(mode_raw),
        target_temp_c=target_temp_step / 2.0,
        actual_temp_c=actual_temp_step / 2.0,
        ambient_temp_c=ambient_temp_step / 2.0,
        fan_step=fan_step,
        fan_percent=5 * fan_step + 5,  # bedjet_const.h:13
        time_remaining=timedelta(hours=data[4], minutes=data[5], seconds=data[6]),
        max_runtime=timedelta(hours=data[11], minutes=data[12]),
        min_temp_c=data[13] / 2.0,
        max_temp_c=data[14] / 2.0,
        turbo_time=turbo_time,
        shutdown_reason=data[18],
        notification=previous.notification if previous is not None else None,
        update_phase=previous.update_phase if previous is not None else None,
        leds_enabled=previous.leds_enabled if previous is not None else None,
        beeps_muted=previous.beeps_muted if previous is not None else None,
        units_setup=previous.units_setup if previous is not None else None,
        connection_test_passed=previous.connection_test_passed if previous is not None else None,
        dual_zone=previous.dual_zone if previous is not None else None,
        bio_sequence_step=previous.bio_sequence_step if previous is not None else None,
        is_partial=bool(data[0]),
        raw=bytes(data),
    )


def merge_tail(state: BedJetState, tail: bytes) -> BedJetState:
    """Merge an 11-byte plain read of characteristic ...2000 into `state`.

    `tail[0]` is global offset 20 (see module docstring). Raises
    `BedJetFrameError` if `tail` is too short to decode every known field, or
    if the notification byte is not a recognized `BedJetNotification`.
    """
    if len(tail) < TAIL_MIN_LENGTH:
        raise BedJetFrameError(f"tail too short: {len(tail)} bytes (need >= {TAIL_MIN_LENGTH})")

    dual_zone_flags = tail[2]  # global offset 22; bedjet_codec.h:82-92
    update_phase = tail[6]  # global offset 26; bedjet_codec.h:98-101
    flags = tail[7]  # global offset 27; bedjet_codec.h:103-117
    bio_sequence_step = tail[8]  # global offset 28; bedjet_codec.h:119-120
    notify_code = tail[9]  # global offset 29; bedjet_codec.h:121-122

    try:
        notification = BedJetNotification(notify_code)
    except ValueError as err:
        raise BedJetFrameError(f"unrecognized notification code: {notify_code}") from err

    return replace(
        state,
        dual_zone=bool(dual_zone_flags & 0x02),
        update_phase=update_phase,
        connection_test_passed=bool(flags & 0x20),
        leds_enabled=bool(flags & 0x10),
        units_setup=bool(flags & 0x04),
        beeps_muted=bool(flags & 0x01),
        bio_sequence_step=bio_sequence_step,
        notification=notification,
    )


def is_meaningful_change(previous: BedJetState | None, current: BedJetState) -> bool:
    """Return True if `current` differs from `previous` in a way worth publishing immediately.

    See module docstring "Meaningful-change detection". Actual/ambient
    temperature are deliberately excluded (continuous, environmental).
    """
    if previous is None:
        return True
    return (
        previous.mode != current.mode
        or previous.fan_step != current.fan_step
        or previous.target_temp_c != current.target_temp_c
        or previous.notification != current.notification
        or previous.leds_enabled != current.leds_enabled
        or previous.beeps_muted != current.beeps_muted
        or previous.units_setup != current.units_setup
        or previous.connection_test_passed != current.connection_test_passed
        or previous.dual_zone != current.dual_zone
        or previous.bio_sequence_step != current.bio_sequence_step
        or previous.update_phase != current.update_phase
    )


def build_command(command: BedJetCommand, *args: object) -> bytes:
    """Encode a command for characteristic ...2004 (write-without-response).

    Takes natural units (Celsius, percent, hour/minute) and performs ESPHome-
    equivalent encoding plus range validation; raises `ValueError` for a
    caller-supplied value the device cannot accept. See the module docstring
    "Command encoding" table for the exact opcode/encoding for each command.
    """
    match command:
        case BedJetCommand.BUTTON:
            (button,) = args
            return bytes((command, int(button)))

        case BedJetCommand.SET_RUNTIME:
            hours, minutes = args
            if not 0 <= hours <= 255:
                raise ValueError(f"runtime hours {hours!r} outside 0..255")
            if not 0 <= minutes <= 59:
                raise ValueError(f"runtime minutes {minutes!r} outside 0..59")
            return bytes((command, hours, minutes))

        case BedJetCommand.SET_TEMP:
            (temperature_c,) = args
            raw = round(temperature_c * 2)
            if not TEMP_STEP_MIN <= raw <= TEMP_STEP_MAX:
                raise ValueError(
                    f"temperature {temperature_c!r}C (raw {raw}) outside device range "
                    f"{TEMP_STEP_MIN / 2}..{TEMP_STEP_MAX / 2}C"
                )
            return bytes((command, raw))

        case BedJetCommand.STATUS:
            return bytes((command,))

        case BedJetCommand.SET_FAN:
            (fan_percent,) = args
            if fan_percent % 5 or not 5 <= fan_percent <= 100:
                raise ValueError(f"fan percent {fan_percent!r} must be a multiple of 5 in 5..100")
            step = fan_percent // 5 - 1
            return bytes((command, step))

        case BedJetCommand.SET_CLOCK:
            hour, minute = args
            if not 0 <= hour <= 23:
                raise ValueError(f"clock hour {hour!r} outside 0..23")
            if not 0 <= minute <= 59:
                raise ValueError(f"clock minute {minute!r} outside 0..59")
            return bytes((command, hour, minute))

        case BedJetCommand.GET_BIO:
            bio_type, tag = args
            return bytes((command, int(bio_type), int(tag)))

        case _:
            raise ValueError(f"unsupported command: {command!r}")
