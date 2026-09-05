# WHATCHANGED - Tests layer (TestsCI-2)

Scope: `tests/` (new), `requirements_test.txt` (new), `.github/workflows/tests.yml` (new).
Does not touch any source file under `custom_components/bedjet/`.

Run: `uv run --python 3.13 --with-requirements requirements_test.txt python -m pytest tests -q`
(plain `pip install -r requirements_test.txt && pytest tests -q` on CPython 3.13 works identically).
190 tests, 0 skipped, ~0.3s wall time, no BLE hardware, no Home Assistant checkout, no real
time.sleep beyond a handful of sub-20ms real awaits used to let a genuinely-pending asyncio
timer/task fire (never the 60s/300s/900s/2s..120s real production durations - every one of
those constants is monkeypatched or driven through a fake monotonic clock).

## Infrastructure

- `tests/ha_stubs.py`: registers minimal `homeassistant.*` stand-ins in `sys.modules` *only*
  when real Home Assistant isn't importable (mirrors the pattern proven in the sibling
  `ac_infinity` rebuild's `tests/ha_stubs.py`). Covers every HA symbol every bedjet source
  file imports at module level: core/const/exceptions/config_entries/data_entry_flow,
  `components.bluetooth` (+ `.match`), `components.{climate,fan,sensor,binary_sensor,switch,
  number,button}`, `helpers.{device_registry,entity_platform,update_coordinator}`,
  `util.dt`. `DataUpdateCoordinator`/`CoordinatorEntity` are faithful enough that
  `coordinator.async_set_updated_data(...)`/`async_update_listeners()` genuinely fan out to
  every registered entity's `_handle_coordinator_update`, so push-driven-update tests exercise
  real wiring, not a mock that always "works". `*EntityDescription` stubs are real
  `@dataclass(frozen=True, kw_only=True)` bases (not plain classes) so the source files'
  `@dataclass class BedJetXEntityDescription(XEntityDescription): value_fn: ...` subclassing
  pattern inherits fields the way real HA dataclasses do - a plain-class base would silently
  drop every inherited field from the generated `__init__` (caught before landing; verified
  with a standalone repro against real `dataclasses`). Every entity base's generic
  `_attr_foo -> foo` property (`unique_id`, `name`, `hvac_modes`, `native_max_value`, ...) is
  resolved via one `__getattr__` fallback on the shared `_WriteStateRecorder` mixin, mirroring
  how real HA's `Entity` base works, instead of hand-enumerating dozens of one-off properties.
- `tests/ble_fakes.py`: `FakeBleakClient` (duck-typed `bleak.BleakClient`: `connect`/
  `disconnect`/`write_gatt_char`/`read_gatt_char`/`start_notify`/`stop_notify`, records every
  write and read, `.notify(char, payload)` pushes a notification, `.simulate_disconnect()`
  drops the link), `FakeBleakClientFactory` + `make_fake_establish_connection` (drop-in
  replacement for `bleak_retry_connector.establish_connection`, honors
  `FakeBleakClient.fail_next_connects` and the real `max_attempts` retry-loop shape),
  `make_ble_device`/`make_advertisement_data` build real `bleak` dataclasses (real `bleak`/
  `bleak-retry-connector`/`bluetooth-data-tools` are installed as test deps - they're tiny,
  pure-Python-construction-safe, and real field names beat a hand-copied stand-in that could
  drift).
- `tests/conftest.py`: installs the stubs before any `custom_components` import; ground-truth
  fixtures `standby_notify`/`standby_tail` are the exact live-capture hex blobs from the
  assignment brief; `notify_builder`/`tail_builder` construct synthetic-but-protocol-shaped
  frames from ESPHome's own field map (never invented offsets).

## Coverage map

**Codec (`test_codec.py`, pure, no I/O)** - decode of both real captures matches every stated
field (mode/temps/fan/ambient/is_partial); tail merge matches every stated flag bit
(conn_test_passed/units_setup/beeps_muted/leds_enabled/dual_zone/update_phase/notification);
turbo_time little-endian (regression - the old fork decoded it big-endian, `0x1234` vs
`0x3412`); every ESPHome validation boundary (mode<7, target 38..86, actual/ambient
`1<x<=100`) at both the rejecting and accepting edges; debug-format ambient-only patch
(previously unimplemented) both patches correctly and requires a prior state; unrecognized
tail notification code raises; `build_command` byte-exact for every opcode incl. natural-unit
inputs (`SET_TEMP` takes Celsius, `SET_FAN` takes percent, `SET_CLOCK`/`SET_RUNTIME` take
hour/minute) and every documented range violation raises `ValueError`; `is_meaningful_change`
(the pure gate behind the fan-out rate limit) proven for every discrete field plus the
"continuous fields alone are not meaningful" case.

**Watchdog/backoff (`test_watchdog_backoff.py`, pure)** - all four `watchdog_action` tiers at
both boundaries (59.999/60/299.999/300/899.999/900); `reconnect_backoff_seconds` full-jitter
bounds, growth-before-cap, saturation-at-cap, and bit-for-bit determinism against a seeded
`random.Random` run independently.

**Connection lifecycle (`test_connection.py`, async, fake BLE)** - `hold_connection=False`
never connects and suppresses reconnect even across an advertisement; toggling it disconnects/
reconnects both directions; an advertisement wakes a pending backoff sleep immediately instead
of waiting out the (here: 10s, would-never-resolve-in-test) delay; a mid-session disconnect
triggers exactly one reconnect; consecutive connect failures produce a non-decreasing,
resetting attempt counter fed to `reconnect_backoff_seconds`; commands raise
`BedJetConnectionError` when not connected, resolve on a matching confirming frame, and raise
`BedJetCommandError` on timeout when only non-matching frames arrive; the tail is re-read once
per staleness window (not per `is_partial` frame) and again once genuinely stale, and a
just-completed command forces one extra re-read even when not yet stale; listener fan-out
rate-limits a continuous-only (actual-temp) change to once per `PUBLISH_MIN_INTERVAL_S` while
a mode change publishes immediately regardless of elapsed time; all three watchdog tiers
verified against the real `_watchdog_loop` body (PROBE writes the literal `[0x06]` status
probe, UNAVAILABLE fires listeners exactly once per stale `last_frame_at` - not once per tick,
RECONNECT forces a real disconnect and re-arms the wakeup event) using a monkeypatched
`_monotonic` fake clock, never a real multi-minute sleep.

**HA entity/coordinator/setup layer** (`test_coordinator.py`, `test_entity_base.py`,
`test_entity_command_errors.py`, `test_init.py`, `test_config_flow.py`, `test_climate.py`,
`test_fan.py`, `test_sensor.py`, `test_binary_sensor.py`, `test_switch.py`, `test_number.py`,
`test_button.py`) - coordinator is push-only (`update_interval is None`) and proxies
`device.available` live, not a snapshot; `BedJetEntity.available` requires both
`coordinator.available` and `device.hold_connection`; `_async_send_command` turns every
`BedJetError` subclass into `HomeAssistantError` (proven for both `BedJetCommandError` and
`BedJetConnectionError`, plus the pass-through-args success path); `async_setup_entry` raises
`ConfigEntryNotReady` only when the address was never seen by HA's bluetooth stack at all,
never when the device merely hasn't answered yet (regression test for a bug HALayer fixed
mid-build - the first draft blocked/failed setup on a slow-to-answer device, which would have
hidden the very `bluetooth_connection` switch meant to fix the "phone app holds the slot"
problem); the advertisement callback forwards `(device, advertisement, source)` exactly;
`bluetooth_connection` switch stays available with `coordinator.available=False` and
`device.hold_connection=False` (the two conditions everything else requires) and calls
`coordinator.async_update_listeners()` on toggle so sibling entities refresh immediately
instead of waiting for a frame that will never come; every other entity's unique_id is stable
per HALayer's `WHATCHANGED-ha.md` map; climate hvac_modes/fan_modes/temperature limits are
static class attributes untouched by a frame carrying different per-mode min/max (regression
guard for upstream issue #61); preset "none" is a conditional revert (only from Turbo/Extended
Heat) not an unconditional Heat switch (regression test for a bug HALayer fixed mid-build);
fan on/off + percent passthrough; sensor `notification` distinguishes `None` (unknown, no
frame yet) from `BedJetNotification.NONE` (known, nothing pending) - both a `None`-preview
regression test and the corrected `is not None` check are covered; `scanner` sensor is the one
sensor that updates before any frame has ever decoded (`coordinator.data is None` bypass);
diagnostic-vs-enabled-by-default and config-vs-diagnostic entity_category/enabled flags are
asserted per entity across every platform that HALayer's map specifies.

## Design decisions

- No `pytest-asyncio`: every async test wraps a plain `async def scenario(): ...` in
  `asyncio.run(scenario())`, matching the pattern already proven in the sibling `ac_infinity`
  rebuild's suite. One dependency fewer, no event-loop-scope fixture questions.
- Every test that needs "did the pending backoff/timeout actually fire" uses a handful of real
  `await asyncio.sleep(small_ms)` iterations (needed because `asyncio.timeout(delay)` requires
  genuine wall-clock progress to expire) with the underlying constant patched down to
  milliseconds or `0.0` first - so the *relative ordering and effect* of a real timer is
  proven without ever waiting out a production-scale delay.
- `reconnect_backoff_seconds`/`_monotonic`/`asyncio.sleep` are patched via `monkeypatch`
  exclusively (never a bare `module.attr = ...` reassignment), so a stub in one test can never
  leak into a later test in the same session - flagged and fixed mid-build after a live
  correctness review caught one raw-assignment instance.
- No test asserts wiring/forwarding/mock-echo/source text: every assertion is either a
  documented protocol byte value (traceable to ESPHome or the live capture), an observable HA
  contract (`available`, `unique_id`, raised exception type, entity_category/enabled-default),
  or a timing/ordering property (exactly-once notification, non-decreasing attempt count,
  before/after read-count deltas).
