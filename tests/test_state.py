"""Device diagnostics: TDSC_ChannelState, asked for and volunteered."""

from __future__ import annotations

import asyncio
import struct

import pytest

from supla_server import channels
from supla_server import consts as C
from supla_server.protocol import (
    SuplaPacket,
    encode_channel_state_request,
    encode_packet,
    iter_packets,
)
from supla_server.registry import DeviceRegistry
from supla_server.tcp_server import SuplaTcpServer

GUID = bytes(range(16))

REPORTED = (
    C.SUPLA_CHANNELSTATE_FIELD_IPV4
    | C.SUPLA_CHANNELSTATE_FIELD_MAC
    | C.SUPLA_CHANNELSTATE_FIELD_WIFIRSSI
    | C.SUPLA_CHANNELSTATE_FIELD_WIFISIGNALSTRENGTH
    | C.SUPLA_CHANNELSTATE_FIELD_UPTIME
    | C.SUPLA_CHANNELSTATE_FIELD_CONNECTIONUPTIME
    | C.SUPLA_CHANNELSTATE_FIELD_LASTCONNECTIONRESETCAUSE
)


def channel_state(
    *,
    channel: int = 0,
    fields: int = REPORTED,
    ip: tuple[int, int, int, int] = (192, 168, 1, 49),
    mac: bytes = bytes([0xA8, 0xA1, 0x59, 0x23, 0x8E, 0x88]),
    rssi: int = -62,
    strength: int = 76,
    uptime: int = 86_400,
    connection_uptime: int = 3_600,
    cause: int = C.SUPLA_LASTCONNECTIONRESETCAUSE_WIFI_CONNECTION_LOST,
    battery: int | None = None,
) -> bytes:
    raw = bytearray(50)
    raw[4] = channel
    if battery is not None:
        fields |= C.SUPLA_CHANNELSTATE_FIELD_BATTERYLEVEL
        raw[26] = battery
    struct.pack_into("<i", raw, 8, fields)
    raw[16:20] = bytes(ip)
    raw[20:26] = mac
    struct.pack_into("<b", raw, 28, rssi)
    struct.pack_into("<B", raw, 29, strength)
    struct.pack_into("<I", raw, 32, uptime)
    struct.pack_into("<I", raw, 36, connection_uptime)
    raw[41] = cause
    return bytes(raw)


# --- the struct ------------------------------------------------------------


def test_the_struct_is_fifty_bytes() -> None:
    assert len(channel_state()) == 50


def test_every_reported_member_is_decoded() -> None:
    state = channels.decode_channel_state(channel_state())
    assert state["ipv4"] == "192.168.1.49"
    assert state["mac"] == "a8:a1:59:23:8e:88"
    assert state["wifi_rssi"] == -62
    assert state["wifi_signal_strength"] == 76
    assert state["uptime"] == 86_400
    assert state["connection_uptime"] == 3_600
    assert state["last_connection_reset_cause_name"] == "wifi_connection_lost"


def test_members_the_device_did_not_fill_in_are_absent() -> None:
    """The Fields bitmap is what says a member means anything."""
    state = channels.decode_channel_state(
        channel_state(fields=C.SUPLA_CHANNELSTATE_FIELD_IPV4)
    )
    assert state["ipv4"] == "192.168.1.49"
    assert "wifi_rssi" not in state
    assert "uptime" not in state


def test_a_battery_device_reports_its_level() -> None:
    state = channels.decode_channel_state(channel_state(battery=64))
    assert state["battery_level"] == 64


def test_an_older_shorter_struct_decodes_what_it_can() -> None:
    """The struct grew across protocol versions."""
    state = channels.decode_channel_state(channel_state()[:30])
    assert state["ipv4"] == "192.168.1.49"
    assert state["wifi_rssi"] == -62
    assert "uptime" not in state


def test_a_truncated_struct_is_rejected() -> None:
    with pytest.raises(ValueError, match="short channel state"):
        channels.decode_channel_state(b"\x00\x01")


@pytest.mark.parametrize(
    "ev_type",
    [C.EV_TYPE_CHANNEL_STATE_V1, C.EV_TYPE_CHANNEL_AND_TIMER_STATE_V1],
)
def test_state_arriving_as_an_extended_value(ev_type: int) -> None:
    # The combined value appends a timer block the state decoder must ignore.
    payload = channel_state() + bytes(64)
    decoded = channels.decode_extended_value(ev_type, payload)
    assert decoded["state"]["ipv4"] == "192.168.1.49"


def test_the_request_names_the_channel() -> None:
    raw = encode_channel_state_request(7, sender_id=1)
    assert len(raw) == 8
    assert struct.unpack_from("<i", raw, 0)[0] == 1
    assert raw[4] == 7


# --- the exchange ----------------------------------------------------------


def _pad(text: str, size: int) -> bytes:
    return text.encode().ljust(size, b"\x00")


def _register_payload() -> bytes:
    payload = bytearray()
    payload += _pad("test@example.com", C.SUPLA_EMAIL_MAXSIZE)
    payload += bytes(16)
    payload += GUID
    payload += _pad("State Device", C.SUPLA_DEVICE_NAME_MAXSIZE)
    payload += _pad("1.2.3", C.SUPLA_SOFTVER_MAXSIZE)
    payload += _pad("localhost", C.SUPLA_SERVER_NAME_MAXSIZE)
    payload += struct.pack("<ihh", 0, 1, 2)
    payload += bytes([1])
    payload += bytes([3]) + struct.pack(
        "<iiii", C.SUPLA_CHANNELTYPE_RELAY, 0, C.SUPLA_CHANNELFNC_POWERSWITCH, 0
    )
    payload += bytes(8)
    return bytes(payload)


class StateDevice:
    """Answers a state request, and can volunteer one unasked."""

    def __init__(self, *, answers: bool = True) -> None:
        self.answers = answers
        self.registered = asyncio.Event()
        self.requests: list[int] = []
        self._buffer = bytearray()

    async def connect(self, port: int) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read_loop())
        await self.send(C.SUPLA_DS_CALL_REGISTER_DEVICE_E, _register_payload())
        await asyncio.wait_for(self.registered.wait(), timeout=5)

    async def send(self, call_id: int, data: bytes) -> None:
        self._writer.write(
            encode_packet(SuplaPacket(version=25, rr_id=1, call_id=call_id, data=data))
        )
        await self._writer.drain()

    async def report_state_as_extended_value(self, raw: bytes) -> None:
        data = (
            bytes([3, C.EV_TYPE_CHANNEL_STATE_V1])
            + struct.pack("<I", len(raw))
            + raw
        )
        await self.send(C.SUPLA_DS_CALL_DEVICE_CHANNEL_EXTENDEDVALUE_CHANGED, data)

    async def _read_loop(self) -> None:
        while True:
            chunk = await self._reader.read(4096)
            if not chunk:
                return
            self._buffer.extend(chunk)
            for packet in iter_packets(self._buffer):
                if packet.call_id == C.SUPLA_SD_CALL_REGISTER_DEVICE_RESULT:
                    self.registered.set()
                elif packet.call_id == C.SUPLA_CSD_CALL_GET_CHANNEL_STATE:
                    self.requests.append(packet.data[4])
                    if self.answers:
                        await self.send(
                            C.SUPLA_DSC_CALL_CHANNEL_STATE_RESULT,
                            channel_state(channel=packet.data[4]),
                        )

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
async def stack():
    registry = DeviceRegistry()
    server = SuplaTcpServer(registry, host="127.0.0.1", port=0, tls_port=None)
    await server.start()
    port = server.servers[0].sockets[0].getsockname()[1]
    devices: list[StateDevice] = []

    async def connect(**kwargs) -> StateDevice:
        device = StateDevice(**kwargs)
        await device.connect(port)
        devices.append(device)
        return device

    yield registry, connect

    for device in devices:
        await device.close()
    await server.stop()


async def test_asking_a_device_for_its_state(stack) -> None:
    registry, connect = stack
    fake = await connect()

    await registry.get(GUID).session.request_channel_state(3)
    await _wait_for(lambda: bool(registry.get(GUID).state))

    state = registry.get(GUID).state
    assert fake.requests == [3]
    assert state["ipv4"] == "192.168.1.49"
    assert state["wifi_rssi"] == -62
    # Stamped on arrival, so an age can be turned into an instant later.
    assert state["received"] > 0


async def test_a_device_that_volunteers_its_state(stack) -> None:
    registry, connect = stack
    fake = await connect(answers=False)

    await fake.report_state_as_extended_value(channel_state())
    await _wait_for(lambda: "ipv4" in registry.get(GUID).state)
    assert registry.get(GUID).state["mac"] == "a8:a1:59:23:8e:88"


async def test_a_device_that_never_answers_leaves_no_state(stack) -> None:
    registry, connect = stack
    await connect(answers=False)

    await registry.get(GUID).session.request_channel_state(3)
    await asyncio.sleep(0.2)
    assert registry.get(GUID).state == {}


async def test_state_survives_a_re_registration(stack) -> None:
    registry, connect = stack
    fake = await connect()
    await registry.get(GUID).session.request_channel_state(3)
    await _wait_for(lambda: bool(registry.get(GUID).state))
    await fake.close()

    await connect()
    assert registry.get(GUID).state["ipv4"] == "192.168.1.49"
