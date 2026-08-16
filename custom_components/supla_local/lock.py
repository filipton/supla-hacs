"""Lock platform: door and gateway strikes on a relay."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import LOCK, EntityKey, find_opening_sensor
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, LOCK, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    return SuplaLock(manager, device, channel, key)


class SuplaLock(SuplaChannelEntity, LockEntity):
    """An electric strike driven by a relay.

    Energising the relay releases the strike, so "unlocked" is the relay being
    on. Most strikes are momentary and fall back to locked on their own, which
    is why OPEN is supported: it is the buzz-the-door-open action.
    """

    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device, channel, key)
        self._sensor_channel = find_opening_sensor(device, channel)
        self._attr_assumed_state = self._sensor_channel is None

    @property
    def is_locked(self) -> bool | None:
        if self._sensor_channel is not None:
            opened = self._sibling_value(self._sensor_channel).get("on")
            if opened is not None:
                return not opened
        energised = self._value.get("on")
        return None if energised is None else not energised

    async def async_lock(self, **kwargs: Any) -> None:
        await self._async_send({"action": "off"})

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._async_send({"action": "on"})

    async def async_open(self, **kwargs: Any) -> None:
        await self._async_send({"action": "on"})
