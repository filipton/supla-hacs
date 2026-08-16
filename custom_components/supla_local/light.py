"""Light platform: light-switch relays, dimmers and RGB controllers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import LIGHT, ROLE_WHITE, EntityKey
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
    async_setup_channel_platform(entry, LIGHT, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.kind == K.KIND_RELAY:
        return SuplaRelayLight(manager, device, channel, key)
    if key.kind == K.KIND_DIMMER or key.role == ROLE_WHITE:
        return SuplaDimmerLight(manager, device, channel, key)
    return SuplaRgbLight(manager, device, channel, key)


def _to_ha(percent: Any) -> int | None:
    """SUPLA 0-100 -> Home Assistant 0-255."""
    if percent is None:
        return None
    return round(int(percent) * 255 / 100)


def _to_supla(brightness: int) -> int:
    """Home Assistant 0-255 -> SUPLA 0-100, never rounding "on" down to off."""
    percent = round(brightness * 100 / 255)
    return max(1, percent) if brightness > 0 else 0


class SuplaRelayLight(SuplaChannelEntity, LightEntity):
    """A relay whose assigned function is a light switch."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        return self._value.get("on")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send({"action": "on"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send({"action": "off"})


class SuplaDimmerLight(SuplaChannelEntity, LightEntity):
    """A single-channel dimmer: a standalone one, or the white half of an RGBW."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def brightness(self) -> int | None:
        return _to_ha(self._value.get("brightness"))

    @property
    def is_on(self) -> bool | None:
        brightness = self._value.get("brightness")
        return None if brightness is None else brightness > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            percent = _to_supla(brightness)
        else:
            percent = int(self._value.get("brightness") or 0) or 100
        # Always the explicit brightness command: on an RGBW channel a plain
        # "on" would light the colour half as well.
        await self._async_send({"action": "brightness", "brightness": percent})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send({"action": "brightness", "brightness": 0})


class SuplaRgbLight(SuplaChannelEntity, LightEntity):
    """The colour half of an RGB or RGBW controller."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    @property
    def brightness(self) -> int | None:
        return _to_ha(self._value.get("color_brightness"))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        value = self._value
        if "red" not in value:
            return None
        return int(value["red"]), int(value["green"]), int(value["blue"])

    @property
    def is_on(self) -> bool | None:
        # Not value["on"]: on an RGBW channel that is also true when only the
        # white dimmer is lit, which belongs to the other entity.
        color_brightness = self._value.get("color_brightness")
        return None if color_brightness is None else color_brightness > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb = kwargs.get(ATTR_RGB_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if brightness is not None:
            percent = _to_supla(brightness)
        else:
            percent = int(self._value.get("color_brightness") or 0) or 100

        if rgb is not None:
            await self._async_send(
                {
                    "action": "color",
                    "color": "#{:02x}{:02x}{:02x}".format(*rgb),
                    "color_brightness": percent,
                }
            )
            return
        await self._async_send({"action": "color_brightness", "color_brightness": percent})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send({"action": "color_brightness", "color_brightness": 0})
