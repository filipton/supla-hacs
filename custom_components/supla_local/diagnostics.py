"""Diagnostics for SUPLA Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import device_entity_keys

TO_REDACT = {"email", "location_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SuplaConfigEntry
) -> dict[str, Any]:
    manager = entry.runtime_data

    devices = []
    for guid, snapshot in manager.devices.items():
        live = manager.registry.get(guid)
        devices.append(
            {
                "stored": snapshot.to_json(),
                "entities": [
                    {"platform": key.platform, "suffix": key.suffix, "kind": key.kind}
                    for key in device_entity_keys(snapshot)
                ],
                "online": bool(live and live.online),
                "last_seen": manager.last_seen.get(guid),
                "live": async_redact_data(live.to_dict(), TO_REDACT) if live else None,
            }
        )

    return {
        "server": {
            "running": manager.running,
            "tcp_port": manager.tcp_port,
            "tls_port": manager.tls_port,
            "bound_ports": manager.bound_ports,
        },
        "devices": devices,
    }
