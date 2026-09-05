"""Tests for BedJetEntity: availability gating and push-driven state refresh.

Uses fakes for the coordinator/device surface entity.py actually touches
(coordinator.available, coordinator.device, device.address,
so this stays independent of the pybedjet layer.
"""

from __future__ import annotations

from custom_components.bedjet.entity import BedJetEntity
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH


class FakeDevice:
    def __init__(self, address: str = "FC:F5:C4:20:1A:92") -> None:
        self.address = address


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self._listeners: list = []

    def async_add_listener(self, update_callback, context=None):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    def push(self) -> None:
        for listener in list(self._listeners):
            listener()


def make_entity() -> tuple[BedJetEntity, FakeCoordinator, FakeDevice]:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    entity = BedJetEntity(coordinator, "Bedjetty")
    return entity, coordinator, device


def test_available_follows_coordinator_available() -> None:
    entity, coordinator, device = make_entity()
    assert entity.available is True

    coordinator.available = False
    assert entity.available is False


def test_device_info_carries_bluetooth_connection_to_address() -> None:
    entity, _coordinator, device = make_entity()
    assert entity._attr_device_info["connections"] == {
        (CONNECTION_BLUETOOTH, device.address)
    }


def test_coordinator_push_reaches_write_ha_state_with_no_polling() -> None:
    entity, coordinator, _device = make_entity()
    assert entity.write_ha_state_calls == 0

    coordinator.push()

    assert entity.write_ha_state_calls == 1
