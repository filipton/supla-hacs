"""Config and options flow for SUPLA Local."""

from __future__ import annotations

import logging
import socket
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENABLE_TLS,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DEFAULT_ENABLE_TLS,
    DEFAULT_TCP_PORT,
    DEFAULT_TLS_PORT,
    DOMAIN,
)
from .manager import LISTEN_HOST

_LOGGER = logging.getLogger(__name__)

TITLE = "SUPLA Local"

PORT = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): PORT,
        vol.Required(CONF_ENABLE_TLS, default=DEFAULT_ENABLE_TLS): bool,
        vol.Required(CONF_TLS_PORT, default=DEFAULT_TLS_PORT): PORT,
    }
)


class SuplaLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per Home Assistant: the entry is the server, not a device."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(self.hass, user_input, in_use=())
            if not errors:
                return self.async_create_entry(title=TITLE, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_SCHEMA, user_input),
            errors=errors,
            description_placeholders={"host": await _async_host(self.hass)},
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return SuplaLocalOptionsFlow()


class SuplaLocalOptionsFlow(OptionsFlow):
    """Change the ports later; the entry reloads and rebinds."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}

        errors: dict[str, str] = {}
        if user_input is not None:
            # The running server holds its own ports, so those are not "taken".
            # What it actually bound is authoritative; the configured values are
            # the fallback for an entry that failed to start.
            manager = getattr(self.config_entry, "runtime_data", None)
            in_use = tuple(manager.bound_ports) if manager is not None else ()
            in_use += (
                int(current.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)),
                int(current.get(CONF_TLS_PORT, DEFAULT_TLS_PORT)),
            )
            errors = await _async_validate(self.hass, user_input, in_use=in_use)
            if not errors:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SCHEMA, user_input or current
            ),
            errors=errors,
            description_placeholders={"host": await _async_host(self.hass)},
        )


async def _async_validate(
    hass: HomeAssistant, user_input: dict[str, Any], *, in_use: tuple[int, ...]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    tcp_port = int(user_input[CONF_TCP_PORT])
    tls_enabled = bool(user_input[CONF_ENABLE_TLS])
    tls_port = int(user_input[CONF_TLS_PORT])

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
        return "<Home Assistant IP>"
    return source_ip or "<Home Assistant IP>"
