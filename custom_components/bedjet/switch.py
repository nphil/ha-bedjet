"""BedJet switch entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BedJetConfigEntry
from .entity import BedJetEntity
from .pybedjet import BedJet, BedJetState


@dataclass(frozen=True, kw_only=True)
class BedJetSwitchEntityDescription(SwitchEntityDescription):
    """BedJet switch entity description."""

    toggle_fn: Callable[[BedJet, bool], Any]
    value_fn: Callable[[BedJetState], bool | None]


SWITCHES = (
    BedJetSwitchEntityDescription(
        key="enable_led",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        translation_key="enable_led",
        toggle_fn=lambda device, enabled: device.set_led(enabled),
        value_fn=lambda state: state.leds_enabled,
    ),
    BedJetSwitchEntityDescription(
        key="mute_beeps",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        translation_key="mute_beeps",
        toggle_fn=lambda device, muted: device.set_mute(muted),
        value_fn=lambda state: state.beeps_muted,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BedJetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch platform for BedJet."""
    coordinator = entry.runtime_data
    async_add_entities(
        BedJetSwitchEntity(coordinator, entry.title, descriptor) for descriptor in SWITCHES
    )


class BedJetSwitchEntity(BedJetEntity, SwitchEntity):
    """Representation of a BedJet device setting toggle."""

    entity_description: BedJetSwitchEntityDescription

    def __init__(self, coordinator, name: str, entity_description) -> None:
        """Initialize a BedJet switch entity."""
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.device.address}_{entity_description.key}"
        super().__init__(coordinator, name)

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        if (state := self.coordinator.data) is None:
            return
        self._attr_is_on = self.entity_description.value_fn(state)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._async_send_command(self.entity_description.toggle_fn, self._device, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._async_send_command(self.entity_description.toggle_fn, self._device, True)

