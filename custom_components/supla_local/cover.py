"""Cover platform: roller shutters, facade blinds and pulse-driven gates.

SUPLA and Home Assistant count cover position in opposite directions:
SUPLA 0 is fully open and 100 fully closed, Home Assistant's
`current_cover_position` is 0 closed and 100 open. Every position and tilt
crossing this file is inverted, in both directions. SUPLA reports -1 while the
drive is calibrating, which maps to "unknown" rather than to a position.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import (
    COVER,
    EntityKey,
    cover_device_class,
    find_opening_sensor,
)
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K

CALIBRATING = -1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, COVER, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.kind == K.KIND_FACADE_BLIND:
        return SuplaFacadeBlindCover(manager, device, channel, key)
    if key.kind == K.KIND_ROLLER_SHUTTER:
        return SuplaShutterCover(manager, device, channel, key)
    return SuplaImpulseCover(manager, device, channel, key)


def _to_ha_position(supla_position: Any) -> int | None:
    if supla_position is None or supla_position < 0 or supla_position > 100:
        return None
    return 100 - int(supla_position)


class SuplaCoverBase(SuplaChannelEntity, CoverEntity):
    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device, channel, key)
        if (device_class := cover_device_class(channel.function)) is not None:
            self._attr_device_class = CoverDeviceClass(device_class)


class SuplaShutterCover(SuplaCoverBase):
    """A motor that reports and accepts an absolute position."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    @property
    def current_cover_position(self) -> int | None:
        return _to_ha_position(self._value.get("position"))

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        value = self._value
        return {
            "calibrating": value.get("position") == CALIBRATING,
            "flags": value.get("flags"),
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._async_send({"action": "open"})

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._async_send({"action": "close"})

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._async_send({"action": "stop"})

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self._async_send(
            {"action": "position", "position": 100 - int(kwargs[ATTR_POSITION])}
        )


class SuplaFacadeBlindCover(SuplaShutterCover):
    """A blind that also reports slat tilt."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.STOP_TILT
        | CoverEntityFeature.SET_TILT_POSITION
    )

    @property
    def current_cover_tilt_position(self) -> int | None:
        return _to_ha_position(self._value.get("tilt"))

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send({"action": "tilt", "tilt": 0})

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send({"action": "tilt", "tilt": 100})

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send({"action": "stop"})

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        await self._async_send(
            {"action": "tilt", "tilt": 100 - int(kwargs[ATTR_TILT_POSITION])}
        )


class SuplaImpulseCover(SuplaCoverBase):
    """A gate or garage door on a relay.

    The relay is a doorbell button, not a state: the same pulse opens and
    closes. Real state comes from the paired opening sensor if the device has
    one, and the pulse is suppressed when the door is already where it should
    be — otherwise "open" on an open gate would close it.
    """

    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

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
    def is_closed(self) -> bool | None:
        if self._sensor_channel is None:
            return None
        opened = self._sibling_value(self._sensor_channel).get("on")
        return None if opened is None else not opened

    async def async_open_cover(self, **kwargs: Any) -> None:
        if self.is_closed is False:
            return
        await self._async_send({"action": "on"})

    async def async_close_cover(self, **kwargs: Any) -> None:
        if self.is_closed is True:
            return
        await self._async_send({"action": "on"})
