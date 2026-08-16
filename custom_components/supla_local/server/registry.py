"""Connected device registry and channel state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from . import channels
from .protocol import DeviceChannel, RegisterDevice, guid_to_hex

if TYPE_CHECKING:
    from .session import DeviceSession

logger = logging.getLogger(__name__)

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
    session: DeviceSession | None = field(default=None, repr=False)

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
            # Preserve extended values across re-registration.
            if existing:
                for number, channel in new_channels.items():
                    previous = existing.channels.get(number)
                    if previous is not None:
                        channel.extended = previous.extended

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

    def list_devices(self) -> list[ConnectedDevice]:
        return list(self._devices.values())

    def get(self, guid: str | bytes) -> ConnectedDevice | None:
        if isinstance(guid, bytes):
            key = guid_to_hex(guid)
        else:
            key = guid.replace("-", "").replace(":", "").upper()
        return self._devices.get(key)


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
