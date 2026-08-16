"""Entity base classes and the lazy "add as devices appear" platform helper."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .channel_map import EntityKey, device_entity_keys, label, unique_id
from .const import DOMAIN, SIGNAL_DEVICE_UPDATE
from .models import ChannelSnapshot, DeviceSnapshot
from .server.channels import UnsupportedCommand
from .server.registry import ChannelState, ConnectedDevice

if TYPE_CHECKING:
    from . import SuplaConfigEntry
    from .manager import SuplaManager

_LOGGER = logging.getLogger(__name__)

try:  # Home Assistant 2024.8+
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # pragma: no cover - older cores
    from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

ChannelEntityBuilder = Callable[
    ["SuplaManager", DeviceSnapshot, ChannelSnapshot, EntityKey], Entity | None
]
DeviceEntityBuilder = Callable[["SuplaManager", DeviceSnapshot], Entity]


class SuplaEntity(Entity):
    """Anything attached to a SUPLA device: pushed to, never polled."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager: SuplaManager, device: DeviceSnapshot) -> None:
        self._manager = manager
        self._guid = device.guid

    @property
    def _device(self) -> ConnectedDevice | None:
        """The live device, or None while it is disconnected.

        Looked up every time on purpose: the registry replaces the object on
        every re-registration, so a cached reference goes stale.
        """
        return self._manager.registry.get(self._guid)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATE.format(self._guid),
                self._async_handle_update,
            )
        )

    @callback
    def _async_handle_update(self) -> None:
        self.async_write_ha_state()


class SuplaChannelEntity(SuplaEntity):
    """One entity backed by one channel of a SUPLA device."""

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device)
        self._channel_number = channel.number
        self._kind = key.kind
        self._key = key
        self._attr_unique_id = unique_id(device.guid, key.suffix)
        self._attr_name = label(channel, key)
        self._attr_device_info = channel_device_info(device, channel)

    # --- state ---

    @property
    def _channel(self) -> ChannelState | None:
        device = self._device
        if device is None:
            return None
        return device.channels.get(self._channel_number)

    @property
    def _value(self) -> dict[str, Any]:
        """Decoded channel value, or {} when the device is not connected."""
        channel = self._channel
        return channel.decoded() if channel is not None else {}

    def _sibling_value(self, number: int | None) -> dict[str, Any]:
        """Decoded value of another channel on the same device."""
        device = self._device
        if device is None or number is None:
            return {}
        channel = device.channels.get(number)
        return channel.decoded() if channel is not None else {}

    @property
    def available(self) -> bool:
        if not self._manager.running:
            return False
        device = self._device
        if device is None or not device.online:
            return False
        channel = self._channel
        if channel is None or channel.offline:
            return False
        # A re-registered device can hand the same channel number a different
        # function; the entity for the old kind stops making sense.
        return channel.kind == self._kind

    # --- control ---

    async def _async_send(self, command: dict[str, Any]) -> None:
        """Send one command, mapping server errors onto HA's error types."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                f"SUPLA device {self._guid} is not connected"
            )
        try:
            await device.execute(self._channel_number, command)
        except UnsupportedCommand as err:
            raise ServiceValidationError(str(err)) from err
        except KeyError as err:
            raise HomeAssistantError(
                f"Channel {self._channel_number} is gone from device {self._guid}"
            ) from err
        except (RuntimeError, OSError) as err:
            raise HomeAssistantError(
                f"Could not reach SUPLA device {self._guid}: {err}"
            ) from err
        # Echoable kinds already reflect the new value; for the rest this just
        # re-renders and the device's own report follows.
        self.async_write_ha_state()


def channel_device_info(
    device: DeviceSnapshot, channel: ChannelSnapshot | None
) -> DeviceInfo:
    """Point at the parent device, or at the sub-device the channel lives on.

    Metadata is filled in by the manager when it creates the registry entries;
    entities only need to say which device they belong to.
    """
    if channel is not None and channel.sub_device_id:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{device.guid}:{channel.sub_device_id}")}
        )
    return DeviceInfo(identifiers={(DOMAIN, device.guid)})


@callback
def async_setup_channel_platform(
    entry: SuplaConfigEntry,
    platform: str,
    async_add_entities: AddConfigEntryEntitiesCallback,
    builder: ChannelEntityBuilder,
) -> None:
    """Add this platform's entities for known devices, and for future ones.

    Devices are not known when the config entry is set up: they show up when
    they dial in, and may change their channel set at any re-registration.
    """
    manager = entry.runtime_data

    @callback
    def _async_add(device: DeviceSnapshot) -> None:
        channels = {channel.number: channel for channel in device.channels}
        new: list[Entity] = []
        for key in device_entity_keys(device):
            if key.platform != platform:
                continue
            entity_unique_id = unique_id(device.guid, key.suffix)
            if not manager.async_claim(entity_unique_id, platform):
                continue
            channel = channels[key.channel]
            try:
                entity = builder(manager, device, channel, key)
            except Exception:  # noqa: BLE001 - one bad channel must not kill setup
                _LOGGER.exception(
                    "Could not build %s entity for %s channel %s",
                    platform,
                    device.guid,
                    key.channel,
                )
                entity = None
            if entity is None:
                manager.async_release(entity_unique_id)
                continue
            new.append(entity)
        if new:
            async_add_entities(new)

    for device in list(manager.devices.values()):
        _async_add(device)
    entry.async_on_unload(manager.async_add_device_listener(_async_add))


@callback
def async_setup_device_platform(
    entry: SuplaConfigEntry,
    platform: str,
    async_add_entities: AddConfigEntryEntitiesCallback,
    suffix: str,
    builder: DeviceEntityBuilder,
) -> None:
    """Same, for entities that describe the device rather than a channel."""
    manager = entry.runtime_data

    @callback
    def _async_add(device: DeviceSnapshot) -> None:
        entity_unique_id = unique_id(device.guid, suffix)
        if not manager.async_claim(entity_unique_id, platform):
            return
        async_add_entities([builder(manager, device)])

    for device in list(manager.devices.values()):
        _async_add(device)
    entry.async_on_unload(manager.async_add_device_listener(_async_add))
