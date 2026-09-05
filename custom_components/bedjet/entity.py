"""BedJet device entity base class."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BedJetCoordinator
from .pybedjet import BedJet, BedJetError

MANUFACTURER = "BedJet"
MODEL = "BedJet 3"


class BedJetEntity(CoordinatorEntity[BedJetCoordinator]):
    """Representation of a BedJet device.

    Unavailable whenever the coordinator has no fresh data or the connection
    slot has been intentionally handed to another client (``hold_connection``
    is False). The Bluetooth Connection switch entity overrides ``available``
    since it must keep working precisely when this is False.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BedJetCoordinator, name: str) -> None:
        """Initialize a BedJet entity."""
        super().__init__(coordinator)
        self._device: BedJet = coordinator.device
        self._attr_device_info = DeviceInfo(
            name=name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={(dr.CONNECTION_BLUETOOTH, self._device.address)},
        )
        self._async_update_attrs()

    @property
    def available(self) -> bool:
        """Return True while the device is usable by this entity."""
        return self.coordinator.available and self._device.hold_connection

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values from the latest state."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle a pushed status update."""
        self._async_update_attrs()
        self.async_write_ha_state()

    async def _async_send_command(
        self, func: Callable[..., Awaitable[None]], *args: Any, **kwargs: Any
    ) -> None:
        """Call a pybedjet command method, surfacing library errors to HA.

        Every command awaits the frame that confirms it; there is no
        optimistic local state to roll back on failure.
        """
        try:
            await func(*args, **kwargs)
        except BedJetError as err:
            raise HomeAssistantError(str(err)) from err
