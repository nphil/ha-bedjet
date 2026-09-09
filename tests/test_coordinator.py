"""Tests for BedJetCoordinator: push-driven updates, no polling, clean shutdown,
and the connection-path lookup the Connection sensor reads.

Uses a minimal fake device (not the real pybedjet.BedJet) since coordinator.py
only touches a narrow surface: .available, .connected, .state, .address,
.scanner_source, .register_callback(). This keeps the test independent of the
pybedjet layer's own churn.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import custom_components.bedjet.coordinator as coordinator_module
from custom_components.bedjet.coordinator import (
    BedJetCoordinator,
    resolve_connection_source,
)


class FakeDevice:
    def __init__(self) -> None:
        self.address = "FC:F5:C4:20:1A:92"
        self.available = True
        self.connected = False
        self.scanner_source = "D4:D4:DA:9D:40:8A"
        self.state = None
        self._callbacks: list = []
        self.unregister_calls = 0

    def register_callback(self, callback):
        self._callbacks.append(callback)

        def _unregister() -> None:
            self.unregister_calls += 1
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return _unregister

    def push(self, state) -> None:
        self.state = state
        for callback in list(self._callbacks):
            callback(self)


def make_coordinator(device: FakeDevice) -> BedJetCoordinator:
    entry = SimpleNamespace(title="Bedjetty")
    return BedJetCoordinator(hass=None, config_entry=entry, device=device)


def test_available_proxies_device_available_live() -> None:
    device = FakeDevice()
    coordinator = make_coordinator(device)

    assert coordinator.available is True
    device.available = False
    # Live proxy, not a snapshot taken at construction time.
    assert coordinator.available is False


def test_device_push_reaches_coordinator_data_with_no_polling() -> None:
    device = FakeDevice()
    coordinator = make_coordinator(device)
    assert coordinator.update_interval is None  # push-driven: never polls

    sentinel_state = object()
    device.push(sentinel_state)

    assert coordinator.data is sentinel_state


def test_async_shutdown_unregisters_device_callback() -> None:
    device = FakeDevice()
    coordinator = make_coordinator(device)

    asyncio.run(coordinator.async_shutdown())

    assert device.unregister_calls == 1
    # A push after shutdown must not resurrect the coordinator's data, since
    # nothing should still be listening.
    device.push(object())
    assert coordinator.data is None


ALLOCATION = SimpleNamespace(
    source="D4:D4:DA:9D:40:8A",
    slots=3,
    free=2,
    allocated=["fc:f5:c4:20:1a:92"],
)
OTHER_ALLOCATION = SimpleNamespace(
    source="AA:BB:CC:DD:EE:FF", slots=3, free=3, allocated=[]
)


class TestResolveConnectionSource:
    """Which proxy carries the link is only knowable from habluetooth's slot
    allocations - the advertisement source can name a different proxy, since
    habluetooth re-scores every proxy by RSSI on each connect.
    """

    def test_finds_the_scanner_that_allocated_this_address(self) -> None:
        source = resolve_connection_source(
            [OTHER_ALLOCATION, ALLOCATION],
            "FC:F5:C4:20:1A:92",
            connected=True,
            fallback_source="AA:BB:CC:DD:EE:FF",
        )
        # Case-insensitive: allocations are not guaranteed to match the
        # BLEDevice's casing, and the wrong answer here would name the wrong
        # proxy for a heal automation to restart.
        assert source == "D4:D4:DA:9D:40:8A"

    def test_disconnected_with_no_allocation_is_none(self) -> None:
        assert (
            resolve_connection_source(
                [OTHER_ALLOCATION],
                "FC:F5:C4:20:1A:92",
                connected=False,
                fallback_source="D4:D4:DA:9D:40:8A",
            )
            is None
        )

    def test_connected_without_slot_accounting_falls_back(self) -> None:
        # A local adapter may report no allocations at all; we are provably
        # connected, so claiming "disconnected" would be a lie.
        assert (
            resolve_connection_source(
                [], "FC:F5:C4:20:1A:92", connected=True, fallback_source="hci0"
            )
            == "hci0"
        )


def test_connection_scanner_name_prefers_the_registered_scanner_name(monkeypatch) -> None:
    device = FakeDevice()
    device.connected = True
    coordinator = make_coordinator(device)
    monkeypatch.setattr(
        coordinator_module,
        "get_manager",
        lambda: SimpleNamespace(async_current_allocations=lambda: [ALLOCATION]),
    )
    monkeypatch.setattr(
        coordinator_module,
        "async_scanner_by_source",
        lambda hass, source: SimpleNamespace(name="master-bedroom-bluetooth-proxy"),
    )

    assert coordinator.connection_source == "D4:D4:DA:9D:40:8A"
    assert coordinator.connection_scanner_name == "master-bedroom-bluetooth-proxy"


def test_connection_scanner_name_falls_back_to_the_bare_source(monkeypatch) -> None:
    device = FakeDevice()
    device.connected = True
    coordinator = make_coordinator(device)
    monkeypatch.setattr(
        coordinator_module,
        "get_manager",
        lambda: SimpleNamespace(async_current_allocations=lambda: [ALLOCATION]),
    )
    monkeypatch.setattr(
        coordinator_module, "async_scanner_by_source", lambda hass, source: None
    )

    assert coordinator.connection_scanner_name == "D4:D4:DA:9D:40:8A"


def test_connection_scanner_name_is_none_while_disconnected(monkeypatch) -> None:
    device = FakeDevice()
    coordinator = make_coordinator(device)
    monkeypatch.setattr(
        coordinator_module,
        "get_manager",
        lambda: SimpleNamespace(async_current_allocations=lambda: None),
    )

    assert coordinator.connection_scanner_name is None


def test_a_failed_scanner_lookup_cannot_swallow_a_state_push(monkeypatch) -> None:
    # The connect-edge log resolves a scanner name; if that lookup raises,
    # the frame must still have reached the coordinator (pybedjet only logs
    # a callback that raises, so a lost push would go unnoticed).
    device = FakeDevice()
    coordinator = make_coordinator(device)

    def boom():
        raise RuntimeError("no bluetooth manager")

    monkeypatch.setattr(coordinator_module, "get_manager", boom)
    device.connected = True
    sentinel_state = object()

    try:
        device.push(sentinel_state)
    except RuntimeError:
        pass

    assert coordinator.data is sentinel_state
