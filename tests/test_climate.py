"""Tests for the BedJet climate entity.

Covers: static 19-43C limits regardless of the per-mode min/max a status
frame reports (upstream issue #61 churn), fan_modes 5%..100%, hvac/preset
mapping, and command-error -> HomeAssistantError mapping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bedjet.climate import (
    MAX_TEMP_C,
    MIN_TEMP_C,
    PRESET_EXTENDED_HEAT,
    PRESET_NONE,
    PRESET_TURBO,
    BedJetClimateEntity,
)
from custom_components.bedjet.pybedjet import BedJetCommandError
from custom_components.bedjet.pybedjet.const import BedJetMode
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import HomeAssistantError

ADDRESS = "FC:F5:C4:20:1A:92"


def make_state(**overrides):
    base = dict(
        mode=BedJetMode.STANDBY,
        actual_temp_c=25.0,
        target_temp_c=40.0,
        fan_percent=5,
        min_temp_c=10.0,
        max_temp_c=40.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.mode_calls: list[BedJetMode] = []
        self.fan_calls: list[int] = []
        self.temp_calls: list[float] = []
        self.button_calls: list = []
        self.raise_on_command: Exception | None = None

    async def set_mode(self, mode) -> None:
        if self.raise_on_command:
            raise self.raise_on_command
        self.mode_calls.append(mode)

    async def set_fan_percent(self, percent: int) -> None:
        if self.raise_on_command:
            raise self.raise_on_command
        self.fan_calls.append(percent)

    async def set_temperature_c(self, celsius: float) -> None:
        if self.raise_on_command:
            raise self.raise_on_command
        self.temp_calls.append(celsius)

    async def press_button(self, button) -> None:
        if self.raise_on_command:
            raise self.raise_on_command
        self.button_calls.append(button)


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = make_state()

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def make_entity(device: FakeDevice | None = None) -> tuple[BedJetClimateEntity, FakeCoordinator]:
    device = device or FakeDevice()
    coordinator = FakeCoordinator(device)
    return BedJetClimateEntity(coordinator, "Bedjetty"), coordinator


class TestStaticLimits:
    def test_unique_id_is_bare_address(self) -> None:
        entity, _coordinator = make_entity()
        assert entity.unique_id == ADDRESS

    def test_min_max_ignore_per_mode_frame_values(self) -> None:
        entity, coordinator = make_entity()
        coordinator.data = make_state(min_temp_c=5.0, max_temp_c=99.0)
        entity._async_update_attrs()

        assert entity.min_temp == MIN_TEMP_C == 19.0
        assert entity.max_temp == MAX_TEMP_C == 43.0

    def test_hvac_modes_are_off_heat_cool_dry(self) -> None:
        entity, _coordinator = make_entity()
        assert entity.hvac_modes == [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.DRY,
        ]

    def test_fan_modes_are_5_to_100_percent(self) -> None:
        entity, _coordinator = make_entity()
        assert entity.fan_modes[0] == "5%"
        assert entity.fan_modes[-1] == "100%"
        assert len(entity.fan_modes) == 20

class TestBeforeFirstFrame:
    def test_state_properties_resolve_with_no_coordinator_data(self) -> None:
        """A listener fan-out before the first decoded frame must not raise.

        Live failure: HA computed the climate state while coordinator.data was
        None and ClimateEntity's hvac_mode/fan_mode/preset_mode backing
        attributes had never been assigned (AttributeError in the listener).
        """
        coordinator = FakeCoordinator(FakeDevice())
        coordinator.data = None
        entity = BedJetClimateEntity(coordinator, "Bedjetty")

        assert entity.hvac_mode is None
        assert entity.fan_mode is None
        assert entity.preset_mode is None



class TestModeMapping:
    @pytest.mark.parametrize(
        ("mode", "hvac_mode"),
        [
            (BedJetMode.STANDBY, HVACMode.OFF),
            (BedJetMode.WAIT, HVACMode.OFF),
            (BedJetMode.COOL, HVACMode.COOL),
            (BedJetMode.DRY, HVACMode.DRY),
            (BedJetMode.HEAT, HVACMode.HEAT),
            (BedJetMode.TURBO, HVACMode.HEAT),
            (BedJetMode.EXTENDED_HEAT, HVACMode.HEAT),
        ],
    )
    def test_frame_mode_maps_to_hvac_mode(self, mode, hvac_mode) -> None:
        entity, coordinator = make_entity()
        coordinator.data = make_state(mode=mode)
        entity._async_update_attrs()
        assert entity.hvac_mode == hvac_mode

    @pytest.mark.parametrize(
        ("mode", "preset"),
        [
            (BedJetMode.TURBO, PRESET_TURBO),
            (BedJetMode.EXTENDED_HEAT, PRESET_EXTENDED_HEAT),
            (BedJetMode.HEAT, PRESET_NONE),
            (BedJetMode.STANDBY, PRESET_NONE),
        ],
    )
    def test_frame_mode_maps_to_preset(self, mode, preset) -> None:
        entity, coordinator = make_entity()
        coordinator.data = make_state(mode=mode)
        entity._async_update_attrs()
        assert entity.preset_mode == preset


class TestServiceCalls:
    def test_set_hvac_mode_heat_sends_heat_mode(self) -> None:
        device = FakeDevice()
        entity, _coordinator = make_entity(device)
        asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))
        assert device.mode_calls == [BedJetMode.HEAT]

    def test_set_hvac_mode_unsupported_raises_home_assistant_error(self) -> None:
        entity, _coordinator = make_entity()
        with pytest.raises(HomeAssistantError):
            asyncio.run(entity.async_set_hvac_mode(HVACMode.FAN_ONLY))

    def test_set_preset_none_from_turbo_reverts_to_heat(self) -> None:
        device = FakeDevice()
        entity, coordinator = make_entity(device)
        coordinator.data = make_state(mode=BedJetMode.TURBO)
        asyncio.run(entity.async_set_preset_mode(PRESET_NONE))
        assert device.mode_calls == [BedJetMode.HEAT]

    def test_set_preset_none_from_extended_heat_reverts_to_heat(self) -> None:
        device = FakeDevice()
        entity, coordinator = make_entity(device)
        coordinator.data = make_state(mode=BedJetMode.EXTENDED_HEAT)
        asyncio.run(entity.async_set_preset_mode(PRESET_NONE))
        assert device.mode_calls == [BedJetMode.HEAT]

    def test_set_preset_none_from_cool_is_a_no_op(self) -> None:
        device = FakeDevice()
        entity, coordinator = make_entity(device)
        coordinator.data = make_state(mode=BedJetMode.COOL)
        asyncio.run(entity.async_set_preset_mode(PRESET_NONE))
        assert device.mode_calls == []

    def test_set_preset_turbo_sends_turbo_mode(self) -> None:
        device = FakeDevice()
        entity, _coordinator = make_entity(device)
        asyncio.run(entity.async_set_preset_mode(PRESET_TURBO))
        assert device.mode_calls == [BedJetMode.TURBO]

    def test_set_preset_invalid_raises_home_assistant_error(self) -> None:
        entity, _coordinator = make_entity()
        with pytest.raises(HomeAssistantError):
            asyncio.run(entity.async_set_preset_mode("not-a-real-preset"))

    def test_set_fan_mode_strips_percent_sign(self) -> None:
        device = FakeDevice()
        entity, _coordinator = make_entity(device)
        asyncio.run(entity.async_set_fan_mode("55%"))
        assert device.fan_calls == [55]

    def test_set_temperature_forwards_celsius(self) -> None:
        from homeassistant.const import ATTR_TEMPERATURE

        device = FakeDevice()
        entity, _coordinator = make_entity(device)
        asyncio.run(entity.async_set_temperature(**{ATTR_TEMPERATURE: 38.0}))
        assert device.temp_calls == [38.0]

    def test_command_failure_surfaces_as_home_assistant_error(self) -> None:
        device = FakeDevice()
        device.raise_on_command = BedJetCommandError("confirmation timed out")
        entity, _coordinator = make_entity(device)
        with pytest.raises(HomeAssistantError):
            asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))
