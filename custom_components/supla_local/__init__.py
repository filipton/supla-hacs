"""The SUPLA Local integration.

Runs a full SUPLA server inside Home Assistant. Devices connect straight to the
HA host on port 2015/2016, so state arrives as a push over the device's own TCP
link — there is no cloud, no broker and nothing to poll.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

from . import channel_map
from .const import DOMAIN
from .manager import SuplaManager
from .store import SuplaStore

_LOGGER = logging.getLogger(__name__)

#: The entry owns the server; the manager hangs off it as runtime data.
SuplaConfigEntry = ConfigEntry[SuplaManager]

#: Derived from the channel map, so a new platform only has to be declared once.
PLATFORMS: list[Platform] = [Platform(name) for name in channel_map.PLATFORMS]


async def async_setup_entry(hass: HomeAssistant, entry: SuplaConfigEntry) -> bool:
    """Start the embedded SUPLA server and bring its platforms up."""
    manager = SuplaManager(hass, entry)
    try:
        await manager.async_setup()
    except OSError as err:
        # Almost always "address already in use": the standalone server, or a
        # previous entry that has not released the port yet.
        await manager.async_stop()
        raise ConfigEntryNotReady(
            f"Cannot listen for SUPLA devices on port {manager.tcp_port}: {err}"
        ) from err

    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SuplaConfigEntry) -> bool:
    """Stop listening. The ports must be free before the entry is set up again."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SuplaConfigEntry) -> None:
    """Forget every remembered device when the integration is deleted."""
    await SuplaStore(hass).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SuplaConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Let the user delete a device from its Home Assistant page.

    Deleting a device that is still connected disconnects it and forgets its
    settings, but registration is open, so it registers again within seconds
    and comes back. Unplug it, or point it somewhere else, to make it stay
    gone.
    """
    manager = entry.runtime_data
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        guid, _, sub_device = identifier.partition(":")
        if sub_device:
            # A sub-device is a view of its parent; the parent owns the state.
            continue
        await manager.async_forget(guid)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: SuplaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
