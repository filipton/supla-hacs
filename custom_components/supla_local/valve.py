"""Valve platform: open/close and percentage valves."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import VALVE, EntityKey
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K

# TValve_Value.flags
FLAG_FLOODING = 1 << 0
FLAG_MANUALLY_CLOSED = 1 << 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, VALVE, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.kind == K.KIND_VALVE_PERCENTAGE:
        return SuplaPositionValve(manager, device, channel, key)
    return SuplaValve(manager, device, channel, key)


class SuplaValveBase(SuplaChannelEntity, ValveEntity):
    # SUPLA does not say what flows through the valve; water is the common case
    # and users can override the class per entity.
    _attr_device_class = ValveDeviceClass.WATER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        flags = self._value.get("flags")
        if flags is None:
            return {}
        return {
            "flooding": bool(flags & FLAG_FLOODING),
            "manually_closed": bool(flags & FLAG_MANUALLY_CLOSED),
        }


class SuplaValve(SuplaValveBase):
    """A valve that is either open or closed."""

    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    @property
    def is_closed(self) -> bool | None:
        return self._value.get("closed")

    async def async_open_valve(self) -> None:
        await self._async_send({"action": "open"})

    async def async_close_valve(self) -> None:
        await self._async_send({"action": "close"})


class SuplaPositionValve(SuplaValveBase):
    """A valve with a settable opening; SUPLA counts the closed percentage."""

    _attr_reports_position = True
    _attr_supported_features = (
        ValveEntityFeature.OPEN
        | ValveEntityFeature.CLOSE
        | ValveEntityFeature.SET_POSITION
    )

    @property
    def current_valve_position(self) -> int | None:
        closed = self._value.get("closed_percent")
        if closed is None:
            return None
        return 100 - int(closed)

    async def async_open_valve(self) -> None:
        await self._async_send({"action": "open"})

    async def async_close_valve(self) -> None:
        await self._async_send({"action": "close"})

    async def async_set_valve_position(self, position: int) -> None:
        await self._async_send({"action": "position", "position": 100 - int(position)})
