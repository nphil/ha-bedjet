"""Tests for BedJetEntity._async_send_command: library errors -> HomeAssistantError.

Per the no-optimistic-state contract, every command entity method routes
through this helper instead of touching pybedjet directly, so a confirmation
timeout or a lost connection surfaces to Home Assistant as a service-call
error rather than leaking a raw pybedjet exception or failing silently.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.bedjet.entity import BedJetEntity
from custom_components.bedjet.pybedjet import BedJetCommandError, BedJetConnectionError
from homeassistant.exceptions import HomeAssistantError


class FakeDevice:
    def __init__(self) -> None:
        self.address = "FC:F5:C4:20:1A:92"


class FakeCoordinator:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.available = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


def make_entity() -> BedJetEntity:
    return BedJetEntity(FakeCoordinator(FakeDevice()), "Bedjetty")


def test_command_error_becomes_home_assistant_error() -> None:
    entity = make_entity()

    async def failing_command() -> None:
        raise BedJetCommandError("confirmation timed out")

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity._async_send_command(failing_command))


def test_connection_error_becomes_home_assistant_error() -> None:
    entity = make_entity()

    async def failing_command() -> None:
        raise BedJetConnectionError("not connected")

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity._async_send_command(failing_command))


def test_success_passes_through_args_and_raises_nothing() -> None:
    entity = make_entity()
    calls: list[tuple[int, str]] = []

    async def ok_command(value: int, *, label: str) -> None:
        calls.append((value, label))

    asyncio.run(entity._async_send_command(ok_command, 5, label="fan"))

    assert calls == [(5, "fan")]
