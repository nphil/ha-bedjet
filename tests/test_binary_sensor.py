"""Tests for the BedJet binary sensor platform: unique_ids and diagnostic gating."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.bedjet.binary_sensor import SENSORS, BedJetBinarySensorEntity

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = SimpleNamespace(
            connection_test_passed=True, dual_zone=False, units_setup=True
        )

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def descriptor_by_key(key: str):
    return next(d for d in SENSORS if d.key == key)


def test_all_unique_ids_and_all_diagnostic_disabled_by_default() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    for descriptor in SENSORS:
        entity = BedJetBinarySensorEntity(coordinator, "Bedjetty", descriptor)
        assert entity.unique_id == f"{ADDRESS}_{descriptor.key}"
        assert descriptor.entity_registry_enabled_default is False


def test_values_reflect_state_via_value_fn() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)

    connection_test = BedJetBinarySensorEntity(
        coordinator, "Bedjetty", descriptor_by_key("connection_test")
    )
    dual_zone = BedJetBinarySensorEntity(coordinator, "Bedjetty", descriptor_by_key("dual_zone"))
    units_setup = BedJetBinarySensorEntity(
        coordinator, "Bedjetty", descriptor_by_key("units_setup")
    )

    assert connection_test.is_on is True
    assert dual_zone.is_on is False
    assert units_setup.is_on is True


def test_no_update_before_first_decoded_frame() -> None:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    coordinator.data = None
    entity = BedJetBinarySensorEntity(coordinator, "Bedjetty", descriptor_by_key("dual_zone"))
    assert entity.is_on is None
