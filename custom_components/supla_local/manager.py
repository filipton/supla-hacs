"""Owns the embedded SUPLA server and turns its callbacks into HA updates."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .channel_map import device_unique_ids
from .const import (
    ACTION_TRIGGER_CAPS,
    CERT_DIRNAME,
    CONF_ENABLE_TLS,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DEFAULT_ENABLE_TLS,
    DEFAULT_TCP_PORT,
    DEFAULT_TLS_PORT,
    DOMAIN,
    EVENT_ACTION_TRIGGER,
    MANUFACTURER,
    SIGNAL_ACTION_TRIGGER,
    SIGNAL_DEVICE_UPDATE,
)
from .models import DeviceSnapshot
from .server import protocol
from .server.registry import ConnectedDevice, DeviceRegistry
from .server.tcp_server import SuplaTcpServer
from .server.tls import load_or_create_ssl_context
from .store import SuplaStore

if TYPE_CHECKING:
    from . import SuplaConfigEntry

_LOGGER = logging.getLogger(__name__)

#: Devices are told to connect to the Home Assistant host, so bind everywhere.
LISTEN_HOST = "0.0.0.0"

DeviceListener = Callable[[DeviceSnapshot], None]


class SuplaManager:
    """One embedded SUPLA server, its device tree, and the HA glue around it."""

    def __init__(self, hass: HomeAssistant, entry: SuplaConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.registry = DeviceRegistry()
        #: Every device ever seen, restored from storage at startup.
        self.devices: dict[str, DeviceSnapshot] = {}
        self.last_seen: dict[str, datetime] = {}
        self.running = False

        self._store = SuplaStore(hass)
        self._tcp: SuplaTcpServer | None = None
        self._listeners: list[DeviceListener] = []
        #: unique id -> platform that owns it, so a channel can never be added
        #: twice and can move between platforms when its function changes.
        self._owners: dict[str, str] = {}

    # --- configuration ---

    @property
    def _options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def tcp_port(self) -> int:
        return int(self._options.get(CONF_TCP_PORT, DEFAULT_TCP_PORT))

    @property
    def tls_enabled(self) -> bool:
        return bool(self._options.get(CONF_ENABLE_TLS, DEFAULT_ENABLE_TLS))

    @property
    def tls_port(self) -> int | None:
        if not self.tls_enabled:
            return None
        return int(self._options.get(CONF_TLS_PORT, DEFAULT_TLS_PORT))

    @property
    def bound_ports(self) -> list[int]:
        """Ports actually being listened on, which differ if 0 was requested."""
        if self._tcp is None:
            return []
        return [
            socket.getsockname()[1]
            for server in self._tcp.servers
            for socket in (server.sockets or ())
        ]

    # --- lifecycle ---

    async def async_setup(self) -> None:
        """Restore state and start listening. Raises OSError if a port is taken."""
        self.devices = await self._store.async_load()
        _LOGGER.debug("Restored %d device(s) from storage", len(self.devices))
        for snapshot in self.devices.values():
            self._async_register_device(snapshot)

        await self._async_apply_timezone()

        ssl_context = None
        if self.tls_enabled:
            cert_dir = Path(self.hass.config.path(CERT_DIRNAME))
            # RSA key generation plus file I/O: never on the event loop.
            ssl_context = await self.hass.async_add_executor_job(
                partial(load_or_create_ssl_context, cert_dir=cert_dir)
            )

        self.registry.add_listener(self._async_on_device_update)
        self.registry.add_action_listener(self._async_on_action_trigger)
        self._tcp = SuplaTcpServer(
            self.registry,
            host=LISTEN_HOST,
            port=self.tcp_port,
            tls_port=self.tls_port,
            ssl_context=ssl_context,
        )
        await self._tcp.start()
        self.running = True

    async def async_stop(self) -> None:
        """Release both ports before the entry can be set up again."""
        self.running = False
        if self._tcp is not None:
            await self._tcp.stop()
            self._tcp = None

    # --- device discovery ---

    @callback
    def async_add_device_listener(self, listener: DeviceListener) -> CALLBACK_TYPE:
        """Subscribe to "this device's entity set may have grown"."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def async_forget_device(self, guid: str) -> None:
        """Drop a device the user deleted from the HA device page."""
        self.devices.pop(guid, None)
        self.last_seen.pop(guid, None)
        self._store.async_remove_device(guid)
        prefix = f"{guid}-"
        for unique_id in [key for key in self._owners if key.startswith(prefix)]:
            del self._owners[unique_id]

    @callback
    def async_claim(self, unique_id: str, platform: str) -> bool:
        """Ask whether `platform` should create the entity for `unique_id` now.

        False means it already exists. If another platform owned it — a channel
        whose function changed from, say, light switch to power switch — the
        stale entity is removed first so the channel does not appear twice.
        """
        owner = self._owners.get(unique_id)
        if owner == platform:
            return False
        if owner is not None:
            self._async_evict(unique_id, owner)
        self._owners[unique_id] = platform
        return True

    @callback
    def async_release(self, unique_id: str) -> None:
        self._owners.pop(unique_id, None)

    @callback
    def _async_evict(self, unique_id: str, platform: str) -> None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id is None:
            return
        _LOGGER.info("Removing %s: channel moved to another platform", entity_id)
        registry.async_remove(entity_id)

    @callback
    def _async_on_device_update(self, device: ConnectedDevice) -> None:
        """Registry listener: fires per device on register, value change, disconnect."""
        guid = device.guid_hex
        if device.online:
            self.last_seen[guid] = dt_util.utcnow()

        snapshot = DeviceSnapshot.from_device(device)
        previous = self.devices.get(guid)
        if previous is not None:
            snapshot = previous.merge(snapshot)

        if previous != snapshot:
            self.devices[guid] = snapshot
            self._store.async_update(snapshot)
            self._async_register_device(snapshot)
            if previous is not None:
                self._async_prune_entities(snapshot)
            for listener in list(self._listeners):
                listener(snapshot)

        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE.format(guid))

    @callback
    def _async_on_action_trigger(
        self, device: ConnectedDevice, channel_number: int, actions: int
    ) -> None:
        """A button was pressed.

        Presses are events, not state: two identical ones leave the channel
        value unchanged, so they arrive on their own signal rather than being
        diffed out of the regular device update.
        """
        guid = device.guid_hex
        names = [name for bit, name in ACTION_TRIGGER_CAPS if actions & bit]
        payload = {
            "guid": guid,
            "channel": channel_number,
            "actions": names,
            "mask": actions,
        }
        self.hass.bus.async_fire(EVENT_ACTION_TRIGGER, payload)
        async_dispatcher_send(
            self.hass, SIGNAL_ACTION_TRIGGER.format(guid, channel_number), names
        )

    # --- Home Assistant registries ---

    @callback
    def _async_register_device(self, snapshot: DeviceSnapshot) -> None:
        """Create the HA device (and any sub-devices) up front.

        Entities would create it implicitly, but doing it here means a device
        whose channels are all unsupported still shows up, and sub-devices get
        their parent link even before their first entity exists.
        """
        registry = dr.async_get(self.hass)
        registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, snapshot.guid)},
            manufacturer=MANUFACTURER,
            name=snapshot.name or f"SUPLA {snapshot.guid[-6:]}",
            model=_model(snapshot.manufacturer_id, snapshot.product_id),
            sw_version=snapshot.soft_ver or None,
            serial_number=snapshot.guid,
        )

        details = {sub.sub_device_id: sub for sub in snapshot.sub_devices}
        sub_ids = {
            channel.sub_device_id for channel in snapshot.channels if channel.sub_device_id
        }
        for sub_id in sorted(sub_ids | set(details)):
            sub = details.get(sub_id)
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, f"{snapshot.guid}:{sub_id}")},
                via_device=(DOMAIN, snapshot.guid),
                manufacturer=MANUFACTURER,
                name=(sub.name if sub and sub.name else f"Module {sub_id}"),
                model=(sub.product_code or None) if sub else None,
                sw_version=(sub.soft_ver or None) if sub else None,
                serial_number=(sub.serial_number or None) if sub else None,
            )

    @callback
    def _async_prune_entities(self, snapshot: DeviceSnapshot) -> None:
        """Drop entities for channels the device no longer reports.

        A firmware update or a function change in the device's web UI can
        replace the channel set outright; without this the old entities linger
        forever as "unavailable".
        """
        expected = device_unique_ids(snapshot)
        registry = er.async_get(self.hass)
        prefix = f"{snapshot.guid}-"
        for entry in er.async_entries_for_config_entry(registry, self.entry.entry_id):
            if not entry.unique_id.startswith(prefix) or entry.unique_id in expected:
                continue
            _LOGGER.info(
                "Removing %s: channel no longer reported by device %s",
                entry.entity_id,
                snapshot.guid,
            )
            registry.async_remove(entry.entity_id)
            self._owners.pop(entry.unique_id, None)

    async def _async_apply_timezone(self) -> None:
        """Answer GET_USER_LOCALTIME in the user's zone, not UTC.

        Devices run staircase timers and weekly schedules off this, so UTC
        would silently shift every schedule.
        """
        name = self.hass.config.time_zone
        if not name:
            return
        zone = await self.hass.async_add_executor_job(dt_util.get_time_zone, name)
        if zone is None:
            _LOGGER.debug("Unknown time zone %s, devices will get UTC", name)
            return
        protocol.set_default_timezone(zone)


def _model(manufacturer_id: int, product_id: int) -> str | None:
    if not manufacturer_id and not product_id:
        return None
    return f"{manufacturer_id}/{product_id}"
