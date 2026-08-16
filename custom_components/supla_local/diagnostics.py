"""Diagnostics for SUPLA Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry, config_map
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
                "config": {
                    str(channel.number): {
                        "spec": channel.config_spec.name if channel.config_spec else None,
                        "configurable": channel.accepts_runtime_config,
                        "values": channel.decoded_config(),
                        "raw": channel.config.hex() or None,
                        "settings": [
                            setting.role
                            for setting in config_map.channel_settings(channel)
                        ],
                    }
                    for channel in snapshot.channels
                    if channel.config_spec is not None
                },
                "device_config": {
                    "available_fields": snapshot.device_config_available,
                    "fields": snapshot.device_config_fields,
                    "values": snapshot.decoded_device_config(),
                    "raw": snapshot.device_config.hex() or None,
                    "settings": [
                        setting.role for setting in config_map.device_settings(snapshot)
                    ],
                },
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
