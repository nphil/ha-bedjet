"""Tests for the BedJet switch platform.

Covers the config-category toggle switches (enable_led, mute_beeps), including
stable unique_ids and command-error mapping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bedjet.pybedjet import BedJetCommandError
from custom_components.bedjet.switch import SWITCHES, BedJetSwitchEntity
from homeassistant.exceptions import HomeAssistantError

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
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
