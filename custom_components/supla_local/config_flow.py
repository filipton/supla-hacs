"""Config and options flow for SUPLA Local.

The first screen is what everyone needs: the address to type into the devices,
whether to accept TLS, and how quickly a device that lost power is noticed.
Ports live behind a checkbox, because SUPLA devices only ever look for 2015 and
2016 and moving them is a last resort.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CUSTOM_PORTS,
    CONF_ENABLE_TLS,
    CONF_OFFLINE_AFTER,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DEFAULT_ENABLE_TLS,
    DEFAULT_OFFLINE_AFTER,
    DEFAULT_TCP_PORT,
    DEFAULT_TLS_PORT,
    DOMAIN,
    MAX_OFFLINE_AFTER,
    MIN_OFFLINE_AFTER,
)
from .manager import LISTEN_HOST

_LOGGER = logging.getLogger(__name__)

TITLE = "SUPLA Local"

PORT = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
OFFLINE_AFTER = vol.All(
    vol.Coerce(int), vol.Range(min=MIN_OFFLINE_AFTER, max=MAX_OFFLINE_AFTER)
)


def main_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_ENABLE_TLS,
                default=current.get(CONF_ENABLE_TLS, DEFAULT_ENABLE_TLS),
            ): bool,
            vol.Required(
                CONF_OFFLINE_AFTER,
                default=current.get(CONF_OFFLINE_AFTER, DEFAULT_OFFLINE_AFTER),
            ): OFFLINE_AFTER,
            vol.Required(CONF_CUSTOM_PORTS, default=uses_custom_ports(current)): bool,
        }
    )


def ports_schema(current: dict[str, Any], *, tls_enabled: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_TCP_PORT, default=current.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
        ): PORT
    }
    if tls_enabled:
        key = vol.Required(
            CONF_TLS_PORT, default=current.get(CONF_TLS_PORT, DEFAULT_TLS_PORT)
        )
        fields[key] = PORT
    return vol.Schema(fields)


def uses_custom_ports(current: dict[str, Any]) -> bool:
    """Whether either port has been moved off the SUPLA default."""
    return (
        current.get(CONF_TCP_PORT, DEFAULT_TCP_PORT) != DEFAULT_TCP_PORT
        or current.get(CONF_TLS_PORT, DEFAULT_TLS_PORT) != DEFAULT_TLS_PORT
    )


class SuplaFlowSteps:
    """The two screens, shared by the config flow and the options flow."""

    hass: HomeAssistant

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # --- filled in by the two concrete flows ---

    @property
    def _current(self) -> dict[str, Any]:
        return {}

    def _ports_in_use(self) -> tuple[int, ...]:
        return ()

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        raise NotImplementedError

    def _show(
        self, step_id: str, schema: vol.Schema, errors: dict[str, str], host: str
    ) -> ConfigFlowResult:
        raise NotImplementedError

    # --- the screens ---

    async def _async_step_main(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data = {
                CONF_ENABLE_TLS: bool(user_input[CONF_ENABLE_TLS]),
                CONF_OFFLINE_AFTER: int(user_input[CONF_OFFLINE_AFTER]),
            }
            if user_input[CONF_CUSTOM_PORTS]:
                return await self.async_step_ports()

            self._data[CONF_TCP_PORT] = DEFAULT_TCP_PORT
            self._data[CONF_TLS_PORT] = DEFAULT_TLS_PORT
            if not await self._async_validate(self._data):
                return await self._async_finish(self._data)
            # The standard ports are taken, so custom ports are the way out.
            errors = {"base": "default_ports_in_use"}

        return self._show(
            step_id,
            main_schema(user_input or self._current),
            errors,
            await self._host(),
        )

    async def async_step_ports(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Second screen, reached only by asking for custom ports."""
        tls_enabled = self._data[CONF_ENABLE_TLS]
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {
                **self._data,
                CONF_TCP_PORT: int(user_input[CONF_TCP_PORT]),
                CONF_TLS_PORT: int(user_input.get(CONF_TLS_PORT, DEFAULT_TLS_PORT)),
            }
            errors = await self._async_validate(candidate)
            if not errors:
                return await self._async_finish(candidate)

        return self._show(
            "ports",
            ports_schema(
                {**self._current, **(user_input or {})}, tls_enabled=tls_enabled
            ),
            errors,
            await self._host(),
        )

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, str]:
        return await _async_validate(self.hass, data, in_use=self._ports_in_use())

    async def _host(self) -> str:
        return await _async_host(self.hass)


class SuplaLocalConfigFlow(SuplaFlowSteps, ConfigFlow, domain=DOMAIN):
    """One entry per Home Assistant: the entry is the server, not a device."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self._async_step_main("user", user_input)

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title=TITLE, data=data)

    def _show(
        self, step_id: str, schema: vol.Schema, errors: dict[str, str], host: str
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders=_placeholders(host, self._data),
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return SuplaLocalOptionsFlow()


class SuplaLocalOptionsFlow(SuplaFlowSteps, OptionsFlow):
    """Change the settings later; the entry reloads and rebinds."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_main("init", user_input)

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data=data)

    def _show(
        self, step_id: str, schema: vol.Schema, errors: dict[str, str], host: str
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders=_placeholders(
                host, {**self._current, **self._data}
            ),
        )

    def _ports_in_use(self) -> tuple[int, ...]:
        """The running server holds its own ports, so those are not "taken".

        What it actually bound is authoritative; the configured values are the
        fallback for an entry that failed to start.
        """
        manager = getattr(self.config_entry, "runtime_data", None)
        current = self._current
        return (tuple(manager.bound_ports) if manager is not None else ()) + (
            int(current.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)),
            int(current.get(CONF_TLS_PORT, DEFAULT_TLS_PORT)),
        )


def _placeholders(host: str, data: dict[str, Any]) -> dict[str, str]:
    tcp_port = data.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
    tls_port = data.get(CONF_TLS_PORT, DEFAULT_TLS_PORT)
    return {
        "host": str(host),
        "tcp_port": str(tcp_port),
        "tls_port": str(tls_port),
        "ports": (
            f"**{tcp_port}** with SSL off, **{tls_port}** with SSL on"
            if data.get(CONF_ENABLE_TLS, DEFAULT_ENABLE_TLS)
            else f"**{tcp_port}**, with SSL turned off"
        ),
    }


async def _async_validate(
    hass: HomeAssistant, data: dict[str, Any], *, in_use: tuple[int, ...]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    tcp_port = int(data[CONF_TCP_PORT])
    tls_enabled = bool(data[CONF_ENABLE_TLS])
    tls_port = int(data[CONF_TLS_PORT])

    if tls_enabled and tcp_port == tls_port:
        errors[CONF_TLS_PORT] = "same_port"
        return errors

    wanted = [(CONF_TCP_PORT, tcp_port)]
    if tls_enabled:
        wanted.append((CONF_TLS_PORT, tls_port))

    for field, port in wanted:
        if port in in_use:
            continue
        if not await hass.async_add_executor_job(_port_is_free, port):
            errors[field] = "port_in_use"

    return errors


def _port_is_free(port: int) -> bool:
    """Bind briefly to see whether something else already listens there."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((LISTEN_HOST, port))
        except OSError:
            return False
    return True


async def _async_host(hass: HomeAssistant) -> str:
    """Address to type into the device's web config, best effort."""
    try:
        from homeassistant.components import network

        source_ip = await network.async_get_source_ip(hass)
    except Exception:  # noqa: BLE001 - purely cosmetic, never block setup
        _LOGGER.debug("Could not determine the Home Assistant address", exc_info=True)
        return "this machine's IP address"
    return source_ip or "this machine's IP address"
