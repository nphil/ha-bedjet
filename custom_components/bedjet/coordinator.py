"""Push-driven data update coordinator for the BedJet integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .pybedjet import BedJet, BedJetState

_LOGGER = logging.getLogger(__name__)


class BedJetCoordinator(DataUpdateCoordinator[BedJetState | None]):
    """Coordinate a single BedJet device.

    There is no polling interval: the BedJet notify characteristic streams a
    status frame at roughly 4 Hz for as long as a connection is held (even in
    standby), so the library pushes every decoded frame straight into
    ``async_set_updated_data`` and this coordinator never schedules a refresh
    of its own.

    No dedup is done here for consecutive identical frames: pybedjet already
    rate-limits its own callback firing for continuous-value-only changes per
    the Contract (mode/fan/target/notification changes still publish
    immediately), and Home Assistant's state machine itself is a no-op past
    the initial comparison when an entity writes an unchanged state and
    attributes. ``DataUpdateCoordinator.always_update`` would not help here
    either way - it is only consulted by the polling refresh path, not by
    ``async_set_updated_data``.
    """

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, device: BedJet
    ) -> None:
        """Initialize the coordinator and start listening to the device."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=config_entry.title,
        )
        self.device = device
        self._unregister_device_callback = device.register_callback(
            self._handle_device_update
        )

    @property
    def available(self) -> bool:
        """Return True while the device is connected and reporting fresh frames."""
        return self.device.available

    @callback
    def _handle_device_update(self, device: BedJet) -> None:
        """Push the library's latest decoded state into the coordinator."""
        self.async_set_updated_data(device.state)

    async def async_shutdown(self) -> None:
        """Stop listening to the device in addition to the base shutdown."""
        self._unregister_device_callback()
        await super().async_shutdown()
