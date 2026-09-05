"""Tests for the BedJet sensor platform: unique_ids, values, and the scanner
sensor's exemption from the "no data yet" guard (it must work even while the
device has never decoded a frame, since it just reports proxy attribution).
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.bedjet.pybedjet.const import BedJetNotification
from custom_components.bedjet.sensor import SENSORS, BedJetSensorEntity

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.hold_connection = True
        self.scanner_source = "D4:D4:DA:9D:40:8A"
        self.state = SimpleNamespace(
            ambient_temp_c=24.5,
            actual_temp_c=25.0,
            notification=BedJetNotification.CLEAN_FILTER,
            bio_sequence_step=0,
            shutdown_reason=0,
            turbo_time=0,
            update_phase=0x15,
        )


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = device.state

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def descriptor_by_key(key: str):
    return next(d for d in SENSORS if d.key == key)


def make_entity(key: str, device: FakeDevice | None = None):
    device = device or FakeDevice()
    coordinator = FakeCoordinator(device)
    return BedJetSensorEntity(coordinator, "Bedjetty", descriptor_by_key(key)), coordinator, device


def test_all_unique_ids_are_address_prefixed_by_key() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    for descriptor in SENSORS:
        entity = BedJetSensorEntity(coordinator, "Bedjetty", descriptor)
        assert entity.unique_id == f"{ADDRESS}_{descriptor.key}"


def test_ambient_temperature_value() -> None:
    entity, _coordinator, _device = make_entity("ambient_temperature")
    assert entity.native_value == 24.5


def test_outlet_temperature_value() -> None:
    entity, _coordinator, _device = make_entity("outlet_temperature")
    assert entity.native_value == 25.0


def test_notification_value_is_lowercase_enum_name() -> None:
    entity, _coordinator, _device = make_entity("notification")
    assert entity.native_value == "clean_filter"


def test_notification_none_when_no_pending_notification() -> None:
    device = FakeDevice()
    device.state = SimpleNamespace(**{**device.state.__dict__, "notification": None})
    entity, _coordinator, _device = make_entity("notification", device)
    assert entity.native_value is None


def test_notification_none_member_renders_as_string_not_python_none() -> None:
    # Regression: BedJetNotification.NONE (value 0, "no notification
    # pending") must render as the string "none", distinct from the sensor
    # being unavailable because no frame has decoded a notification yet.
    device = FakeDevice()
    device.state = SimpleNamespace(
        **{**device.state.__dict__, "notification": BedJetNotification.NONE}
    )
    entity, _coordinator, _device = make_entity("notification", device)
    assert entity.native_value == "none"


def test_diagnostic_sensors_are_disabled_by_default() -> None:
    for key in ("bio_sequence_step", "shutdown_reason", "turbo_time", "update_phase", "scanner"):
        descriptor = descriptor_by_key(key)
        assert descriptor.entity_registry_enabled_default is False


def test_ambient_and_outlet_are_enabled_by_default() -> None:
    for key in ("ambient_temperature", "outlet_temperature"):
        descriptor = descriptor_by_key(key)
        assert descriptor.entity_registry_enabled_default is True

def test_notification_is_enabled_default_with_no_category() -> None:
    # Regression: notification was briefly diagnostic+enabled (an
    # inconsistent combination); the assignment lists it only under
    # "enabled by default", so it must carry no entity_category.
    descriptor = descriptor_by_key("notification")
    assert descriptor.entity_category is None
    assert descriptor.entity_registry_enabled_default is True


def test_scanner_sensor_updates_even_without_a_decoded_frame_yet() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    coordinator.data = None  # no status frame decoded yet
    entity = BedJetSensorEntity(coordinator, "Bedjetty", descriptor_by_key("scanner"))

    device.scanner_source = "AA:BB:CC:DD:EE:FF"
    entity._async_update_attrs()

    assert entity.native_value == "AA:BB:CC:DD:EE:FF"


def test_non_scanner_sensor_skips_update_without_a_decoded_frame() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    coordinator.data = None
    entity = BedJetSensorEntity(coordinator, "Bedjetty", descriptor_by_key("ambient_temperature"))

    # Never assigned because coordinator.data was None at update time.
    assert entity.native_value is None
