"""Editable device and channel settings, as Home Assistant entities.

One base class covers both scopes: a setting either lives in a channel's
config struct or in the device-level blob, and the only differences are where
its value is read from and which registry call writes it back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import config_map
from .channel_map import EntityKey, unique_id
from .entity import SuplaEntity, channel_device_info
from .models import ChannelSnapshot, DeviceSnapshot
from .server.config import ConfigError, ConfigField, ConfigSpec
from .server.registry import ConfigRejected

if TYPE_CHECKING:
    from .manager import SuplaManager

_LOGGER = logging.getLogger(__name__)


class SuplaConfigEntity(SuplaEntity):
    """A single configuration field of a device or one of its channels."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        setting: config_map.Setting,
        *,
        channel: ChannelSnapshot | None = None,
        key: EntityKey | None = None,
    ) -> None:
        super().__init__(manager, device)
        self._setting = setting
        self._channel_number = channel.number if channel is not None else None
        self._attr_icon = setting.icon

        spec: ConfigSpec | None
        if channel is not None and key is not None:
            spec = channel.config_spec
            self._attr_unique_id = unique_id(device.guid, key.suffix)
            self._attr_name = f"{setting.label} {channel.number}"
            self._attr_device_info = channel_device_info(device, channel)
        else:
            spec = config_map.spec_for(setting)
            self._attr_unique_id = unique_id(device.guid, setting.role)
            self._attr_name = setting.label
            self._attr_device_info = channel_device_info(device, None)

        if spec is None or (field := spec.field(setting.key)) is None:
            raise ConfigError(f"no configuration field for {setting.key!r}")
        self._field: ConfigField = field

    @property
    def _values(self) -> dict[str, int]:
        """The struct this setting lives in, decoded, or {} when unknown."""
        device = self._device
        if device is None:
            return {}
        if self._channel_number is None:
            return device.decoded_device_config().get(self._setting.group, {})
        channel = device.channels.get(self._channel_number)
        return channel.decoded_config() if channel is not None else {}

    @property
    def _raw(self) -> int | None:
        return self._values.get(self._setting.key)

    @property
    def available(self) -> bool:
        # Configuration is written over the device's own connection, so it can
        # only be read or changed while the device is there.
        if not self._manager.running:
            return False
        device = self._device
        if device is None or not device.online:
            return False
        if self._channel_number is None:
            return True
        channel = device.channels.get(self._channel_number)
        return channel is not None and not channel.offline

    async def _async_write(self, raw: int) -> None:
        """Send one field to the device and wait for it to accept."""
        registry = self._manager.registry
        try:
            if self._channel_number is None:
                await registry.write_device_config(
                    self._guid, self._setting.group, self._setting.key, raw
                )
            else:
                await registry.write_channel_config(
                    self._guid, self._channel_number, self._setting.key, raw
                )
        except ConfigRejected as err:
            raise HomeAssistantError(f"{self.name}: the device refused it ({err})") from err
        except ConfigError as err:
            raise ServiceValidationError(str(err)) from err
        except asyncio.TimeoutError as err:
            raise HomeAssistantError(
                f"{self.name}: the device did not answer in time"
            ) from err
        except (RuntimeError, OSError) as err:
            raise HomeAssistantError(f"{self.name}: {err}") from err
        self.async_write_ha_state()


class SuplaConfigNumber(SuplaConfigEntity, NumberEntity):
    """A numeric setting, shown in whatever unit the field is presented in."""

    _attr_mode = NumberMode.BOX

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._attr_native_unit_of_measurement = self._setting.unit
        self._attr_native_step = self._setting.step

    def _bound(self, which: str) -> float:
        """Prefer the device's own limit, then ours, then what the field holds."""
        reported = getattr(self._field, f"{which}_from", None)
        if reported and (raw := self._values.get(reported)):
            return raw / self._field.scale
        for candidate in (getattr(self._setting, which), getattr(self._field, which)):
            if candidate is not None:
                return candidate
        low, high = self._field.bounds()
        return low if which == "minimum" else high

    @property
    def native_min_value(self) -> float:
        return self._bound("minimum")

    @property
    def native_max_value(self) -> float:
        return self._bound("maximum")

    @property
    def native_value(self) -> float | None:
        raw = self._raw
        return None if raw is None else raw / self._field.scale

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(int(round(value * self._field.scale)))


class SuplaConfigSwitch(SuplaConfigEntity, SwitchEntity):
    """A boolean setting.

    Several SUPLA fields are tri-state: 0 means the device has no opinion yet,
    1 means false and 2 means true. Those report unknown until they are set.
    """

    @property
    def is_on(self) -> bool | None:
        raw = self._raw
        if raw is None:
            return None
        if self._setting.tri_state:
            return None if raw == 0 else raw == 2
        return bool(raw) != self._setting.inverted

    def _raw_for(self, on: bool) -> int:
        if self._setting.tri_state:
            return 2 if on else 1
        if self._setting.inverted:
            return 0 if on else 1
        return 1 if on else 0

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(self._raw_for(True))

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(self._raw_for(False))


class SuplaConfigSelect(SuplaConfigEntity, SelectEntity):
    """A setting with a fixed set of choices."""

    @property
    def _choices(self) -> list[tuple[int, str]]:
        return config_map.options_for(self._setting, self._values)

    @property
    def options(self) -> list[str]:
        return [label for _raw, label in self._choices]

    @property
    def current_option(self) -> str | None:
        raw = self._raw
        if raw is None:
            return None
        return next((label for value, label in self._choices if value == raw), None)

    async def async_select_option(self, option: str) -> None:
        raw = next((value for value, label in self._choices if label == option), None)
        if raw is None:
            raise ServiceValidationError(
                f"{self.name}: this device does not offer {option!r}"
            )
        await self._async_write(raw)


PLATFORM_CLASSES: dict[str, type[SuplaConfigEntity]] = {
    config_map.NUMBER: SuplaConfigNumber,
    config_map.SWITCH: SuplaConfigSwitch,
    config_map.SELECT: SuplaConfigSelect,
}


def build_channel_config_entity(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaConfigEntity | None:
    """The configuration entity a channel's entity key stands for, if any."""
    for setting in config_map.channel_settings(channel):
        if setting.role != key.role:
            continue
        factory = PLATFORM_CLASSES.get(setting.platform)
        if factory is None:
            return None
        return factory(manager, device, setting, channel=channel, key=key)
    return None


def build_device_config_entities(
    manager: SuplaManager, device: DeviceSnapshot, platform: str
) -> list[SuplaConfigEntity]:
    """Every device-level configuration entity belonging to one platform."""
    entities: list[SuplaConfigEntity] = []
    for setting in config_map.device_settings(device):
        if setting.platform != platform:
            continue
        factory = PLATFORM_CLASSES.get(setting.platform)
        if factory is None:
            continue
        try:
            entities.append(factory(manager, device, setting))
        except ConfigError:
            _LOGGER.debug("skipping unbuildable setting %s", setting.role)
    return entities


def async_setup_device_config_platform(
    entry, platform: str, async_add_entities
) -> None:
    """Add device-level configuration entities, now and as devices appear."""
    manager = entry.runtime_data

    def _async_add(device: DeviceSnapshot) -> None:
        new = [
            entity
            for entity in build_device_config_entities(manager, device, platform)
            if manager.async_claim(entity.unique_id, platform)
        ]
        if new:
            async_add_entities(new)

    for device in list(manager.devices.values()):
        _async_add(device)
    entry.async_on_unload(manager.async_add_device_listener(_async_add))
