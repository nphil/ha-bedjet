"""Minimal Home Assistant stand-ins so the integration modules import under plain pytest.

WHY: this fork targets HA 2026.9 (Python 3.13). Installing a full Home
Assistant just to unit-test decode/connection/entity-availability logic is
slow, version-coupled, and unnecessary - every HA symbol the integration
imports at module level is either a constant, a small dataclass, or a base
class whose scheduling behavior the tests do not rely on. We register light
replacements in ``sys.modules`` *before* ``custom_components`` is imported.

Rules for this file:
- If real Home Assistant is importable, we install NOTHING (see ``install()``),
  so the suite also runs unmodified inside a dev container that has HA.
- Entity bases are the thinnest object that lets the module import and the
  code under test run, plus a ``_WriteStateRecorder`` mixin so tests can
  observe that an entity asked Home Assistant to persist its state.
- ``CoordinatorEntity``/``DataUpdateCoordinator`` are faithful enough to real
  HA that ``coordinator.async_set_updated_data(...)`` fans out to every
  entity's ``_handle_coordinator_update`` exactly like production does -
  push-driven entity tests depend on that wiring being real, not mocked away.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from collections.abc import Callable
from enum import Enum, IntFlag, StrEnum
from types import ModuleType
from typing import Any


def _module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


class _WriteStateRecorder:
    """Mixin for entity stubs: records async_write_ha_state calls, and
    resolves any unrecognized attribute ``foo`` to ``self._attr_foo`` the way
    real HA's ``Entity`` base does for dozens of properties (``unique_id``,
    ``name``, ``hvac_modes``, ``native_max_value``, ...). Only used when
    normal lookup fails, so an explicitly defined property (``is_on``,
    ``native_value``, ...) always wins.

    Real HA schedules a state-machine update; tests only need to know the
    entity *asked* for one (that is the push-driven-update contract: a
    coordinator push must reach ``async_write_ha_state`` with no polling).
    """

    #: Real HA's ``Entity`` declares this as a class attribute that stays
    #: unset until the entity is added to a platform; log lines that mention
    #: ``self.entity_id`` must not explode in a test.
    entity_id: str | None = None

    @property
    def write_ha_state_calls(self) -> int:
        return getattr(self, "_write_ha_state_calls", 0)

    def async_write_ha_state(self) -> None:
        self._write_ha_state_calls = self.write_ha_state_calls + 1

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        attr_name = f"_attr_{name}"
        try:
            return object.__getattribute__(self, attr_name)
        except AttributeError:
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r} "
                f"(also tried {attr_name!r})"
            ) from None


def install() -> bool:
    """Install stubs unless real Home Assistant is available. Returns True if stubbed."""
    if "homeassistant" in sys.modules:
        return False
    if importlib.util.find_spec("homeassistant") is not None:
        return False

    ha = _module("homeassistant")

    # -- homeassistant.core -------------------------------------------------
    core = _module("homeassistant.core")

    def callback(func):  # HA's @callback is only a scheduling marker
        return func

    class HomeAssistant:
        pass

    class Event:
        def __init__(self, event_type: str, data: dict | None = None) -> None:
            self.event_type = event_type
            self.data = data or {}

    class CoreState(Enum):
        running = "RUNNING"
        not_running = "NOT_RUNNING"

    core.callback = callback
    core.HomeAssistant = HomeAssistant
    core.Event = Event
    core.CoreState = CoreState

    # -- homeassistant.const --------------------------------------------------
    const = _module("homeassistant.const")
    const.PERCENTAGE = "%"
    const.CONF_ADDRESS = "address"
    const.CONF_SERVICE_DATA = "service_data"
    const.ATTR_TEMPERATURE = "temperature"
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"

    class UnitOfTemperature(StrEnum):
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    class UnitOfTime(StrEnum):
        SECONDS = "s"
        MINUTES = "min"
        HOURS = "h"

    class Platform(StrEnum):
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        CLIMATE = "climate"
        FAN = "fan"
        NUMBER = "number"
        SENSOR = "sensor"
        SWITCH = "switch"

    class EntityCategory(StrEnum):
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    const.UnitOfTemperature = UnitOfTemperature
    const.UnitOfTime = UnitOfTime
    const.Platform = Platform
    const.EntityCategory = EntityCategory

    # -- homeassistant.exceptions -------------------------------------------
    exceptions = _module("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    # -- homeassistant.data_entry_flow ---------------------------------------
    data_entry_flow = _module("homeassistant.data_entry_flow")
    data_entry_flow.FlowResult = dict

    # -- homeassistant.config_entries ----------------------------------------
    config_entries = _module("homeassistant.config_entries")

    class ConfigEntry:
        """Constructor-free stub; tests build instances via SimpleNamespace-like use."""

        def __class_getitem__(cls, item):
            return cls

    class ConfigFlow:
        """Behavioral subset of HA's ConfigFlow used by config-flow tests."""

        def __init_subclass__(cls, *, domain: str | None = None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls._domain = domain

        hass = None
        context: dict = {}

        async def async_set_unique_id(self, unique_id, *, raise_on_progress=True):
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def _async_current_ids(self):
            return set()

        def _async_in_progress(self):
            return []

        def _set_confirm_only(self) -> None:
            pass

        def async_abort(self, *, reason: str):
            return {"type": "abort", "reason": reason}

        def async_show_form(self, *, step_id: str, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                "description_placeholders": description_placeholders,
            }

        def async_create_entry(self, *, title: str, data):
            return {"type": "create_entry", "title": title, "data": data}

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlowResult = dict
    config_entries.ConfigFlow = ConfigFlow

    # -- homeassistant.components(.bluetooth[.match]) ------------------------
    components = _module("homeassistant.components")
    bluetooth = _module("homeassistant.components.bluetooth")
    components.bluetooth = bluetooth

    class BluetoothScanningMode(Enum):
        PASSIVE = "passive"
        ACTIVE = "active"

    class BluetoothChange(Enum):
        ADVERTISEMENT = 1

    class BluetoothServiceInfoBleak:
        """Duck-typed like HA's real dataclass: device + advertisement + metadata."""

        def __init__(
            self,
            *,
            name: str,
            address: str,
            rssi: int,
            device: Any,
            advertisement: Any,
            source: str,
            connectable: bool = True,
            service_uuids: list[str] | None = None,
            manufacturer_data: dict | None = None,
        ) -> None:
            self.name = name
            self.address = address
            self.rssi = rssi
            self.device = device
            self.advertisement = advertisement
            self.source = source
            self.connectable = connectable
            self.service_uuids = service_uuids or []
            self.manufacturer_data = manufacturer_data or {}

    def async_discovered_service_info(hass, connectable=True):
        return []

    def async_ble_device_from_address(hass, address, connectable=True):
        return None

    def async_last_service_info(hass, address, connectable=True):
        return None

    def async_register_callback(hass, callback_fn, matcher, mode):
        return lambda: None

    def async_scanner_by_source(hass, source):
        return None

    bluetooth.BluetoothScanningMode = BluetoothScanningMode
    bluetooth.BluetoothChange = BluetoothChange
    bluetooth.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
    bluetooth.async_discovered_service_info = async_discovered_service_info
    bluetooth.async_ble_device_from_address = async_ble_device_from_address
    bluetooth.async_last_service_info = async_last_service_info
    bluetooth.async_register_callback = async_register_callback
    bluetooth.async_scanner_by_source = async_scanner_by_source

    # -- habluetooth ---------------------------------------------------------
    # habluetooth ships inside Home Assistant, not in this fork's test deps.
    # The integration imports exactly one symbol from it (`get_manager`, for
    # live connection-slot allocations); a test that exercises allocation
    # lookups monkeypatches `get_manager` in the module under test, so the
    # stub only has to exist and to fail loudly if something forgets to.
    habluetooth = _module("habluetooth")

    @dataclasses.dataclass(frozen=True)
    class HaBluetoothSlotAllocations:
        source: str
        slots: int
        free: int
        allocated: list[str]

    def get_manager():
        raise RuntimeError("habluetooth manager is not set (test stub)")

    habluetooth.HaBluetoothSlotAllocations = HaBluetoothSlotAllocations
    habluetooth.get_manager = get_manager

    bluetooth_match = _module("homeassistant.components.bluetooth.match")
    bluetooth.match = bluetooth_match
    ADDRESS = "address"

    class BluetoothCallbackMatcher(dict):
        """Real HA type is a TypedDict; a plain dict is a faithful stand-in."""

    bluetooth_match.ADDRESS = ADDRESS
    bluetooth_match.BluetoothCallbackMatcher = BluetoothCallbackMatcher

    # -- homeassistant.components.climate ------------------------------------
    climate = _module("homeassistant.components.climate")
    components.climate = climate

    class HVACMode(StrEnum):
        OFF = "off"
        HEAT = "heat"
        COOL = "cool"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"
        HEAT_COOL = "heat_cool"

    class ClimateEntityFeature(IntFlag):
        TARGET_TEMPERATURE = 1
        FAN_MODE = 8
        PRESET_MODE = 16
        TURN_OFF = 128
        TURN_ON = 256

    class ClimateEntity(_WriteStateRecorder):
        # Mirror homeassistant.components.climate.ClimateEntity exactly: only the
        # temperature attrs default to None; hvac_mode/fan_mode/preset_mode are
        # declared without defaults, so reading them before the entity assigns
        # them raises AttributeError (the live failure this suite must catch).
        _attr_current_temperature = None
        _attr_target_temperature = None

        @property
        def hvac_mode(self):
            return self._attr_hvac_mode

        @property
        def current_temperature(self):
            return self._attr_current_temperature

        @property
        def target_temperature(self):
            return self._attr_target_temperature

        @property
        def fan_mode(self):
            return self._attr_fan_mode

        @property
        def preset_mode(self):
            return self._attr_preset_mode

    climate.ATTR_HVAC_MODE = "hvac_mode"
    climate.HVACMode = HVACMode
    climate.ClimateEntityFeature = ClimateEntityFeature
    climate.ClimateEntity = ClimateEntity

    # -- homeassistant.components.fan ----------------------------------------
    fan = _module("homeassistant.components.fan")
    components.fan = fan

    class FanEntityFeature(IntFlag):
        SET_SPEED = 1
        OSCILLATE = 2
        DIRECTION = 4
        PRESET_MODE = 8
        TURN_OFF = 16
        TURN_ON = 32

    class FanEntity(_WriteStateRecorder):
        _attr_is_on = None
        _attr_percentage = None
        _attr_preset_mode = None

        @property
        def is_on(self):
            return self._attr_is_on

        @property
        def percentage(self):
            return self._attr_percentage

        @property
        def preset_mode(self):
            return self._attr_preset_mode

    fan.FanEntityFeature = FanEntityFeature
    fan.FanEntity = FanEntity

    # -- homeassistant.components.sensor -------------------------------------
    sensor = _module("homeassistant.components.sensor")
    components.sensor = sensor

    class SensorDeviceClass(StrEnum):
        TEMPERATURE = "temperature"
        DURATION = "duration"
        ENUM = "enum"

    class SensorStateClass(StrEnum):
        MEASUREMENT = "measurement"

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: Any = None
        device_class: Any = None
        state_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        translation_key: Any = None
        icon: Any = None
        native_unit_of_measurement: Any = None
        options: Any = None

    class SensorEntity(_WriteStateRecorder):
        _attr_native_value = None

        @property
        def native_value(self):
            return self._attr_native_value

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorEntity = SensorEntity

    # -- homeassistant.components.binary_sensor ------------------------------
    binary_sensor = _module("homeassistant.components.binary_sensor")
    components.binary_sensor = binary_sensor

    class BinarySensorDeviceClass(StrEnum):
        CONNECTIVITY = "connectivity"
        PROBLEM = "problem"

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription:
        key: str
        name: Any = None
        device_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        translation_key: Any = None
        icon: Any = None

    class BinarySensorEntity(_WriteStateRecorder):
        _attr_is_on = None

        @property
        def is_on(self):
            return self._attr_is_on

    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    binary_sensor.BinarySensorEntityDescription = BinarySensorEntityDescription
    binary_sensor.BinarySensorEntity = BinarySensorEntity

    # -- homeassistant.components.switch -------------------------------------
    switch = _module("homeassistant.components.switch")
    components.switch = switch

    class SwitchDeviceClass(StrEnum):
        OUTLET = "outlet"
        SWITCH = "switch"

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class SwitchEntityDescription:
        key: str
        name: Any = None
        device_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        translation_key: Any = None
        icon: Any = None

    class SwitchEntity(_WriteStateRecorder):
        _attr_is_on = None

        @property
        def is_on(self):
            return self._attr_is_on

    switch.SwitchDeviceClass = SwitchDeviceClass
    switch.SwitchEntityDescription = SwitchEntityDescription
    switch.SwitchEntity = SwitchEntity

    # -- homeassistant.components.number -------------------------------------
    number = _module("homeassistant.components.number")
    components.number = number

    class NumberDeviceClass(StrEnum):
        DURATION = "duration"
        TEMPERATURE = "temperature"

    class NumberMode(StrEnum):
        AUTO = "auto"
        BOX = "box"
        SLIDER = "slider"

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class NumberEntityDescription:
        key: str
        name: Any = None
        device_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        translation_key: Any = None
        icon: Any = None
        native_unit_of_measurement: Any = None
        native_min_value: Any = None
        native_max_value: Any = None
        native_step: Any = None
        mode: Any = None

    class NumberEntity(_WriteStateRecorder):
        _attr_native_value = None
        _attr_native_max_value = None
        _attr_native_min_value = None

        @property
        def native_value(self):
            return self._attr_native_value

    number.NumberDeviceClass = NumberDeviceClass
    number.NumberMode = NumberMode
    number.NumberEntityDescription = NumberEntityDescription
    number.NumberEntity = NumberEntity

    # -- homeassistant.components.button -------------------------------------
    button = _module("homeassistant.components.button")
    components.button = button

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class ButtonEntityDescription:
        key: str
        name: Any = None
        device_class: Any = None
        entity_category: Any = None
        entity_registry_enabled_default: bool = True
        translation_key: Any = None
        icon: Any = None

    class ButtonEntity(_WriteStateRecorder):
        pass

    button.ButtonEntityDescription = ButtonEntityDescription
    button.ButtonEntity = ButtonEntity

    # -- homeassistant.helpers ------------------------------------------------
    helpers = _module("homeassistant.helpers")

    device_registry = _module("homeassistant.helpers.device_registry")
    helpers.device_registry = device_registry
    device_registry.CONNECTION_BLUETOOTH = "bluetooth"

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    device_registry.DeviceInfo = DeviceInfo

    entity = _module("homeassistant.helpers.entity")
    helpers.entity = entity
    entity.DeviceInfo = DeviceInfo

    entity_platform = _module("homeassistant.helpers.entity_platform")
    helpers.entity_platform = entity_platform

    class AddEntitiesCallback:
        pass

    class AddConfigEntryEntitiesCallback:
        pass

    entity_platform.AddEntitiesCallback = AddEntitiesCallback
    entity_platform.AddConfigEntryEntitiesCallback = AddConfigEntryEntitiesCallback

    update_coordinator = _module("homeassistant.helpers.update_coordinator")
    helpers.update_coordinator = update_coordinator

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        """Faithful enough stand-in: push updates fan out to registered listeners.

        Real DataUpdateCoordinator also supports polling via update_interval;
        BedJetCoordinator never sets one (push-driven), so polling is not
        modeled here.
        """

        def __init__(
            self,
            hass=None,
            logger=None,
            *,
            config_entry=None,
            name: str | None = None,
            update_interval=None,
            **kwargs: Any,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.config_entry = config_entry
            self.name = name
            self.update_interval = update_interval
            self.data: Any = None
            self.last_update_success = True
            self._listeners: dict[object, tuple[Callable[[], None], Any]] = {}

        def __class_getitem__(cls, item):
            return cls

        @callback
        def async_set_updated_data(self, data: Any) -> None:
            self.data = data
            self.last_update_success = True
            for update_callback, _context in list(self._listeners.values()):
                update_callback()

        @callback
        def async_update_listeners(self) -> None:
            """Notify listeners without changing .data (real HA API)."""
            for update_callback, _context in list(self._listeners.values()):
                update_callback()

        @callback
        def async_add_listener(
            self, update_callback: Callable[[], None], context: Any = None
        ) -> Callable[[], None]:
            token = object()
            self._listeners[token] = (update_callback, context)

            def _remove() -> None:
                self._listeners.pop(token, None)

            return _remove

        async def async_shutdown(self) -> None:
            self._listeners.clear()

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    class CoordinatorEntity(_WriteStateRecorder):
        """Registers with the coordinator immediately (tests have no hass lifecycle)."""

        def __init__(self, coordinator: DataUpdateCoordinator, context: Any = None) -> None:
            self.coordinator = coordinator
            self.coordinator_context = context
            self._on_remove: list[Callable[[], None]] = []
            self._remove_listener = coordinator.async_add_listener(
                self._handle_coordinator_update, context
            )

        def __class_getitem__(cls, item):
            return cls

        @property
        def available(self) -> bool:
            return self.coordinator.last_update_success

        async def async_update(self) -> None:
            pass

        async def async_added_to_hass(self) -> None:
            """Real HA subscribes to the coordinator here; the stub did it in __init__."""

        async def async_will_remove_from_hass(self) -> None:
            """Called before an entity is removed, exactly like real HA."""

        def async_on_remove(self, func: Callable[[], None]) -> None:
            self._on_remove.append(func)

        async def async_remove(self, *, force_remove: bool = False) -> None:
            """Mirror real HA's removal order: will_remove, then on_remove LIFO."""
            await self.async_will_remove_from_hass()
            while self._on_remove:
                self._on_remove.pop()()

        @callback
        def _handle_coordinator_update(self) -> None:
            self.async_write_ha_state()

    update_coordinator.CoordinatorEntity = CoordinatorEntity

    # -- homeassistant.util(.dt / .percentage) --------------------------------
    util = _module("homeassistant.util")
    ha.util = util

    dt_util = _module("homeassistant.util.dt")
    util.dt = dt_util

    import datetime as _datetime

    def dt_now(time_zone=None):
        return _datetime.datetime.now(_datetime.UTC)

    dt_util.now = dt_now
    dt_util.UTC = _datetime.UTC

    ha.core = core
    ha.const = const
    ha.exceptions = exceptions
    ha.config_entries = config_entries
    ha.components = components
    ha.helpers = helpers
    ha.data_entry_flow = data_entry_flow

    return True
