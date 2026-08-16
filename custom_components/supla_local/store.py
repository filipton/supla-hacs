"""Persistence of the device tree.

Home Assistant's device and entity registries already remember names, areas and
entity ids. The only thing they cannot tell us is *which* entities to create
before any device has reconnected, so that is all we store: the shape of every
device we have ever seen. Deliberately no values — a restored entity is
unavailable until its device reports, rather than showing a stale reading.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_SAVE_DELAY, STORAGE_VERSION
from .models import DeviceSnapshot

_LOGGER = logging.getLogger(__name__)


class SuplaStore:
    """Reads and writes `.storage/supla_local`."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self._devices: dict[str, DeviceSnapshot] = {}

    async def async_load(self) -> dict[str, DeviceSnapshot]:
        data = await self._store.async_load()
        devices: dict[str, DeviceSnapshot] = {}
        for guid, raw in (data or {}).get("devices", {}).items():
            try:
                devices[guid] = DeviceSnapshot.from_json(raw)
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Dropping unreadable stored device %s", guid)
        self._devices = devices
        return dict(devices)

    @callback
    def async_update(self, snapshot: DeviceSnapshot) -> None:
        if self._devices.get(snapshot.guid) == snapshot:
            return
        self._devices[snapshot.guid] = snapshot
        self._async_schedule_save()

    @callback
    def async_remove_device(self, guid: str) -> None:
        if self._devices.pop(guid, None) is not None:
            self._async_schedule_save()

    async def async_remove(self) -> None:
        """Forget everything; called when the config entry is deleted."""
        self._devices.clear()
        await self._store.async_remove()

    @callback
    def _async_schedule_save(self) -> None:
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)

    @callback
    def _data(self) -> dict[str, Any]:
        return {
            "devices": {
                guid: snapshot.to_json() for guid, snapshot in self._devices.items()
            }
        }
