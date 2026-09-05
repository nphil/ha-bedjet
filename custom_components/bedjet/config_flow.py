"""Config flow for the BedJet integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bluetooth_data_tools import human_readable_name
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import BEDJET_SERVICE_UUID, DOMAIN, LOCAL_NAME_PREFIX
from .pybedjet import BedJet

_LOGGER = logging.getLogger(__name__)

# Short interactive timeout for the config flow's connectivity probe; the
# longer CONNECT_TIMEOUT in const.py is for the (non-interactive) integration
# setup, which HA retries automatically on failure.
PROBE_TIMEOUT = 15


def _is_bedjet(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if a discovered advertisement looks like a BedJet."""
    return BEDJET_SERVICE_UUID in service_info.service_uuids or bool(
        service_info.name and service_info.name.upper().startswith(LOCAL_NAME_PREFIX)
    )


async def _async_probe(service_info: BluetoothServiceInfoBleak) -> str | None:
    """Connect briefly to confirm a BedJet answers.

    Returns an abort/error reason string on failure, or None on success.
    """
    device = BedJet(
        service_info.device, service_info.advertisement, source=service_info.source
    )
    frame_received = asyncio.Event()
    unregister = device.register_callback(lambda *_: frame_received.set())
    try:
        await device.start()
        async with asyncio.timeout(PROBE_TIMEOUT):
            await frame_received.wait()
    except TimeoutError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error probing BedJet")
        return "unknown"
    finally:
        unregister()
        await device.stop()
    return None


class BedjetDeviceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BedJet."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered BT device: %s", discovery_info)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if reason := await _async_probe(discovery_info):
            return self.async_abort(reason=reason)

        name = human_readable_name(None, discovery_info.name, discovery_info.address)
        self.context["title_placeholders"] = {"name": name}
        self._discovery_info = discovery_info

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            assert self._discovery_info is not None
            return self.async_create_entry(
                title=self.context["title_placeholders"]["name"],
                data={CONF_ADDRESS: self._discovery_info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            if reason := await _async_probe(discovery_info):
                errors["base"] = reason
            else:
                name = human_readable_name(
                    None, discovery_info.name, discovery_info.address
                )
                return self.async_create_entry(
                    title=name, data={CONF_ADDRESS: address}
                )

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    or not _is_bedjet(discovery)
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        service_info.address: (
                            f"{service_info.name} ({service_info.address})"
                        )
                        for service_info in self._discovered_devices.values()
                    }
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
