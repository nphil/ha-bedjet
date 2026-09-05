"""BedJet number entity."""

from __future__ import annotations

from math import ceil

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities([BedJetNumberEntity(coordinator, entry.title)])


class BedJetNumberEntity(BedJetEntity, NumberEntity):
    """Representation of a BedJet device's remaining runtime."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_translation_key = "runtime_remaining"

    def __init__(self, coordinator, name: str) -> None:
        """Initialize a BedJet number entity."""
        self._attr_unique_id = f"{coordinator.device.address}_runtime_remaining"
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if (state := self.coordinator.data) is None:
            return
        self._attr_native_max_value = state.max_runtime.total_seconds() / 60
        self._attr_native_value = ceil(state.time_remaining.total_seconds() / 60)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        minutes = int(value)
        await self._async_send_command(
            self._device.set_runtime, minutes // 60, minutes % 60
        )
