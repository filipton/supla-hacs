"""Switch platform: plain relays and digiglass panels."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry, config_map
from .channel_map import SWITCH, EntityKey
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
from .server import channels as K


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, SWITCH, async_add_entities, _build)
    async_setup_device_config_platform(entry, SWITCH, async_add_entities)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.role.startswith(f"{config_map.ROLE_PREFIX}-"):
        return build_channel_config_entity(manager, device, channel, key)
    if key.kind == K.KIND_DIGIGLASS:
        return SuplaDigiglassSwitch(manager, device, channel, key)
    return SuplaRelaySwitch(manager, device, channel, key)


class SuplaRelaySwitch(SuplaChannelEntity, SwitchEntity):
    """A relay whose function is a plain on/off load."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        return self._value.get("on")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send({"action": "on"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send({"action": "off"})

    async def async_toggle(self, **kwargs: Any) -> None:
        # One packet instead of read-then-write, so a wall switch pressed at the
        # same moment cannot make us invert a stale state.
        await self._async_send({"action": "toggle"})


class SuplaDigiglassSwitch(SuplaChannelEntity, SwitchEntity):
    """Switchable glass; every section is driven together."""

    @property
    def is_on(self) -> bool | None:
        value = self._value
        if "mask" not in value:
            return None
        return bool(value["mask"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        value = self._value
        return {
            "section_mask": value.get("mask"),
            "section_count": value.get("section_count"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send({"action": "on"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send({"action": "off"})
