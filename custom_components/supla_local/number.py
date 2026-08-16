"""Number platform: engine speed channels."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry, config_map
from .channel_map import NUMBER, EntityKey
from .config_entity import (
    async_setup_device_config_platform,
    build_channel_config_entity,
)
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
    async_setup_channel_platform(entry, NUMBER, async_add_entities, _build)
    async_setup_device_config_platform(entry, NUMBER, async_add_entities)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.role.startswith(f"{config_map.ROLE_PREFIX}-"):
        return build_channel_config_entity(manager, device, channel, key)
    return SuplaEngineSpeedNumber(manager, device, channel, key)


class SuplaEngineSpeedNumber(SuplaChannelEntity, NumberEntity):
    """Speed of a motor driven by a SUPLA engine channel."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        return self._value.get("speed")

    async def async_set_native_value(self, value: float) -> None:
        await self._async_send({"action": "speed", "speed": int(value)})
