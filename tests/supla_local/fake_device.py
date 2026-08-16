"""A minimal SUPLA device that speaks the real protocol over a real socket."""

from __future__ import annotations

import asyncio
import struct

from custom_components.supla_local.server import consts as C
from custom_components.supla_local.server.protocol import (
    SuplaPacket,
    encode_packet,
    iter_packets,
)

GUID = bytes(range(16))

# (number, type, function, initial value)
CHANNELS: list[tuple[int, int, int, bytes]] = [
    (0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_LIGHTSWITCH, bytes(8)),
    (1, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_POWERSWITCH, bytes(8)),
    (2, C.SUPLA_CHANNELTYPE_DIMMER, C.SUPLA_CHANNELFNC_DIMMER, bytes(8)),
    (
        3,
        C.SUPLA_CHANNELTYPE_RELAY,
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER,
        bytes(8),
    ),
    (
        4,
        C.SUPLA_CHANNELTYPE_THERMOMETER,
        C.SUPLA_CHANNELFNC_THERMOMETER,
        struct.pack("<d", 20.5),
    ),
    (5, C.SUPLA_CHANNELTYPE_HVAC, C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT, bytes(8)),
    (
        6,
        C.SUPLA_CHANNELTYPE_BINARYSENSOR,
        C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
        bytes(8),
    ),
    (
        7,
        C.SUPLA_CHANNELTYPE_VALVE_OPENCLOSE,
        C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE,
        bytes(8),
    ),
    (
        8,
        C.SUPLA_CHANNELTYPE_ACTIONTRIGGER,
        C.SUPLA_CHANNELFNC_ACTIONTRIGGER,
        bytes(8),
    ),
]


def _pad(text: str, size: int) -> bytes:
    return text.encode().ljust(size, b"\x00")


def register_payload(
    channels: list[tuple[int, int, int, bytes]] | None = None,
    *,
    name: str = "Fake Device",
    guid: bytes = GUID,
) -> bytes:
    payload = bytearray()
    payload += _pad("test@example.com", C.SUPLA_EMAIL_MAXSIZE)
    payload += bytes(16)  # auth key
    payload += guid
    payload += _pad(name, C.SUPLA_DEVICE_NAME_MAXSIZE)
    payload += _pad("1.2.3", C.SUPLA_SOFTVER_MAXSIZE)
    payload += _pad("localhost", C.SUPLA_SERVER_NAME_MAXSIZE)
    payload += struct.pack("<ihh", 0, 1, 2)  # flags, manufacturer, product
    entries = CHANNELS if channels is None else channels
    payload += bytes([len(entries)])
    for number, type_, function, value in entries:
        # TDS_SuplaDeviceChannel_C: Number, Type, FuncList, Default, Flags, value
        payload += bytes([number]) + struct.pack("<iiii", type_, 0, function, 0) + value
    return bytes(payload)


class FakeDevice:
    """Registers, then records every set-value command the server sends."""

    def __init__(self, guid: bytes = GUID) -> None:
        self.guid = guid
        self.commands: list[tuple[int, bytes]] = []
        self.registered = asyncio.Event()
        self.closed = asyncio.Event()
        self._buffer = bytearray()

    async def connect(
        self,
        port: int,
        channels: list[tuple[int, int, int, bytes]] | None = None,
        *,
        name: str = "Fake Device",
    ) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read_loop())
        await self._send(
            C.SUPLA_DS_CALL_REGISTER_DEVICE_E,
            register_payload(channels, name=name, guid=self.guid),
        )
        await asyncio.wait_for(self.registered.wait(), timeout=5)

    async def _send(self, call_id: int, data: bytes) -> None:
        self._writer.write(
            encode_packet(SuplaPacket(version=25, rr_id=1, call_id=call_id, data=data))
        )
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    return
                self._buffer.extend(chunk)
                for packet in iter_packets(self._buffer):
                    if packet.call_id == C.SUPLA_SD_CALL_REGISTER_DEVICE_RESULT:
                        self.registered.set()
                    elif packet.call_id == C.SUPLA_SD_CALL_CHANNEL_SET_VALUE:
                        self.commands.append((packet.data[4], packet.data[9:17]))
        finally:
            self.closed.set()

    async def wait_closed(self) -> None:
        """Resolves when the server hangs up on us."""
        await self.closed.wait()

    async def report_value(self, number: int, value: bytes) -> None:
        await self._send(
            C.SUPLA_DS_CALL_DEVICE_CHANNEL_VALUE_CHANGED, bytes([number]) + value
        )

    async def report_extended(self, number: int, ev_type: int, payload: bytes) -> None:
        data = bytes([number, ev_type]) + struct.pack("<I", len(payload)) + payload
        await self._send(C.SUPLA_DS_CALL_DEVICE_CHANNEL_EXTENDEDVALUE_CHANGED, data)

    async def press(self, number: int, actions: int) -> None:
        await self._send(
            C.SUPLA_DS_CALL_ACTIONTRIGGER, bytes([number]) + struct.pack("<i", actions)
        )

    async def close(self) -> None:
        self._task.cancel()
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, OSError):
            pass
