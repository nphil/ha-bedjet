"""Tests for the BedJet runtime_remaining number entity: minute rollover
into (hours, minutes) before calling the library, and value derivation from
the frame's timedeltas.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from custom_components.bedjet.number import BedJetNumberEntity

ADDRESS = "FC:F5:C4:20:1A:92"


class FakeDevice:
    def __init__(self) -> None:
        self.address = ADDRESS
        self.hold_connection = True
        self.runtime_calls: list[tuple[int, int]] = []

    async def set_runtime(self, hours: int, minutes: int) -> None:
        self.runtime_calls.append((hours, minutes))


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True
        self.data = SimpleNamespace(
            time_remaining=timedelta(minutes=90), max_runtime=timedelta(hours=10)
        )

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def make_entity() -> tuple[BedJetNumberEntity, FakeCoordinator, FakeDevice]:
    device = FakeDevice()
    coordinator = FakeCoordinator(device)
    return BedJetNumberEntity(coordinator, "Bedjetty"), coordinator, device


def test_unique_id() -> None:
    entity, _coordinator, _device = make_entity()
    assert entity.unique_id == f"{ADDRESS}_runtime_remaining"


def test_native_value_and_max_from_frame_timedeltas() -> None:
    entity, _coordinator, _device = make_entity()
    assert entity.native_value == 90
    assert entity.native_max_value == 600  # 10h in minutes


def test_set_value_under_an_hour_sends_zero_hours() -> None:
    entity, _coordinator, device = make_entity()
    asyncio.run(entity.async_set_native_value(45))
    assert device.runtime_calls == [(0, 45)]


def test_set_value_rolls_minutes_into_hours() -> None:
    entity, _coordinator, device = make_entity()
    asyncio.run(entity.async_set_native_value(125))
    assert device.runtime_calls == [(2, 5)]
