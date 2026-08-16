"""Connected device registry and channel state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from . import channels
from . import config as config_mod
from . import consts as C
from .protocol import DeviceChannel, RegisterDevice, guid_to_hex

if TYPE_CHECKING:
    from .session import DeviceSession

logger = logging.getLogger(__name__)


class ConfigRejected(RuntimeError):
    """The device refused a configuration write."""

    def __init__(self, result: int) -> None:
        self.result = result
        super().__init__(
            C.CONFIG_RESULT_NAMES.get(result, f"unknown result {result}")
        )

DeviceListener = Callable[["ConnectedDevice"], Awaitable[None] | None]
#: (device, channel_number, action bitmask) for a button press.
ActionListener = Callable[["ConnectedDevice", int, int], Awaitable[None] | None]

# Kinds whose set-value payload is laid out like the value the device reports back.
# For the others (roller shutters, HVAC, digiglass, ...) the command is an
# instruction, not a state, so we wait for the device to report the new value.
_ECHOABLE_KINDS = frozenset(
    {
        channels.KIND_RELAY,
        channels.KIND_DIMMER,
        channels.KIND_RGB,
        channels.KIND_DIMMER_RGB,
        channels.KIND_VALVE_OPEN_CLOSE,
        channels.KIND_VALVE_PERCENTAGE,
        channels.KIND_ENGINE_SPEED,
    }
)


@dataclass(slots=True)
class ChannelState:
    number: int
    type: int
    function: int
    func_list: int = 0
    flags: int = 0
    value: bytes = field(default_factory=lambda: bytes(8))
    offline: int = 0
    sub_device_id: int = 0
    extended: dict[str, Any] | None = None
    #: Raw SUPLA_CONFIG_TYPE_DEFAULT blob, exactly as last exchanged with the
    #: device. Writes edit a copy of these bytes rather than build new ones.
    config: bytes | None = None

    @property
    def config_spec(self) -> config_mod.ConfigSpec | None:
        return config_mod.channel_config_spec(self.function)

    @property
    def accepts_runtime_config(self) -> bool:
        return bool(self.flags & C.SUPLA_CHANNEL_FLAG_RUNTIME_CHANNEL_CONFIG_UPDATE)

    def decoded_config(self) -> dict[str, int]:
        spec = self.config_spec
        return spec.decode(self.config) if spec is not None else {}

    @property
    def kind(self) -> str:
        return channels.channel_kind(self.function, self.type)

    def decoded(self) -> dict[str, Any]:
        return channels.decode_value(self.kind, self.value)

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind
        return {
            "number": self.number,
            "type": self.type,
            "type_name": channels.type_name(self.type),
            "function": self.function,
            "function_name": channels.function_name(self.function),
            "kind": kind,
            "controllable": channels.is_controllable(kind),
            "actions": channels.actions_for(kind),
            "func_list": self.func_list,
            "flags": self.flags,
            "offline": self.offline,
            "sub_device_id": self.sub_device_id,
            "value": self.decoded(),
            "extended": self.extended,
            "config": self.decoded_config(),
            "config_raw": self.config.hex() if self.config else None,
        }


@dataclass
class ConnectedDevice:
    guid: bytes
    name: str
    soft_ver: str
    channels: dict[int, ChannelState]
    email: str | None = None
    location_id: int | None = None
    flags: int = 0
    manufacturer_id: int = 0
    product_id: int = 0
    proto_version: int = 0
    sub_devices: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: Raw device config blob and its bitmaps, as last reported by the device.
    device_config: bytes = b""
    device_config_fields: int = 0
    device_config_available: int = 0
    session: DeviceSession | None = field(default=None, repr=False)

    @property
    def supports_device_config(self) -> bool:
        return bool(self.flags & C.SUPLA_DEVICE_FLAG_DEVICE_CONFIG_SUPPORTED)

    def decoded_device_config(self) -> dict[str, dict[str, int]]:
        return config_mod.decode_device_config(
            self.device_config_fields, self.device_config
        )

    @property
    def guid_hex(self) -> str:
        return guid_to_hex(self.guid)

    @property
    def online(self) -> bool:
        return self.session is not None and self.session.is_connected

    def to_dict(self) -> dict[str, Any]:
        ordered = sorted(self.channels.values(), key=lambda c: c.number)
        return {
            "guid": self.guid_hex,
            "name": self.name,
            "soft_ver": self.soft_ver,
            "email": self.email,
            "location_id": self.location_id,
            "flags": self.flags,
            "manufacturer_id": self.manufacturer_id,
            "product_id": self.product_id,
            "proto_version": self.proto_version,
            "online": self.online,
            "device_config": self.decoded_device_config(),
            "device_config_fields": self.device_config_fields,
            "device_config_available": self.device_config_available,
            "sub_devices": list(self.sub_devices.values()),
            "channels": [channel.to_dict() for channel in ordered],
        }

    async def execute(self, channel_number: int, command: dict[str, Any]) -> ChannelState:
        """Translate a command dict into SUPLA_SD_CALL_CHANNEL_SET_VALUE."""
        if self.session is None or not self.session.is_connected:
            raise RuntimeError("device is offline")
        channel = self.channels.get(channel_number)
        if channel is None:
            raise KeyError(f"channel {channel_number} not found")

        normalized = channels.normalize_command(command)
        value = channels.encode_command(channel.kind, normalized, channel.decoded())
        await self.session.send_channel_value(channel_number, value)
        if channel.kind in _ECHOABLE_KINDS:
            # These commands use the same layout as the reported state, so we can
            # show it right away; the device confirms with a value-changed call.
            channel.value = value
        return channel


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, ConnectedDevice] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[DeviceListener] = []
        self._action_listeners: list[ActionListener] = []
        #: Partially received device config, keyed by GUID; a device may split
        #: its configuration over several messages.
        self._device_config_parts: dict[str, tuple[int, bytearray]] = {}

    def add_listener(self, listener: DeviceListener) -> None:
        self._listeners.append(listener)

    def add_action_listener(self, listener: ActionListener) -> None:
        """Subscribe to button presses, which are events rather than state."""
        self._action_listeners.append(listener)

    async def _notify(self, device: ConnectedDevice) -> None:
        for listener in self._listeners:
            result = listener(device)
            if asyncio.iscoroutine(result):
                await result

    async def register(
        self,
        reg: RegisterDevice,
        session: DeviceSession,
        proto_version: int,
    ) -> ConnectedDevice:
        guid_hex = guid_to_hex(reg.guid)
        new_channels = {
            ch.number: _channel_state(ch) for ch in reg.channels
        }

        old_session: DeviceSession | None = None
        async with self._lock:
            existing = self._devices.get(guid_hex)
            if existing and existing.session is not None and existing.session is not session:
                old_session = existing.session
            # Preserve extended values and configuration across re-registration:
            # the device sends neither again, but both still apply.
            if existing:
                for number, channel in new_channels.items():
                    previous = existing.channels.get(number)
                    if previous is not None:
                        channel.extended = previous.extended
                        if previous.function == channel.function:
                            channel.config = previous.config

            device = ConnectedDevice(
                guid=reg.guid,
                name=reg.name,
                soft_ver=reg.soft_ver,
                channels=new_channels,
                email=reg.email,
                location_id=reg.location_id,
                flags=reg.flags,
                manufacturer_id=reg.manufacturer_id,
                product_id=reg.product_id,
                proto_version=proto_version,
                sub_devices=dict(existing.sub_devices) if existing else {},
                device_config=existing.device_config if existing else b"",
                device_config_fields=existing.device_config_fields if existing else 0,
                device_config_available=(
                    existing.device_config_available if existing else 0
                ),
                session=session,
            )
            self._devices[guid_hex] = device

        if old_session is not None:
            logger.info("replacing session for device %s", guid_hex)
            await old_session.close()

        logger.info(
            "registered device %s (%s) with %d channel(s): %s",
            reg.name,
            guid_hex,
            len(new_channels),
            ", ".join(
                f"#{ch.number} {channels.function_name(ch.function)}"
                for ch in sorted(new_channels.values(), key=lambda c: c.number)
            ),
        )
        await self._notify(device)
        return device

    async def unregister_session(self, session: DeviceSession) -> None:
        device: ConnectedDevice | None = None
        async with self._lock:
            for candidate in self._devices.values():
                if candidate.session is session:
                    candidate.session = None
                    device = candidate
                    break
        if device is not None:
            logger.info("device %s went offline", device.guid_hex)
            await self._notify(device)

    async def update_channel_value(
        self,
        guid: bytes,
        channel_number: int,
        value: bytes,
        offline: int = 0,
    ) -> None:
        async with self._lock:
            device = self._devices.get(guid_to_hex(guid))
            if device is None:
                return
            channel = device.channels.get(channel_number)
            if channel is None:
                channel = ChannelState(number=channel_number, type=0, function=0)
                device.channels[channel_number] = channel
            channel.value = value
            channel.offline = offline
        await self._notify(device)

    async def update_extended_value(
        self,
        guid: bytes,
        channel_number: int,
        extended: dict[str, Any],
    ) -> None:
        async with self._lock:
            device = self._devices.get(guid_to_hex(guid))
            if device is None:
                return
            channel = device.channels.get(channel_number)
            if channel is None:
                channel = ChannelState(number=channel_number, type=0, function=0)
                device.channels[channel_number] = channel
            channel.extended = extended
        await self._notify(device)

    async def trigger_action(
        self,
        guid: bytes,
        channel_number: int,
        actions: int,
    ) -> None:
        """Record and announce an action trigger (button press).

        The bitmask is kept as the channel value so readers see the last press,
        but two identical presses in a row leave that value unchanged, so
        listeners are notified separately rather than by diffing state.
        """
        async with self._lock:
            device = self._devices.get(guid_to_hex(guid))
            if device is None:
                return
            channel = device.channels.get(channel_number)
            if channel is None:
                channel = ChannelState(number=channel_number, type=0, function=0)
                device.channels[channel_number] = channel
            channel.value = actions.to_bytes(8, "little", signed=False)

        for listener in self._action_listeners:
            result = listener(device, channel_number, actions)
            if asyncio.iscoroutine(result):
                await result
        await self._notify(device)

    async def add_sub_device(self, guid: bytes, details: dict[str, Any]) -> None:
        async with self._lock:
            device = self._devices.get(guid_to_hex(guid))
            if device is None:
                return
            device.sub_devices[int(details["sub_device_id"])] = details
        await self._notify(device)

    async def update_channel_config(
        self,
        guid: bytes,
        channel_number: int,
        function: int,
        config_type: int,
        raw: bytes,
    ) -> None:
        """Record the configuration a device says it is running."""
        if config_type != C.SUPLA_CONFIG_TYPE_DEFAULT:
            # Weekly schedules and the other config types are not modelled.
            logger.debug(
                "ignoring channel %s config of type %s", channel_number, config_type
            )
            return
        async with self._lock:
            device = self._devices.get(guid_to_hex(guid))
            if device is None:
                return
            channel = device.channels.get(channel_number)
            if channel is None:
                return
            channel.config = raw
            if function and not channel.function:
                channel.function = function
        logger.info(
            "channel %s reported config: %s",
            channel_number,
            config_mod.describe(channel.decoded_config()) or f"{len(raw)} bytes",
        )
        await self._notify(device)

    async def update_device_config(
        self,
        guid: bytes,
        end_of_data: int,
        available_fields: int,
        fields: int,
        raw: bytes,
    ) -> None:
        """Record device-level configuration, reassembling split messages."""
        key = guid_to_hex(guid)
        async with self._lock:
            device = self._devices.get(key)
            if device is None:
                return
            merged_fields, buffer = self._device_config_parts.get(key, (0, bytearray()))
            merged_fields |= fields
            buffer.extend(raw)
            if not end_of_data:
                self._device_config_parts[key] = (merged_fields, buffer)
                return
            self._device_config_parts.pop(key, None)
            device.device_config = bytes(buffer)
            device.device_config_fields = merged_fields
            device.device_config_available = available_fields
        logger.info(
            "device %s reported config fields 0x%x (%d bytes)",
            key,
            merged_fields,
            len(device.device_config),
        )
        await self._notify(device)

    async def write_channel_config(
        self,
        guid: str | bytes,
        channel_number: int,
        field: str,
        value: int,
    ) -> None:
        """Change one channel setting and wait for the device to accept it."""
        device = self.get(guid)
        if device is None or device.session is None or not device.session.is_connected:
            raise RuntimeError("device is offline")
        channel = device.channels.get(channel_number)
        if channel is None:
            raise KeyError(f"channel {channel_number} not found")
        spec = channel.config_spec
        if spec is None:
            raise config_mod.ConfigError(
                f"channel {channel_number} has no configurable settings"
            )

        payload = spec.with_field(channel.config, field, value)
        if payload == channel.config:
            return
        result = await device.session.send_channel_config(
            channel_number=channel_number,
            func=channel.function,
            config_type=C.SUPLA_CONFIG_TYPE_DEFAULT,
            config=payload,
        )
        if result != C.SUPLA_CONFIG_RESULT_TRUE:
            raise ConfigRejected(result)

        async with self._lock:
            channel.config = payload
        logger.info("channel %s config %s set to %s", channel_number, field, value)
        await self._notify(device)

    async def write_device_config(
        self,
        guid: str | bytes,
        name: str,
        field: str,
        value: int,
    ) -> None:
        """Change one device-level setting and wait for the device to accept it."""
        device = self.get(guid)
        if device is None or device.session is None or not device.session.is_connected:
            raise RuntimeError("device is offline")

        entry = config_mod.DEVICE_CONFIG_BY_NAME.get(name)
        if entry is None:
            raise config_mod.ConfigError(f"unknown device config field {name!r}")
        available = device.device_config_available
        if available and not available & entry.bit:
            raise config_mod.ConfigError(f"device does not support {name!r}")

        payload, fields = config_mod.device_config_with_field(
            device.device_config, device.device_config_fields, name, field, value
        )
        if payload == device.device_config and fields == device.device_config_fields:
            return
        result = await device.session.send_device_config(
            available_fields=available or fields,
            fields=fields,
            config=payload,
        )
        if result != C.SUPLA_CONFIG_RESULT_TRUE:
            raise ConfigRejected(result)

        async with self._lock:
            device.device_config = payload
            device.device_config_fields = fields
        logger.info("device config %s.%s set to %s", name, field, value)
        await self._notify(device)

    async def forget(self, guid: str | bytes) -> ConnectedDevice | None:
        """Drop a device and hang up on it.

        The device is removed before its session is closed, so the disconnect
        does not announce a device that no longer exists. Registration is open,
        so it comes back if it connects again.
        """
        key = guid_to_hex(guid) if isinstance(guid, bytes) else _normalise(guid)
        async with self._lock:
            device = self._devices.pop(key, None)
            self._device_config_parts.pop(key, None)
        if device is not None and device.session is not None:
            logger.info("forgetting device %s", key)
            await device.session.close()
        return device

    def list_devices(self) -> list[ConnectedDevice]:
        return list(self._devices.values())

    def get(self, guid: str | bytes) -> ConnectedDevice | None:
        key = guid_to_hex(guid) if isinstance(guid, bytes) else _normalise(guid)
        return self._devices.get(key)


def _normalise(guid: str) -> str:
    return guid.replace("-", "").replace(":", "").upper()


def _channel_state(ch: DeviceChannel) -> ChannelState:
    return ChannelState(
        number=ch.number,
        type=ch.type,
        function=ch.default,
        func_list=ch.func_list,
        flags=ch.flags,
        value=ch.value,
        offline=ch.offline,
        sub_device_id=ch.sub_device_id,
    )
