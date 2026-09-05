"""Tests for the BedJet fan entity: on/off state and percent passthrough."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bedjet.fan import BedJetFanEntity
from custom_components.bedjet.pybedjet.const import BedJetMode

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.hold_connection = True
        self.mode_calls: list[BedJetMode] = []
        self.fan_calls: list[int] = []

    async def set_mode(self, mode) -> None:
        self.mode_calls.append(mode)

    async def set_fan_percent(self, percent: int) -> None:
        self.fan_calls.append(percent)


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = SimpleNamespace(mode=BedJetMode.STANDBY, fan_percent=5)

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def make_entity() -> tuple[BedJetFanEntity, FakeCoordinator, FakeDevice]:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    return BedJetFanEntity(coordinator, "Bedjetty"), coordinator, device


def test_unique_id_is_address_fan() -> None:
    entity, _coordinator, _device = make_entity()
    assert entity.unique_id == f"{ADDRESS}_fan"


def test_standby_is_off_with_zero_percentage() -> None:
    entity, coordinator, _device = make_entity()
    coordinator.data = SimpleNamespace(mode=BedJetMode.STANDBY, fan_percent=55)
    entity._async_update_attrs()
    assert entity.is_on is False
    assert entity.percentage == 0


def test_active_mode_reports_fan_percent_directly() -> None:
    entity, coordinator, _device = make_entity()
    coordinator.data = SimpleNamespace(mode=BedJetMode.HEAT, fan_percent=65)
    entity._async_update_attrs()
    assert entity.is_on is True
    assert entity.percentage == 65


def test_turn_on_from_standby_enters_cool_mode_and_sets_percentage() -> None:
    entity, coordinator, device = make_entity()
    coordinator.data = SimpleNamespace(mode=BedJetMode.STANDBY, fan_percent=5)

    asyncio.run(entity.async_turn_on(percentage=80))

    assert device.mode_calls == [BedJetMode.COOL]
    assert device.fan_calls == [80]


def test_turn_on_while_already_active_only_sets_percentage() -> None:
    entity, coordinator, device = make_entity()
    coordinator.data = SimpleNamespace(mode=BedJetMode.HEAT, fan_percent=40)

    asyncio.run(entity.async_turn_on(percentage=40))

    assert device.mode_calls == []
    assert device.fan_calls == [40]


def test_turn_off_sends_standby_mode() -> None:
    entity, _coordinator, device = make_entity()
    asyncio.run(entity.async_turn_off())
    assert device.mode_calls == [BedJetMode.STANDBY]


def test_set_percentage_zero_turns_off_instead_of_setting_speed() -> None:
    entity, _coordinator, device = make_entity()
    asyncio.run(entity.async_set_percentage(0))
    assert device.mode_calls == [BedJetMode.STANDBY]
    assert device.fan_calls == []
