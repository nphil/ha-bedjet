"""BedJet climate entity."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJetButton, BedJetMode

_LOGGER = logging.getLogger(__name__)

# Static per Home Assistant convention, not read from the per-mode min/max the
# device reports in status frames (upstream ha-bedjet issue #61: those churn
# on every mode change and are not meant to be entity-wide limits).
MIN_TEMP_C = 19.0
MAX_TEMP_C = 43.0

PRESET_NONE = "none"
PRESET_TURBO = "Turbo"
PRESET_EXTENDED_HEAT = "Extended Heat"

MODE_TO_HVAC_MODE = {
    BedJetMode.STANDBY: HVACMode.OFF,
    BedJetMode.WAIT: HVACMode.OFF,
    BedJetMode.COOL: HVACMode.COOL,
    BedJetMode.DRY: HVACMode.DRY,
    BedJetMode.HEAT: HVACMode.HEAT,
    BedJetMode.TURBO: HVACMode.HEAT,
    BedJetMode.EXTENDED_HEAT: HVACMode.HEAT,
}
HVAC_MODE_TO_MODE = {
    HVACMode.OFF: BedJetMode.STANDBY,
    HVACMode.COOL: BedJetMode.COOL,
    HVACMode.DRY: BedJetMode.DRY,
    HVACMode.HEAT: BedJetMode.HEAT,
}
MODE_TO_PRESET = {
    BedJetMode.TURBO: PRESET_TURBO,
    BedJetMode.EXTENDED_HEAT: PRESET_EXTENDED_HEAT,
}
# "None" only means anything as a preset revert while a HEAT-family preset
# (Turbo/Extended Heat) is active; setting it from Cool/Dry/off must not
# force a mode switch.
PRESET_TO_MODE = {
    PRESET_TURBO: BedJetMode.TURBO,
    PRESET_EXTENDED_HEAT: BedJetMode.EXTENDED_HEAT,
}
PRESET_REVERT_MODES = (BedJetMode.TURBO, BedJetMode.EXTENDED_HEAT)
MEMORY_PRESET_KEYS = ("m1_name", "m2_name", "m3_name")
MEMORY_PRESET_BUTTONS = (BedJetButton.M1, BedJetButton.M2, BedJetButton.M3)
MEMORY_PRESET_DEFAULT_LABELS = ("M1", "M2", "M3")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities([BedJetClimateEntity(coordinator, entry.title)])


class BedJetClimateEntity(BedJetEntity, ClimateEntity):
    """Representation of a BedJet device as a climate entity."""

    _attr_fan_modes = [f"{speed}%" for speed in range(5, 101, 5)]
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.DRY]
    _attr_max_temp = MAX_TEMP_C
    _attr_min_temp = MIN_TEMP_C
    _attr_name = None
    _attr_preset_modes = [
        PRESET_NONE,
        PRESET_TURBO,
        PRESET_EXTENDED_HEAT,
        *MEMORY_PRESET_DEFAULT_LABELS,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, name: str) -> None:
        """Initialize a BedJet climate entity."""
        self._attr_unique_id = coordinator.device.address
        self._memory_preset_buttons: dict[str, BedJetButton] = dict(
            zip(MEMORY_PRESET_DEFAULT_LABELS, MEMORY_PRESET_BUTTONS, strict=True)
        )
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if (state := self.coordinator.data) is None:
            return
        self._attr_current_temperature = state.actual_temp_c
        self._attr_target_temperature = state.target_temp_c
        self._attr_fan_mode = f"{state.fan_percent}%"
        self._attr_hvac_mode = MODE_TO_HVAC_MODE.get(state.mode, HVACMode.OFF)
        self._attr_preset_mode = MODE_TO_PRESET.get(state.mode, PRESET_NONE)

        device = self._device
        labels = [
            getattr(device, key, None) or default
            for key, default in zip(
                MEMORY_PRESET_KEYS, MEMORY_PRESET_DEFAULT_LABELS, strict=True
            )
        ]
        self._memory_preset_buttons = dict(zip(labels, MEMORY_PRESET_BUTTONS, strict=True))
        self._attr_preset_modes = [
            PRESET_NONE,
            PRESET_TURBO,
            PRESET_EXTENDED_HEAT,
            *labels,
        ]

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        await self._async_send_command(
            self._device.set_fan_percent, int(fan_mode.removesuffix("%"))
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if (mode := HVAC_MODE_TO_MODE.get(hvac_mode)) is None:
            raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")
        await self._async_send_command(self._device.set_mode, mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode == PRESET_NONE:
            state = self.coordinator.data
            if state is not None and state.mode in PRESET_REVERT_MODES:
                await self._async_send_command(self._device.set_mode, BedJetMode.HEAT)
            return
        if (mode := PRESET_TO_MODE.get(preset_mode)) is not None:
            await self._async_send_command(self._device.set_mode, mode)
            return
        if (button := self._memory_preset_buttons.get(preset_mode)) is not None:
            await self._async_send_command(self._device.press_button, button)
            return
        raise HomeAssistantError(f"{preset_mode} is not a valid preset for {self.name}")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_HVAC_MODE in kwargs:
            _LOGGER.warning(
                "Changing HVAC mode while setting temperature for %s is not "
                "supported. Please call `climate.set_hvac_mode` first",
                self.entity_id,
            )
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._async_send_command(self._device.set_temperature_c, temperature)
