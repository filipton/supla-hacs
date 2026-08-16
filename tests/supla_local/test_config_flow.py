"""Config and options flow."""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.supla_local import config_flow
from custom_components.supla_local.const import (
    CONF_CUSTOM_PORTS,
    CONF_ENABLE_TLS,
    CONF_OFFLINE_AFTER,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DEFAULT_OFFLINE_AFTER,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


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


@pytest.fixture
def default_ports(monkeypatch) -> tuple[int, int]:
    """Stand-ins for 2015/2016, so the suite never fights a real server."""
    plain, tls = free_port(), free_port()
    monkeypatch.setattr(config_flow, "DEFAULT_TCP_PORT", plain)
    monkeypatch.setattr(config_flow, "DEFAULT_TLS_PORT", tls)
    return plain, tls


async def start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


def main(**overrides):
    return {
        CONF_ENABLE_TLS: False,
        CONF_OFFLINE_AFTER: DEFAULT_OFFLINE_AFTER,
        CONF_CUSTOM_PORTS: False,
        **overrides,
    }


# --- the common path -------------------------------------------------------


async def test_the_first_screen_never_asks_about_ports(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert set(result["data_schema"].schema) == {
        CONF_ENABLE_TLS,
        CONF_OFFLINE_AFTER,
        CONF_CUSTOM_PORTS,
    }


async def test_the_address_is_offered_to_the_form(hass: HomeAssistant) -> None:
    result = await start(hass)
    placeholders = result["description_placeholders"]
    assert placeholders["host"]
    assert placeholders["ports"]


async def test_accepting_the_defaults_creates_the_entry(
    hass: HomeAssistant, default_ports: tuple[int, int]
) -> None:
    plain, tls = default_ports
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], main())
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SUPLA Local"
    assert result["data"][CONF_TCP_PORT] == plain
    assert result["data"][CONF_TLS_PORT] == tls
    # The checkbox is a question, not a setting.
    assert CONF_CUSTOM_PORTS not in result["data"]


async def test_only_one_entry_is_allowed(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_taken_default_ports_point_at_the_custom_ports_box(
    hass: HomeAssistant, taken_port: int, monkeypatch
) -> None:
    monkeypatch.setattr(config_flow, "DEFAULT_TCP_PORT", taken_port)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], main())

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "default_ports_in_use"}


# --- the ports screen ------------------------------------------------------


async def test_asking_for_custom_ports_opens_a_second_screen(
    hass: HomeAssistant,
) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True, CONF_ENABLE_TLS: True})
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ports"
    assert set(result["data_schema"].schema) == {CONF_TCP_PORT, CONF_TLS_PORT}

    wanted = free_port()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TCP_PORT: wanted, CONF_TLS_PORT: free_port()}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TCP_PORT] == wanted


async def test_the_tls_port_is_not_asked_for_when_tls_is_off(
    hass: HomeAssistant,
) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True})
    )
    assert result["step_id"] == "ports"
    assert set(result["data_schema"].schema) == {CONF_TCP_PORT}


async def test_a_port_that_is_already_listening_is_rejected(
    hass: HomeAssistant, taken_port: int
) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True})
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TCP_PORT: taken_port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TCP_PORT: "port_in_use"}


async def test_the_tls_port_must_differ(hass: HomeAssistant) -> None:
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True, CONF_ENABLE_TLS: True})
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TCP_PORT: 2015, CONF_TLS_PORT: 2015}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TLS_PORT: "same_port"}


# --- options ---------------------------------------------------------------


async def test_options_change_settings_without_touching_ports(
    hass: HomeAssistant, entry: MockConfigEntry, port: int
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert CONF_TCP_PORT not in result["data_schema"].schema

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], main(**{CONF_OFFLINE_AFTER: 25, CONF_CUSTOM_PORTS: True})
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TCP_PORT: port}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.offline_after == 25


async def test_options_can_move_the_ports(
    hass: HomeAssistant, entry: MockConfigEntry, port: int
) -> None:
    """The old port has to be released before the new one is bound."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True})
    )
    assert result["step_id"] == "ports"

    wanted = free_port()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TCP_PORT: wanted}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.bound_ports == [wanted]


async def test_the_options_flow_accepts_its_own_current_port(
    hass: HomeAssistant, port: int
) -> None:
    """The running server owns the port; that must not read as "in use"."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], main(**{CONF_CUSTOM_PORTS: True})
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TCP_PORT: port}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_custom_ports_box_remembers_that_it_was_used(
    hass: HomeAssistant, entry: MockConfigEntry, port: int
) -> None:
    """A non-default port is what ticks the box on next time."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    marker = next(
        key for key in result["data_schema"].schema if key == CONF_CUSTOM_PORTS
    )
    assert marker.default() is True
