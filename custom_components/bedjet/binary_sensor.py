"""BedJet binary sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJetState


@dataclass(frozen=True, kw_only=True)
class BedJetBinarySensorEntityDescription(BinarySensorEntityDescription):
    """BedJet binary sensor entity description."""

    value_fn: Callable[[BedJetState], Any]


SENSORS = (
    BedJetBinarySensorEntityDescription(
        key="connection_test",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="connection_test",
        value_fn=lambda state: state.connection_test_passed,
    ),
    BedJetBinarySensorEntityDescription(
        key="dual_zone",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="dual_zone",
        value_fn=lambda state: state.dual_zone,
    ),
    BedJetBinarySensorEntityDescription(
        key="units_setup",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="units_setup",
        value_fn=lambda state: state.units_setup,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities(
        BedJetBinarySensorEntity(coordinator, entry.title, descriptor)
        for descriptor in SENSORS
    )


class BedJetBinarySensorEntity(BedJetEntity, BinarySensorEntity):
    """Representation of a BedJet binary sensor."""

    entity_description: BedJetBinarySensorEntityDescription

    def __init__(self, coordinator, name: str, entity_description) -> None:
        """Initialize a BedJet binary sensor entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.device.address}_{entity_description.key}"
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if (state := self.coordinator.data) is None:
            return
        self._attr_is_on = self.entity_description.value_fn(state)
