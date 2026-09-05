"""Throwaway verification of the two post-review hardening fixes. Delete after."""

import asyncio
import sys

sys.path.insert(0, "custom_components/bedjet")

import pybedjet as pb  # noqa: E402
from pybedjet.const import BedJetMode  # noqa: E402

STATUS_FRAME = bytes.fromhex("01561b0100000032500000000014500000310012")


class FakeClient:
    is_connected = True

    def __init__(self):
        self.written = []

    async def start_notify(self, uuid, callback):
        self.notify_callback = callback

    async def stop_notify(self, uuid):
        pass

    async def write_gatt_char(self, uuid, data, response=False):
        self.written.append(bytes(data))

    async def read_gatt_char(self, uuid):
        return bytes.fromhex("01990100ff00152500018f")

    async def disconnect(self):
        self.is_connected = False


class BrokenBLEDevice:
    """No .address attribute - simulates a fundamentally broken device object."""


async def test_supervisor_survives_broken_address():
    """The supervisor must never die, even if self.address itself raises."""
    attempts = [0]

    async def fake_establish_connection(client_cls, ble_device, name, disconnected_cb, **kwargs):
        attempts[0] += 1
        raise RuntimeError("simulated connect failure")

    pb.establish_connection = fake_establish_connection
    pb.RECONNECT_BACKOFF_MIN_S = 0.01  # keep the last-resort sleep fast for the test

    device = pb.BedJet(BrokenBLEDevice(), hold_connection=True)
    await device.start()
    # Let the supervisor run several iterations. Each one will:
    #  1. try to connect (fails with RuntimeError from the fake)
    #  2. try to log using self.address, which itself raises AttributeError
    #     (this is exactly what escaped the loop before the fix)
    for _ in range(30):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    assert not device._connect_task.done(), "supervisor task must still be alive"
    assert attempts[0] >= 1, "supervisor must still be attempting to connect"
    first_attempts = attempts[0]
    await asyncio.sleep(0.05)
    assert attempts[0] > first_attempts, "supervisor must keep retrying, not be stuck on one dead iteration"
    device._stopped = True
    device._connect_task.cancel()
    with __import__("contextlib").suppress(asyncio.CancelledError):
        await device._connect_task
    print(f"supervisor survived {attempts[0]} broken-address connect attempts without dying - OK")


async def test_watchdog_probe_is_fire_and_forget():
    """The PROBE tier must not block the loop on its own confirmation."""
    fake_time = [1000.0]
    pb._monotonic = lambda: fake_time[0]
    pb.WATCHDOG_TICK_S = 0.01
    # Deliberately do NOT shrink COMMAND_TIMEOUT_S here - if the probe still
    # goes through the confirmed path, this test will be slow/fail because
    # the real 5s timeout will block the loop from ever reaching UNAVAILABLE
    # within the short real-time budget below.
    assert pb.COMMAND_TIMEOUT_S == 5.0

    async def fake_establish_connection(client_cls, ble_device, name, disconnected_cb, **kwargs):
        return FakeClient()

    pb.establish_connection = fake_establish_connection
    ble_device = type("FakeBLEDevice", (), {"address": "AA:BB:CC:DD:EE:FF"})()
    device = pb.BedJet(ble_device, hold_connection=True)
    events = []
    device.register_callback(lambda d: events.append(fake_time[0]))

    await device.start()
    for _ in range(5):
        await asyncio.sleep(0)
    client = device._client
    client.notify_callback(object(), bytearray(STATUS_FRAME))
    for _ in range(5):
        await asyncio.sleep(0)

    # Jump straight past PROBE into UNAVAILABLE territory and give the loop
    # only a small *real* time budget - if the probe blocked for the real 5s
    # COMMAND_TIMEOUT_S, this would not resolve within that budget.
    fake_time[0] = 1000.0 + 305.0
    await asyncio.wait_for(_wait_until(lambda: not device.available), timeout=1.0)
    assert bytes([0x06]) in client.written, "expected the STATUS probe to still be written"
    assert not device.available
    print("watchdog PROBE is fire-and-forget: reached UNAVAILABLE within 1 real second (would need 5+ before the fix) - OK")

    await device.stop()


async def _wait_until(predicate, step=0.005):
    while not predicate():
        await asyncio.sleep(step)


async def main():
    await test_supervisor_survives_broken_address()
    await test_watchdog_probe_is_fire_and_forget()
    print("ALL HARDENING CHECKS PASSED")


asyncio.run(main())
