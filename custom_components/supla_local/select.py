"""Select platform: SUPLA settings that pick one of a fixed set of choices."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import SELECT, EntityKey
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
    async_setup_channel_platform(entry, SELECT, async_add_entities, _build)
    async_setup_device_config_platform(entry, SELECT, async_add_entities)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    # Every select this integration creates is a configuration field.
    return build_channel_config_entity(manager, device, channel, key)
