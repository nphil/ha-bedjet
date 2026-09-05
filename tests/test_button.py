"""Tests for the BedJet button platform: three distinct command buttons,
unique_ids, and the config/disabled-by-default gating on sync_clock and
firmware_update.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.bedjet.button import BUTTONS, BedJetButtonEntity
from custom_components.bedjet.pybedjet import BedJetCommandError
from homeassistant.exceptions import HomeAssistantError

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.acknowledge_calls = 0
        self.sync_clock_calls = 0
        self.firmware_update_calls = 0
        self.raise_on_press: Exception | None = None

    async def acknowledge_notification(self) -> None:
        if self.raise_on_press:
            raise self.raise_on_press
        self.acknowledge_calls += 1

    async def sync_clock(self) -> None:
        if self.raise_on_press:
            raise self.raise_on_press
        self.sync_clock_calls += 1

    async def request_firmware_update(self) -> None:
        if self.raise_on_press:
            raise self.raise_on_press
        self.firmware_update_calls += 1


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def descriptor_by_key(key: str):
    return next(d for d in BUTTONS if d.key == key)


def make_entity(key: str, device: FakeDevice | None = None):
    device = device or FakeDevice()
    coordinator = FakeCoordinator(device)
    return BedJetButtonEntity(coordinator, "Bedjetty", descriptor_by_key(key)), device


def test_unique_ids() -> None:
    for key in ("acknowledge_notification", "sync_clock", "firmware_update"):
        entity, _device = make_entity(key)
        assert entity.unique_id == f"{ADDRESS}_{key}"


def test_acknowledge_notification_is_enabled_by_default_no_category() -> None:
    descriptor = descriptor_by_key("acknowledge_notification")
    assert descriptor.entity_registry_enabled_default is True
    assert descriptor.entity_category is None


@pytest.mark.parametrize("key", ["sync_clock", "firmware_update"])
def test_config_buttons_are_disabled_by_default(key: str) -> None:
    descriptor = descriptor_by_key(key)
    assert descriptor.entity_registry_enabled_default is False


def test_acknowledge_notification_press_calls_device() -> None:
    entity, device = make_entity("acknowledge_notification")
    asyncio.run(entity.async_press())
    assert device.acknowledge_calls == 1


def test_sync_clock_press_calls_device_with_no_args() -> None:
    entity, device = make_entity("sync_clock")
    asyncio.run(entity.async_press())
    assert device.sync_clock_calls == 1


def test_firmware_update_press_calls_device() -> None:
    entity, device = make_entity("firmware_update")
    asyncio.run(entity.async_press())
    assert device.firmware_update_calls == 1


def test_press_failure_surfaces_as_home_assistant_error() -> None:
    device = FakeDevice()
    device.raise_on_press = BedJetCommandError("confirmation timed out")
    entity, _device = make_entity("sync_clock", device)
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_press())
