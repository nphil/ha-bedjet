"""Tests for the BedJet switch platform.

Covers the always-available bluetooth_connection switch (the only way a user
gets the BLE slot back without disabling the whole integration) and the
config-category toggle switches (enable_led, mute_beeps), including stable
unique_ids and command-error mapping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bedjet.pybedjet import BedJetCommandError
from custom_components.bedjet.switch import (
    SWITCHES,
    BedJetConnectionSwitch,
    BedJetSwitchEntity,
)
from homeassistant.exceptions import HomeAssistantError

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.hold_connection = True
        self.led_calls: list[bool] = []
        self.mute_calls: list[bool] = []
        self.raise_on_toggle: Exception | None = None

    async def set_led(self, enabled: bool) -> None:
        if self.raise_on_toggle:
            raise self.raise_on_toggle
        self.led_calls.append(enabled)

    async def set_mute(self, muted: bool) -> None:
        if self.raise_on_toggle:
            raise self.raise_on_toggle
        self.mute_calls.append(muted)


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = SimpleNamespace(leds_enabled=False, beeps_muted=True)

    def async_add_listener(self, update_callback, context=None):
        return lambda: None

    def async_update_listeners(self) -> None:
        self.update_listener_calls = getattr(self, "update_listener_calls", 0) + 1


def descriptor_by_key(key: str):
    return next(d for d in SWITCHES if d.key == key)


class TestBluetoothConnectionSwitch:
    def test_unique_id_is_stable(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        entity = BedJetConnectionSwitch(coordinator, "Bedjetty")
        assert entity.unique_id == f"{ADDRESS}_bluetooth_connection"

    def test_always_available_even_when_coordinator_and_device_are_not(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        entity = BedJetConnectionSwitch(coordinator, "Bedjetty")

        coordinator.available = False
        coordinator.device.hold_connection = False

        assert entity.available is True

    def test_turn_off_releases_the_slot_and_refreshes_other_entities(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        entity = BedJetConnectionSwitch(coordinator, "Bedjetty")

        asyncio.run(entity.async_turn_off())

        assert coordinator.device.hold_connection is False
        assert entity.is_on is False
        # Other entities have no pushed frame to react to while the slot is
        # released, so turning this off must proactively refresh them.
        assert coordinator.update_listener_calls == 1

    def test_turn_on_reclaims_the_slot_and_refreshes_other_entities(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        coordinator.device.hold_connection = False
        entity = BedJetConnectionSwitch(coordinator, "Bedjetty")

        asyncio.run(entity.async_turn_on())

        assert coordinator.device.hold_connection is True
        assert entity.is_on is True
        assert coordinator.update_listener_calls == 1



class TestToggleSwitches:
    def test_enable_led_unique_id(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        entity = BedJetSwitchEntity(coordinator, "Bedjetty", descriptor_by_key("enable_led"))
        assert entity.unique_id == f"{ADDRESS}_enable_led"

    def test_enable_led_reflects_state_value_fn(self) -> None:
        coordinator = FakeCoordinator(FakeDevice())
        coordinator.data = SimpleNamespace(leds_enabled=True, beeps_muted=False)
        entity = BedJetSwitchEntity(coordinator, "Bedjetty", descriptor_by_key("enable_led"))
        entity._async_update_attrs()
        assert entity.is_on is True

    def test_turn_on_calls_device_set_led(self) -> None:
        device = FakeDevice()
        coordinator = FakeCoordinator(device)
        entity = BedJetSwitchEntity(coordinator, "Bedjetty", descriptor_by_key("enable_led"))

        asyncio.run(entity.async_turn_on())

        assert device.led_calls == [True]

    def test_mute_beeps_turn_off_calls_device_set_mute(self) -> None:
        device = FakeDevice()
        coordinator = FakeCoordinator(device)
        entity = BedJetSwitchEntity(coordinator, "Bedjetty", descriptor_by_key("mute_beeps"))

        asyncio.run(entity.async_turn_off())

        assert device.mute_calls == [False]

    def test_command_failure_surfaces_as_home_assistant_error(self) -> None:
        device = FakeDevice()
        device.raise_on_toggle = BedJetCommandError("confirmation timed out")
        coordinator = FakeCoordinator(device)
        entity = BedJetSwitchEntity(coordinator, "Bedjetty", descriptor_by_key("enable_led"))

        with pytest.raises(HomeAssistantError):
            asyncio.run(entity.async_turn_on())
