"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
from fake_device import GUID, FakeDevice
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.supla_local.const import (
    CONF_ENABLE_TLS,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DOMAIN,
    STORAGE_SAVE_DELAY,
)

GUID_HEX = GUID.hex().upper()


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry bound to an ephemeral port, with TLS off.

    TLS is skipped so the tests do not pay for RSA key generation.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SUPLA Local",
        data={CONF_TCP_PORT: 0, CONF_ENABLE_TLS: False, CONF_TLS_PORT: 0},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def port(hass: HomeAssistant, entry: MockConfigEntry) -> int:
    """Set the entry up and return the port the server actually bound."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data.bound_ports[0]


@pytest.fixture
async def device(port: int) -> AsyncGenerator[FakeDevice, None]:
    fake = FakeDevice()
    await fake.connect(port)
    yield fake
    await fake.close()


async def wait_for(predicate, timeout: float = 5.0) -> None:
    """Poll until a condition holds; the device link is asynchronous."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


async def flush_store(hass: HomeAssistant) -> None:
    """Force the debounced storage write out.

    Home Assistant coalesces repeated delayed saves by pushing the deadline
    back, so the first firing may only reschedule rather than write.
    """
    for multiple in (1, 2, 3):
        async_fire_time_changed(
            hass,
            dt_util.utcnow() + timedelta(seconds=STORAGE_SAVE_DELAY * multiple + 1),
        )
        await hass.async_block_till_done()


@pytest.fixture
async def connect(port: int):
    """Bring up extra fake devices, each with its own channel set."""
    started: list[FakeDevice] = []

    async def _connect(channels) -> FakeDevice:
        fake = FakeDevice()
        await fake.connect(port, channels=channels)
        started.append(fake)
        return fake

    yield _connect
    for fake in started:
        await fake.close()


def entity_id_for(hass: HomeAssistant, platform: str, suffix: str) -> str:
    """Look an entity up by its stable unique id rather than by name."""
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{GUID_HEX}-{suffix}"
    )
    assert entity_id is not None, f"no {platform} entity for {suffix}"
    return entity_id


async def nth_command(device: FakeDevice, channel: int, index: int = 0) -> bytes:
    """Wait for the index-th set-value command the server sent to a channel."""

    def sent() -> list[bytes]:
        return [value for number, value in device.commands if number == channel]

    await wait_for(lambda: len(sent()) > index)
    return sent()[index]
