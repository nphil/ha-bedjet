"""BedJet sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet, BedJetNotification


@dataclass(frozen=True, kw_only=True)
class BedJetSensorEntityDescription(SensorEntityDescription):
    """BedJet sensor entity description."""

    value_fn: Callable[[BedJet], Any]


SENSORS = (
    BedJetSensorEntityDescription(
        key="ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="ambient_temperature",
        value_fn=lambda device: device.state.ambient_temp_c,
    ),
    BedJetSensorEntityDescription(
        key="outlet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        translation_key="outlet_temperature",
        value_fn=lambda device: device.state.actual_temp_c,
    ),
    BedJetSensorEntityDescription(
        key="notification",
        device_class=SensorDeviceClass.ENUM,
        options=[member.name.lower() for member in BedJetNotification],
        translation_key="notification",
        value_fn=(
            lambda device: (
                notification.name.lower()
                if (notification := device.state.notification) is not None
                else None
            )
        ),
    ),
    BedJetSensorEntityDescription(
        key="bio_sequence_step",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="bio_sequence_step",
        value_fn=lambda device: device.state.bio_sequence_step,
    ),
    BedJetSensorEntityDescription(
        key="shutdown_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="shutdown_reason",
        value_fn=lambda device: device.state.shutdown_reason,
    ),
    BedJetSensorEntityDescription(
        key="turbo_time",
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        translation_key="turbo_time",
        value_fn=lambda device: device.state.turbo_time,
    ),
    BedJetSensorEntityDescription(
        key="update_phase",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="update_phase",
        value_fn=lambda device: device.state.update_phase,
    ),
    BedJetSensorEntityDescription(
        key="scanner",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="scanner",
        value_fn=lambda device: device.scanner_source,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities(
        BedJetSensorEntity(coordinator, entry.title, descriptor)
        for descriptor in SENSORS
    )


class BedJetSensorEntity(BedJetEntity, SensorEntity):
    """Representation of a BedJet sensor."""

    entity_description: BedJetSensorEntityDescription

    def __init__(self, coordinator, name: str, entity_description) -> None:
        """Initialize a BedJet sensor entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.device.address}_{entity_description.key}"
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if self.entity_description.key != "scanner" and self.coordinator.data is None:
            return
        self._attr_native_value = self.entity_description.value_fn(self._device)
