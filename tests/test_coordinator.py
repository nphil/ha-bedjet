"""Tests for BedJetCoordinator: push-driven updates, no polling, clean shutdown.

Uses a minimal fake device (not the real pybedjet.BedJet) since coordinator.py
only touches device.address-free surface: .available, .state,
.register_callback(). This keeps the test independent of the pybedjet layer's
own churn.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bedjet.coordinator import BedJetCoordinator


class FakeDevice:
    def __init__(self) -> None:
        self.available = True
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
