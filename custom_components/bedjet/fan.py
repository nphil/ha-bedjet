"""BedJet fan entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJetMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fan platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities([BedJetFanEntity(coordinator, entry.title)])


class BedJetFanEntity(BedJetEntity, FanEntity):
    """Representation of a BedJet device as a fan entity."""

    _attr_name = None
    _attr_speed_count = 20
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
    )

    def __init__(self, coordinator, name: str) -> None:
        """Initialize a BedJet fan entity."""
        self._attr_unique_id = f"{coordinator.device.address}_fan"
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if (state := self.coordinator.data) is None:
            return
        is_on = state.mode != BedJetMode.STANDBY
        self._attr_is_on = is_on
        self._attr_percentage = state.fan_percent if is_on else 0

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._async_send_command(self._device.set_mode, BedJetMode.STANDBY)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if self.coordinator.data is None or self.coordinator.data.mode == BedJetMode.STANDBY:
            await self._async_send_command(self._device.set_mode, BedJetMode.COOL)
        if percentage:
            await self._async_send_command(self._device.set_fan_percent, percentage)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return
        await self.async_turn_on(percentage=percentage)
