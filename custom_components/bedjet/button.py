"""BedJet button entities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet


@dataclass(frozen=True, kw_only=True)
class BedJetButtonEntityDescription(ButtonEntityDescription):
    """BedJet button entity description."""

    press_fn: Callable[[BedJet], Awaitable[None]]


BUTTONS = (
    BedJetButtonEntityDescription(
        key="acknowledge_notification",
        translation_key="acknowledge_notification",
        press_fn=lambda device: device.acknowledge_notification(),
    ),
    BedJetButtonEntityDescription(
        key="sync_clock",
        translation_key="sync_clock",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.sync_clock(),
    ),
    BedJetButtonEntityDescription(
        key="firmware_update",
        translation_key="firmware_update",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda device: device.request_firmware_update(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities(
        BedJetButtonEntity(coordinator, entry.title, descriptor)
        for descriptor in BUTTONS
    )


class BedJetButtonEntity(BedJetEntity, ButtonEntity):
    """Representation of a BedJet command button."""

    entity_description: BedJetButtonEntityDescription

    def __init__(self, coordinator, name: str, entity_description) -> None:
        """Initialize a BedJet button entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.device.address}_{entity_description.key}"
        super().__init__(coordinator, name)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._async_send_command(self.entity_description.press_fn, self._device)
