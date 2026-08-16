"""Config and options flow."""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.supla_local.const import (
    CONF_ENABLE_TLS,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DOMAIN,
)


def free_port() -> int:
    """A port nothing is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return sock.getsockname()[1]


@pytest.fixture
def taken_port() -> Iterator[int]:
    """A port held open for the duration of the test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


async def start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_the_user_flow_creates_the_entry(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    wanted = free_port()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: wanted, CONF_ENABLE_TLS: False, CONF_TLS_PORT: 2016},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SUPLA Local"
    assert result["data"][CONF_TCP_PORT] == wanted


async def test_only_one_entry_is_allowed(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_a_port_that_is_already_listening_is_rejected(
    hass: HomeAssistant, taken_port: int
) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: taken_port, CONF_ENABLE_TLS: False, CONF_TLS_PORT: 2016},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TCP_PORT: "port_in_use"}


async def test_the_tls_port_must_differ(hass: HomeAssistant) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: 2015, CONF_ENABLE_TLS: True, CONF_TLS_PORT: 2015},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TLS_PORT: "same_port"}


async def test_a_disabled_tls_port_is_not_checked(
    hass: HomeAssistant, taken_port: int
) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: free_port(), CONF_ENABLE_TLS: False, CONF_TLS_PORT: taken_port},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_changing_options_reloads_the_listener(
    hass: HomeAssistant, entry: MockConfigEntry, port: int
) -> None:
    """The old port has to be released before the new one is bound."""
    assert port != 0

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    wanted = free_port()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: wanted, CONF_ENABLE_TLS: False, CONF_TLS_PORT: 2016},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.bound_ports == [wanted]


async def test_the_options_flow_accepts_its_own_current_port(
    hass: HomeAssistant, port: int
) -> None:
    """The running server owns the port; that must not read as "in use"."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_TCP_PORT: port, CONF_ENABLE_TLS: False, CONF_TLS_PORT: 2016},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
