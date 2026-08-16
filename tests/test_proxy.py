"""The port forwarder, with a real device on one side and a real server on the other."""

from __future__ import annotations

import argparse
import asyncio
import struct

import pytest

from supla_server import consts as C
from supla_server.protocol import SuplaPacket, encode_packet, iter_packets
from supla_server.registry import DeviceRegistry
from supla_server.tcp_server import SuplaTcpServer
from tools.supla_proxy import PortForwarder, parse_port

GUID = bytes(range(16))
CHANNELS = [(0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_POWERSWITCH)]


def _pad(text: str, size: int) -> bytes:
    return text.encode().ljust(size, b"\x00")


def _register_payload() -> bytes:
    payload = bytearray()
    payload += _pad("test@example.com", C.SUPLA_EMAIL_MAXSIZE)
    payload += bytes(16)
    payload += GUID
    payload += _pad("Proxied Device", C.SUPLA_DEVICE_NAME_MAXSIZE)
    payload += _pad("1.2.3", C.SUPLA_SOFTVER_MAXSIZE)
    payload += _pad("localhost", C.SUPLA_SERVER_NAME_MAXSIZE)
    payload += struct.pack("<ihh", 0, 1, 2)
    payload += bytes([len(CHANNELS)])
    for number, type_, function in CHANNELS:
        payload += bytes([number]) + struct.pack("<iiii", type_, 0, function, 0)
        payload += bytes(8)
    return bytes(payload)


class TinyDevice:
    """Registers over TCP and records the commands it is sent."""

    def __init__(self) -> None:
        self.commands: list[tuple[int, bytes]] = []
        self.registered = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._buffer = bytearray()

    async def connect(self, port: int) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read_loop())
        self._writer.write(
            encode_packet(
                SuplaPacket(
                    version=25,
                    rr_id=1,
                    call_id=C.SUPLA_DS_CALL_REGISTER_DEVICE_E,
                    data=_register_payload(),
                )
            )
        )
        await self._writer.drain()
        await asyncio.wait_for(self.registered.wait(), timeout=5)

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
            self.disconnected.set()

    async def close(self) -> None:
        self._task.cancel()
        self._writer.close()


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


@pytest.fixture
async def proxied():
    """A server, a forwarder in front of it, and a device dialling the forwarder."""
    registry = DeviceRegistry()
    server = SuplaTcpServer(registry, host="127.0.0.1", port=0, tls_port=None)
    await server.start()
    server_port = server.servers[0].sockets[0].getsockname()[1]

    forwarder = PortForwarder("127.0.0.1", 0, "127.0.0.1", server_port)
    await forwarder.start()

    device = TinyDevice()
    await device.connect(forwarder.bound_port)

    yield registry, forwarder, device

    await device.close()
    await forwarder.stop()
    await server.stop()


async def test_a_device_registers_through_the_forwarder(proxied) -> None:
    registry, forwarder, _device = proxied
    connected = registry.get(GUID)
    assert connected is not None
    assert connected.name == "Proxied Device"
    assert connected.online
    # The server sees the forwarder, not the device, which is the whole point.
    assert forwarder.bound_port != forwarder.target_port


async def test_commands_travel_back_through_the_forwarder(proxied) -> None:
    registry, _forwarder, device = proxied
    await registry.get(GUID).execute(0, {"action": "on"})
    await _wait_for(lambda: bool(device.commands))
    assert device.commands[0] == (0, b"\x01" + bytes(7))


async def test_reported_values_travel_forwards(proxied) -> None:
    registry, _forwarder, device = proxied
    device._writer.write(
        encode_packet(
            SuplaPacket(
                version=25,
                rr_id=2,
                call_id=C.SUPLA_DS_CALL_DEVICE_CHANNEL_VALUE_CHANGED,
                data=bytes([0]) + b"\x01" + bytes(7),
            )
        )
    )
    await device._writer.drain()
    await _wait_for(lambda: registry.get(GUID).channels[0].decoded()["on"] is True)


async def test_stopping_the_forwarder_drops_the_device(proxied) -> None:
    registry, forwarder, device = proxied
    await forwarder.stop()
    await asyncio.wait_for(device.disconnected.wait(), timeout=5)
    await _wait_for(lambda: not registry.get(GUID).online)


async def test_an_unreachable_target_closes_the_client_cleanly() -> None:
    """A forwarder pointed at nothing must not hang the device."""
    forwarder = PortForwarder("127.0.0.1", 0, "127.0.0.1", 1)
    await forwarder.start()
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", forwarder.bound_port
        )
        assert await asyncio.wait_for(reader.read(1), timeout=5) == b""
        writer.close()
    finally:
        await forwarder.stop()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2015", (2015, 2015)), ("2015:12015", (2015, 12015)), ("2016:2016", (2016, 2016))],
)
def test_port_arguments(value: str, expected: tuple[int, int]) -> None:
    assert parse_port(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "0", "70000", "2015:x"])
def test_bad_port_arguments_are_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_port(value)
