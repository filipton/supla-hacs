"""Full stack test: fake device registers over TCP and is controlled over HTTP."""

from __future__ import annotations

import asyncio
import struct

import aiohttp
import pytest

from supla_server import consts as C
from supla_server.http_api import create_app
from supla_server.protocol import (
    SuplaPacket,
    encode_packet,
    iter_packets,
)
from supla_server.registry import DeviceRegistry
from supla_server.tcp_server import SuplaTcpServer

GUID = bytes(range(16))

# (number, type, function, initial value)
CHANNELS = [
    (0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_LIGHTSWITCH, bytes(8)),
    (1, C.SUPLA_CHANNELTYPE_DIMMER, C.SUPLA_CHANNELFNC_DIMMER, bytes(8)),
    (2, C.SUPLA_CHANNELTYPE_DIMMERANDRGBLED, C.SUPLA_CHANNELFNC_DIMMERANDRGBLIGHTING, bytes(8)),
    (3, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER, bytes(8)),
    (4, C.SUPLA_CHANNELTYPE_THERMOMETER, C.SUPLA_CHANNELFNC_THERMOMETER, struct.pack("<d", 20.5)),
    (5, C.SUPLA_CHANNELTYPE_HVAC, C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT, bytes(8)),
    (6, C.SUPLA_CHANNELTYPE_BINARYSENSOR, C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR, bytes(8)),
    (7, C.SUPLA_CHANNELTYPE_VALVE_OPENCLOSE, C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE, bytes(8)),
]


def _pad(text: str, size: int) -> bytes:
    return text.encode().ljust(size, b"\x00")


def _register_payload() -> bytes:
    payload = bytearray()
    payload += _pad("test@example.com", C.SUPLA_EMAIL_MAXSIZE)
    payload += bytes(16)  # auth key
    payload += GUID
    payload += _pad("Fake Device", C.SUPLA_DEVICE_NAME_MAXSIZE)
    payload += _pad("1.2.3", C.SUPLA_SOFTVER_MAXSIZE)
    payload += _pad("localhost", C.SUPLA_SERVER_NAME_MAXSIZE)
    payload += struct.pack("<ihh", 0, 1, 2)  # flags, manufacturer, product
    payload += bytes([len(CHANNELS)])
    for number, type_, function, value in CHANNELS:
        # TDS_SuplaDeviceChannel_C: Number, Type, FuncList, Default, Flags, value
        payload += bytes([number]) + struct.pack("<iiii", type_, 0, function, 0) + value
    return bytes(payload)


class FakeDevice:
    """Minimal SUPLA device: registers, then records every set-value command."""

    def __init__(self) -> None:
        self.commands: list[tuple[int, bytes]] = []
        self.registered = asyncio.Event()
        self._buffer = bytearray()

    async def connect(self, port: int) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read_loop())
        await self._send(C.SUPLA_DS_CALL_REGISTER_DEVICE_E, _register_payload())

    async def _send(self, call_id: int, data: bytes) -> None:
        self._writer.write(encode_packet(SuplaPacket(version=25, rr_id=1, call_id=call_id, data=data)))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        while True:
            chunk = await self._reader.read(4096)
            if not chunk:
                return
            self._buffer.extend(chunk)
            for packet in iter_packets(self._buffer):
                if packet.call_id == C.SUPLA_SD_CALL_REGISTER_DEVICE_RESULT:
                    self.registered.set()
                elif packet.call_id == C.SUPLA_SD_CALL_CHANNEL_SET_VALUE:
                    number = packet.data[4]
                    self.commands.append((number, packet.data[9:17]))

    async def report_value(self, number: int, value: bytes) -> None:
        await self._send(
            C.SUPLA_DS_CALL_DEVICE_CHANNEL_VALUE_CHANGED, bytes([number]) + value
        )

    async def report_extended(self, number: int, ev_type: int, payload: bytes) -> None:
        data = bytes([number, ev_type]) + struct.pack("<I", len(payload)) + payload
        await self._send(C.SUPLA_DS_CALL_DEVICE_CHANNEL_EXTENDEDVALUE_CHANGED, data)

    async def close(self) -> None:
        self._task.cancel()
        self._writer.close()


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.fixture
async def stack():
    registry = DeviceRegistry()
    tcp = SuplaTcpServer(registry, host="127.0.0.1", port=0, tls_port=None)
    await tcp.start()
    port = tcp.servers[0].sockets[0].getsockname()[1]

    runner = aiohttp.web.AppRunner(create_app(registry))
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    http_port = list(runner.addresses)[0][1]

    device = FakeDevice()
    await device.connect(port)
    await asyncio.wait_for(device.registered.wait(), timeout=2)

    async with aiohttp.ClientSession(base_url=f"http://127.0.0.1:{http_port}") as client:
        yield client, device, registry

    await device.close()
    await runner.cleanup()
    await tcp.stop()


async def test_device_registers_with_all_channel_kinds(stack) -> None:
    client, _device, _registry = stack
    async with client.get("/api/devices") as resp:
        body = await resp.json()

    device = body["devices"][0]
    assert device["name"] == "Fake Device"
    assert device["online"] is True
    kinds = {ch["number"]: ch["kind"] for ch in device["channels"]}
    assert kinds == {
        0: "relay",
        1: "dimmer",
        2: "dimmer_rgb",
        3: "roller_shutter",
        4: "thermometer",
        5: "hvac",
        6: "binary_sensor",
        7: "valve_open_close",
    }
    temperature = next(ch for ch in device["channels"] if ch["number"] == 4)
    assert temperature["value"]["temperature"] == 20.5
    assert temperature["controllable"] is False


@pytest.mark.parametrize(
    ("number", "command", "expected_prefix"),
    [
        (0, {"action": "on"}, bytes([1])),
        (1, {"action": "brightness", "brightness": 55}, bytes([55])),
        (2, {"action": "color", "color": "#ff8000"}, bytes([0, 100, 0x00, 0x80, 0xFF])),
        (3, {"action": "position", "position": 20}, bytes([30])),
        (7, {"action": "close"}, bytes([1])),
    ],
)
async def test_commands_reach_the_device(stack, number, command, expected_prefix) -> None:
    client, device, _registry = stack
    async with client.post(f"/api/devices/{GUID.hex().upper()}/channels/{number}", json=command) as resp:
        assert resp.status == 200

    await _wait_for(lambda: any(cmd[0] == number for cmd in device.commands))
    sent = next(value for num, value in device.commands if num == number)
    assert sent[: len(expected_prefix)] == expected_prefix


async def test_hvac_setpoint_command(stack) -> None:
    client, device, _registry = stack
    async with client.post(
        f"/api/devices/{GUID.hex().upper()}/channels/5",
        json={"action": "heat", "setpoint_heat": 22.5},
    ) as resp:
        assert resp.status == 200

    await _wait_for(lambda: any(cmd[0] == 5 for cmd in device.commands))
    sent = next(value for num, value in device.commands if num == 5)
    is_on, mode, heat, _cool, flags = struct.unpack("<BBhhH", sent)
    assert (is_on, mode, heat) == (1, C.SUPLA_HVAC_MODE_HEAT, 2250)
    assert flags & C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET


async def test_device_reported_state_shows_up_in_api(stack) -> None:
    client, device, _registry = stack
    await device.report_value(6, bytes([1]) + bytes(7))
    await device.report_extended(
        4, C.EV_TYPE_ELECTRICITY_METER_MEASUREMENT_V3, struct.pack("<QQQ", 100000, 0, 0)
    )

    async def sensor_is_on() -> bool:
        async with client.get(f"/api/devices/{GUID.hex().upper()}") as resp:
            body = await resp.json()
        channel = next(ch for ch in body["channels"] if ch["number"] == 6)
        return channel["value"]["on"] is True

    deadline = asyncio.get_running_loop().time() + 2
    while asyncio.get_running_loop().time() < deadline:
        if await sensor_is_on():
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("binary sensor state was not updated")

    async with client.get(f"/api/devices/{GUID.hex().upper()}") as resp:
        body = await resp.json()
    meter = next(ch for ch in body["channels"] if ch["number"] == 4)
    assert meter["extended"]["total_forward_active_energy_kwh"][0] == 1.0


async def test_web_panel_is_served(stack) -> None:
    client, _device, _registry = stack
    async with client.get("/") as resp:
        assert resp.status == 200
        assert "SUPLA test panel" in await resp.text()
    async with client.get("/static/app.js") as resp:
        assert resp.status == 200
