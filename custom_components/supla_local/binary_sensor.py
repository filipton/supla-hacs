"""Binary sensor platform: SUPLA sensor channels plus a per-device connectivity entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import (
    BINARY_SENSOR,
    CONNECTIVITY_KEY,
    EntityKey,
    binary_sensor_device_class,
    unique_id,
)
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    SuplaEntity,
    async_setup_channel_platform,
    async_setup_device_platform,
    channel_device_info,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, BINARY_SENSOR, async_add_entities, _build)
    async_setup_device_platform(
        entry,
        BINARY_SENSOR,
        async_add_entities,
        CONNECTIVITY_KEY,
        SuplaConnectivitySensor,
    )


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    return SuplaBinarySensor(manager, device, channel, key)


class SuplaBinarySensor(SuplaChannelEntity, BinarySensorEntity):
    """An opening, flood, motion or generic sensor channel."""

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device, channel, key)
        if (device_class := binary_sensor_device_class(channel.function)) is not None:
            self._attr_device_class = BinarySensorDeviceClass(device_class)

    @property
    def is_on(self) -> bool | None:
        return self._value.get("on")


class SuplaConnectivitySensor(SuplaEntity, BinarySensorEntity):
    """Whether the device currently holds a connection to Home Assistant.

    Every other entity of the device goes unavailable when it drops off, so
    this is the one entity that stays readable and can drive an alert.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connection"

    def __init__(self, manager: SuplaManager, device: DeviceSnapshot) -> None:
        super().__init__(manager, device)
        self._attr_unique_id = unique_id(device.guid, CONNECTIVITY_KEY)
        self._attr_device_info = channel_device_info(device, None)

    @property
    def available(self) -> bool:
        return self._manager.running

    @property
    def is_on(self) -> bool:
        device = self._device
        return device is not None and device.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device
        return {
            "guid": self._guid,
            "last_seen": self._manager.last_seen.get(self._guid),
            "protocol_version": device.proto_version if device else None,
        }
