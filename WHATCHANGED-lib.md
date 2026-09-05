# WHATCHANGED - pybedjet library (LibLayer)

Scope: `custom_components/bedjet/pybedjet/` only (`__init__.py`, `const.py`, new
`codec.py`; `limiter.py` and `helpers.py` deleted). Does not touch any HA platform
file (HALayer, see `WHATCHANGED-ha.md`) or `tests/` (TestsCI-2). Credit lineage
preserved: robert-friedland -> asheliahut -> natekspencer -> nphil -> this rewrite.

Every fact below cited `file:line` is against ESPHome's `esphome/components/bedjet/`
(`dev` branch, fetched 2026-09-05): `bedjet_const.h`, `bedjet_codec.h`,
`bedjet_codec.cpp`, `bedjet_hub.h`, `bedjet_hub.cpp`. The full byte-level map with
every citation lives as the module docstring of `codec.py` - this document is the
bug/gap -> fix mapping, not a re-derivation of the protocol.

## New file: `codec.py`

Pure decode/merge/build functions with zero I/O, asyncio, or bleak imports -
verified by importing it directly via its file path with nothing but the stdlib
and `const.py` on `sys.path` (no bleak needed at all to decode a frame). Contains
the full frame/tail byte map and command-encoding table, every offset cited to
ESPHome, `[INFERENCE]` tags on everything ESPHome doesn't cover.

## Bug: `turbo_time` decoded big-endian, should be little-endian

**Before**: `int.from_bytes(data[15:17], byteorder="big")`.
**Root cause**: `BedjetStatusPacket` is a `__attribute__((packed))` C struct
(bedjet_codec.h:126) filled by `memcpy` (bedjet_codec.cpp:108) on an ESP32
(Xtensa/RISC-V - little-endian). A `uint16_t turbo_time : 16` bitfield
(bedjet_codec.h:69) populated that way from bytes `[15, 16]` is
`data[15] | (data[16] << 8)`. Big-endian decoding only happened to look right
while the high byte was zero (turbo_time < 256s).
**Fix**: `codec.decode_frame` uses `int.from_bytes(data[15:17], "little")`.
**Proof**: throwaway script decoded `turbo_time=0x012C` (bytes `2C 01`) as 300s;
the old big-endian read of the same bytes would have produced 11265s.

## Bug: validation ranges didn't match ESPHome's `decode_notify`

**Before**: no numeric validation of the notify payload at all - any bytes with
the right length were decoded and published, including transient corruption.
**Fix**: `decode_frame` now requires `mode < 7 and 38 <= target_temp_step <= 86
and 1 < actual_temp_step <= 100 and 1 < ambient_temp_step <= 100`
(bedjet_codec.cpp:112-114), raising `BedJetFrameError` otherwise. Deliberately
diverges from ESPHome in one place: ESPHome nulls out its cached status on a
bad frame (bedjet_codec.cpp:119); this library keeps serving the last known-good
`BedJetState` and only logs the rejection, since one corrupt frame out of ~4/sec
must never flap every entity to unavailable.

## Gap: debug-format ambient patch was never implemented

**Before**: no handling at all for `packet_format == 0x05` /
`packet_type == 0x02` frames; they would have failed the (nonexistent) length
check silently or been misdecoded as a garbage status frame.
**Fix**: `decode_frame` reproduces ESPHome's `decode_notify` special case
(bedjet_codec.cpp:96,123-134): a debug-format frame patches only
`ambient_temp_c` from byte 6 onto the *existing* state, touching nothing else.
Raises `BedJetFrameError` if there's no prior state to patch onto (verified by
throwaway script) rather than crashing on `previous.whatever`.

## Gap: tail (bytes 20-30) was read once at connect + once per external `update()` poll, not driven by `is_partial`

**Before**: `_read_device_status` was called from `_ensure_connected` (once,
at connect time) and from the old `update()` polling entry point - static
timing, decoupled from whether the tail had actually gone stale or a command
had just changed something the tail carries (LED/mute/notification/dual_zone/
etc. all live *only* in the tail, per bedjet_codec.h:76-124).
**Fix**: `BedJet._handle_notify` re-reads the tail whenever the frame is
`is_partial` **and** (older than `TAIL_MAX_AGE_S=15s` **or** a command just
completed). 15s mirrors ESPHome's own `MIN_NOTIFY_THROTTLE`
(bedjet_hub.h:147), reused for the same purpose (bedjet_hub.cpp:378). "A
command just completed" is tracked directly (`_tail_refresh_needed`, set right
after every `write_gatt_char` in `_run_command`) rather than relying on
incidentally detecting a mode/fan/target change the way ESPHome's
`compare()`-triggered `force_refresh_` does (bedjet_codec.cpp:167) - which
would have missed LED/mute changes entirely, since those never touch
mode/fan_step/target_temp_step. The read itself is a single tracked
`asyncio.Task` (`_tail_read_task`), never more than one in flight.

## Gap: no meaningful-change detection - existing tail-decode logic was otherwise already correct

Read carefully against the ground truth's live tail capture
(`01990100ff00152500018f`) before touching anything: the prior fork's bit
offsets/masks for `dual_zone` (bit 0x02 @ local index 2), `update_phase`
(local index 6), `conn_test_passed`/`leds_enabled`/`units_setup`/`beeps_muted`
(bits of local index 7), `bio_sequence_step` (local index 8), and
`notification` (local index 9) all independently matched ESPHome's struct
(bedjet_codec.h:82-122) exactly. Nothing there was broken; it has been ported
as-is into `merge_tail`, just restructured as a pure function operating on
the documented tail-only 11-byte read instead of inline bit-twiddling mixed
into connection code.
Added `is_meaningful_change` (`[INFERENCE]`, extends ESPHome's own
`compare()` idea, bedjet_codec.cpp:144-169, which only checks mode/fan_step/
target_temp_step): mode, fan_step, target_temp_c, notification, and every
tail-derived flag now gate *immediate* listener publish; actual/ambient
temperature are the only fields subject to the 2-second publish rate limit
(Constraints: "a continuous value may be rate-limited to 1 write/2s, but a
mode/fan/target/notification change publishes immediately"). Verified by
throwaway script: 1.75s of pure temperature jitter published exactly once
(the first frame), crossing 2s published again, and a mode change published
immediately even 50ms after the previous publish.

## Removed: BedJet V2 (ISSC) support

Out of scope per the assignment ("one BedJet V3"). Removed: `_is_v2`, all
`BEDJET2_*` UUIDs/constants, the V2 branches of every `set_*` method, V2
notification decoding (`_handle_v2_notification`), V2 packet wrapping/
checksumming in `_send_command`, and `helpers.py`'s `calculate_maximum_runtime`
lookup table (its own docstring said "this is for BedJet V2 only as BedJet 3
returns the maximum runtime in notifications" - dead code once V2 is gone;
`max_runtime` is decoded directly from frame bytes 11-12 for V3). Verified no
other file in the fork imported `helpers`/`limiter`/V2 symbols before deleting
(repo-wide grep).

## Removed: `limiter.py` (`TemperatureLimiter`, `EndTimeLimiter`)

Exactly the "per-value jitter limiter that hides real changes" the Contract
prohibits: it suppressed a temperature update unless it moved >=1.0C or 15s
had passed, and separately stabilized `run_end_time` similarly. Real fix
belongs at the listener-fan-out layer, not the decode layer (see
`is_meaningful_change` above) - a value it silently "corrected" from the
real device was, definitionally, not being reported to the user. Deleted;
`decode_frame` reports every field as decoded, unmodified, every time.
Announced to HALayer/TestsCI-2 via hub before deleting.

## Removed/renamed protocol surface not in the ground-truth tables

- `BedJetCommand.SET_STEP` (0x04) and `SET_HACKS` (0x05): declared in the
  prior fork's `const.py`, absent from ESPHome, absent from the ground
  truth's opcode table, and referenced by zero callers anywhere in this
  fork's history (verified by grep) - unverified/invented protocol surface,
  removed per "nothing beyond these tables may be sent to the device."
- `BedJetCommand.SET_BIO` (0x40): same reasoning - declared, never used,
  never verified. Only `GET_BIO` (0x41) reads are kept, per the explicit
  bio-data carve-out (see below).
- `BedJetCommand.SET_TEMPERATURE` renamed to `SET_TEMP` to match ESPHome's
  own `CMD_SET_TEMP` (bedjet_const.h:87) and the assignment's acceptance
  criteria wording.
- `OperatingMode` renamed to `BedJetMode` per the Contract's enum list.
- Characteristic `...2005` ("BIODATA", short) and `...2001`/`...2002`/`...2003`
  (device name / WiFi SSID / WiFi password) constants dropped: verified by
  grep that none of them were ever read from or written to anywhere in this
  fork's history. Only `...2006` (BIODATA_FULL) is actually exercised by any
  GET_BIO response.
- `BedJetButton` is **unchanged** - every member (including LED_ON/OFF,
  MUTE/UNMUTE, BIORHYTHM_1/2/3, which have no ESPHome citation) is kept,
  since the ground truth explicitly lists them as real additional knowledge
  this fork has beyond ESPHome's partial C++ port.

## Removed: `.name`/`.model`/`.firmware_version`/`.biorhythm1_name`.."3_name"`/`.is_v2`/`.rssi`/`is_data_stale`

None of these appear in the Contract's `BedJet` surface, and HALayer confirmed
(hub exchange) DeviceInfo is hardcoded (`model="BedJet 3"`, no firmware
reported) with no need for any of them. `_read_device_name`
(characteristic `...2001`) and the biorhythm-name/firmware GET_BIO reads
are removed entirely - not aliased, not left dead. Only the M1/M2/M3
memory-name read survives (see next section), since it is the one bio-read
the Contract's climate preset labels actually consume.

## Kept per explicit carve-out: M1/M2/M3 memory-name read (`GET_BIO`, `...2006`)

`[INFERENCE]`, absent from ESPHome entirely. Ported from
`_parse_bio_data_response`'s `"01"` (memory names) branch, confirmed correct
against `climate.py`'s already-written `getattr(device, key, None) or default`
consumption pattern (`m1_name`/`m2_name`/`m3_name`, no "M1: " prefix - a
small, intentional behavior improvement over the old code's literal `"M1: " +
name` and `"Default"` sentinel string, which now both correctly become `None`
so the HA layer's own "M1"/"M2"/"M3" fallback applies instead of showing the
word "Default"). Best-effort: 2 attempts, any failure logged at debug only,
never raises, never touches `state`.

## Rebuilt: connection lifecycle (all of `BedJet`'s async machinery)

- **`hold_connection`**: `True` (default) = single background supervisor task
  connects and maintains the link, reconnecting on advertisement sightings
  with full-jitter exponential backoff (2s doubling, capped 120s) on failure;
  `False` = disconnects immediately and the supervisor idles until re-enabled.
  This is the primitive `bluetooth_connection`'s switch entity (HALayer) is
  built on - the actual fix for "must disable the whole integration to free
  the slot for the phone app."
- **Single in-flight connect task**: one supervisor `asyncio.Task` loops
  forever; never spawns a second concurrent connect attempt. A failed attempt
  waits on `asyncio.Event` (advertisement/toggle/stop all set it) bounded by
  the backoff delay via `asyncio.timeout` - never a busy loop, never
  unbounded.
- **`establish_connection`** from `bleak_retry_connector` with
  `BleakClientWithServiceCache`, `use_services_cache=True`, and
  `ble_device_callback=lambda: self._ble_device` so a stale `BLEDevice`
  reference is re-resolved through whichever scanner/proxy currently sees the
  device, exactly as the prior fork already did (unchanged pattern, kept).
- **16-bit CCCD**: confirmed `bleak.BleakClient.start_notify()` performs a
  spec-correct 16-bit descriptor write on every backend already; the base's
  approach was already correct (plain `start_notify()`, no manual descriptor
  write). ESPHome's own `write_notify_config_descriptor_` workaround
  (bedjet_hub.cpp:420-434) exists only because ESP-IDF's raw
  `esp_ble_gattc`/ESPHome's `ble_client` writes 8 bits where the spec
  requires 16 - an ESP-IDF quirk with no bleak/Python equivalent. Documented
  in the module docstring since the Contract explicitly asked.
- **Command confirmation replaces every busy-wait**: the old
  `while self.state.operating_mode != mode: await asyncio.sleep(0.1)` pattern
  (present in `set_operating_mode`, both V2 and V3 branches) is gone. Every
  command now registers a `(predicate, asyncio.Future)` pair *before* writing
  (closes the race where a confirming frame arrives faster than the wait is
  set up), the notify/tail handlers resolve matching predicates on every
  frame, and `asyncio.timeout(5.0)` converts an unmet predicate into
  `BedJetCommandError`. `mode`/`temperature_c`/`fan_percent` check the exact
  corresponding field (temperature and fan compared via their raw
  integer/step representation, not float equality); `runtime` checks
  whole-minutes-remaining (seconds intentionally ignored - it is a live
  countdown, so exact-seconds confirmation would be flaky against network/
  decode latency); `led`/`mute` check their tail-derived boolean;
  `sync_clock`/`acknowledge_notification`/`press_button`/`request_status`/
  `request_firmware_update` resolve on the next valid frame (no single field
  uniquely identifies success for a raw button press or a status ping).
  `request_firmware_update` timing out after the unit reboots without another
  frame is an expected, honest outcome, not a bug - this call never assumes
  success it can't observe.
- **Watchdog** (`asyncio.sleep(WATCHDOG_TICK_S)` loop, never a busy-wait): a
  pure `watchdog_action(elapsed_s)` function decides NONE/PROBE/UNAVAILABLE/
  RECONNECT from elapsed-since-last-frame. 60s send `request_status()`
  (`[INFERENCE]`, opcode is ESPHome-declared but ESPHome itself never sends it
  - ground truth explicitly asked to keep it as a probe). 300s/900s directly
  mirror ESPHome's own `NOTIFY_WARN_THRESHOLD`/`DEFAULT_STATUS_TIMEOUT`
  (bedjet_hub.h:148-149) and how `dispatch_status_` actually uses them
  (bedjet_hub.cpp:534,538): "log a warning" -> fire the registered callback so
  HA re-checks `available` (a watchdog-detected stall with the link still
  technically connected would otherwise go unnoticed by HA, which only
  reacts to `register_callback` firing - confirmed necessary in a hub
  exchange with HALayer); "force a BLE reconnect" -> force a BLE reconnect.
  A fresh connection resets the "last positive signal" clock immediately
  (before the first frame even arrives) specifically to prevent the 900s tier
  from re-triggering every watchdog tick while the just-reconnected link is
  still waiting for its first notification.
- **Clean teardown**: `stop()` cancels the supervisor/watchdog/pending-release
  tasks, awaits them, then does a best-effort `stop_notify` + `disconnect`
  (`contextlib.suppress(BleakError, OSError, EOFError)` on both - a
  characteristic that's already gone or a socket that's already dead must
  never prevent shutdown). Idempotent: `self._client` is nulled
  synchronously before any `await`, so bleak's own disconnected-callback
  firing afterward is always a safe no-op, never a double-teardown.
- **Disconnect log severity**: downgraded from `WARNING` ("unexpectedly
  disconnected") to `DEBUG`. For this specific device, disconnecting whenever
  the phone app takes the slot is normal, frequent, expected operation, not
  an error condition - `WARNING` is reserved for the watchdog's genuine
  stall tiers now.
- **Clock sync**: `clock: Callable[[], datetime] | None` sent as `SET_CLOCK`
  right after every successful connect+subscribe, via the same confirmed
  `sync_clock()` a caller can invoke manually; a sync failure is logged and
  never blocks the rest of connect.
- **`scanner_source` fix before it shipped broken**: read `habluetooth`'s
  actual `BluetoothServiceInfoBleak` source (`.source` is a sibling field of
  `.advertisement`, not an attribute *on* it - a plain bleak
  `AdvertisementData` has no `.source` at all). Added an additive,
  keyword-only `source: str | None = None` to both the constructor and
  `set_ble_device_and_advertisement_data` rather than changing either
  method's documented required-arg shape; caught and fixed with HALayer
  before their call sites shipped with a permanently-`None` diagnostic
  field.

## Public surface

Exactly the Contract's list (`BedJet`, `BedJetState`, the four `const.py`
enums, `decode_frame`/`merge_tail`/`build_command`, the four exceptions), plus
these explicitly-announced, low-risk additions the Contract's prose didn't
enumerate but real callers need: `address` (every entity's `unique_id`/
`DeviceInfo` connection depends on it), `m1_name`/`m2_name`/`m3_name` (the
climate preset labels the Contract itself requires), `scanner_source`/
`last_frame_at` (both explicitly named in the Contract's property list),
`WatchdogAction`/`watchdog_action`/`reconnect_backoff_seconds`/
`is_meaningful_change` (pure, independently testable per TestsCI-2's request,
documented and announced before landing). Everything the base exposed that
isn't in one of those two groups (V2 support, `.name`/`.model`/
`.firmware_version`/`.biorhythm*_name`/`.is_v2`/`.rssi`/`.is_data_stale`/
`.led_enabled`-as-a-device-property/`.beeps_muted`-as-a-device-property/etc.,
`SET_STEP`/`SET_HACKS`/`SET_BIO`, `limiter.py`, `helpers.py`) was removed, not
aliased.

## Post-review hardening: two bugs found by deliberately breaking the test harness

While building the fake-BLE-client smoke tests, two real gaps in `__init__.py`
surfaced (not test bugs) and were fixed directly, then re-verified along with
the full existing test suite (no regressions):

1. **`_connect_supervisor`'s own failure handler could itself raise and kill
   the loop.** A broken `ble_device` (no `.address`) made the `except
   Exception as err:` block's own logging call (`self.address`) raise a
   *second* exception from inside the handler, which escaped the `try` and
   ended the `while` loop for good - "Never raises - must run for the
   lifetime of the client" was violated. A real `BLEDevice` always has
   `.address`, so this specific trigger cannot happen in production, but the
   invariant is load-bearing (there is no other path back to a connection)
   and cheap to make airtight regardless of the exact trigger: added an outer
   `try/except Exception` around the entire loop body that logs generically
   (without touching anything that could itself raise) and sleeps briefly
   before continuing. Verified with a fake device whose `.address` raises:
   the supervisor kept retrying (`_reconnect_attempt` climbing) instead of
   dying after the first iteration.
2. **The watchdog's PROBE tier blocked itself.** `request_status()` is a
   fully-confirmed command (awaits a matching frame, 5s timeout) - correct
   for the public API, but calling it *from the watchdog* meant every PROBE
   tick blocked the watchdog loop for up to `COMMAND_TIMEOUT_S` waiting for a
   frame that, by definition, is not arriving (that is why it is probing).
   The watchdog does not need to observe the probe's own outcome - if it
   wakes the device, the ordinary notify path updates `last_frame_at` on its
   own regardless. Added `_write_raw_command` (best-effort
   `write_gatt_char`, no confirmation future, no predicate) and pointed the
   watchdog's PROBE branch at it instead of the public method; `CMD_STATUS`
   is still written with the same bytes. `request_status()` itself is
   unchanged and stays fully confirmed. Verified by measuring wall-clock
   time from crossing into UNAVAILABLE territory to `available` actually
   flipping False: sub-second with the fix (would have needed 5+ real
   seconds if the probe still blocked).
