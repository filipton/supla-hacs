"""Device diagnostics as Home Assistant entities."""

from __future__ import annotations

import struct

import pytest
from conftest import GUID_HEX, entity_id_for, wait_for
from fake_device import FakeDevice

from custom_components.supla_local.const import DOMAIN, STORAGE_KEY
from custom_components.supla_local.server import consts as C
from custom_components.supla_local.server.protocol import SuplaPacket, iter_packets
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

REPORTED = (
    C.SUPLA_CHANNELSTATE_FIELD_IPV4
    | C.SUPLA_CHANNELSTATE_FIELD_MAC
    | C.SUPLA_CHANNELSTATE_FIELD_WIFIRSSI
    | C.SUPLA_CHANNELSTATE_FIELD_WIFISIGNALSTRENGTH
    | C.SUPLA_CHANNELSTATE_FIELD_UPTIME
    | C.SUPLA_CHANNELSTATE_FIELD_CONNECTIONUPTIME
    | C.SUPLA_CHANNELSTATE_FIELD_LASTCONNECTIONRESETCAUSE
)


def channel_state(*, channel: int = 0, fields: int = REPORTED, uptime: int = 86_400):
    raw = bytearray(50)
    raw[4] = channel
    struct.pack_into("<i", raw, 8, fields)
    raw[16:20] = bytes([192, 168, 1, 49])
    raw[20:26] = bytes([0xA8, 0xA1, 0x59, 0x23, 0x8E, 0x88])
    struct.pack_into("<b", raw, 28, -62)
    struct.pack_into("<B", raw, 29, 76)
    struct.pack_into("<I", raw, 32, uptime)
    struct.pack_into("<I", raw, 36, 3_600)
    raw[41] = C.SUPLA_LASTCONNECTIONRESETCAUSE_ACTIVITY_TIMEOUT
    return bytes(raw)


class DiagnosticDevice(FakeDevice):
    """Answers the server's request for its diagnostics."""

    def __init__(self) -> None:
        super().__init__()
        self.answers = True
        self.requests: list[int] = []
        self.state = channel_state()

    async def _read_loop(self) -> None:
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    return
                self._buffer.extend(chunk)
                for packet in iter_packets(self._buffer):
                    await self._on_packet(packet)
        finally:
            self.closed.set()

    async def _on_packet(self, packet: SuplaPacket) -> None:
        if packet.call_id == C.SUPLA_SD_CALL_REGISTER_DEVICE_RESULT:
            self.registered.set()
        elif packet.call_id == C.SUPLA_SD_CALL_CHANNEL_SET_VALUE:
            self.commands.append((packet.data[4], packet.data[9:17]))
        elif packet.call_id == C.SUPLA_CSD_CALL_GET_CHANNEL_STATE:
            self.requests.append(packet.data[4])
            if self.answers:
                await self._send(
                    C.SUPLA_DSC_CALL_CHANNEL_STATE_RESULT, self.state
                )


@pytest.fixture
async def device(port: int):
    fake = DiagnosticDevice()
    await fake.connect(port)
    yield fake
    await fake.close()


async def _wait_for_sensor(hass: HomeAssistant, suffix: str) -> str:
    registry = er.async_get(hass)
    await wait_for(
        lambda: registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-{suffix}")
        is not None
    )
    return entity_id_for(hass, "sensor", suffix)


async def test_a_device_is_asked_for_its_diagnostics_when_it_connects(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    await wait_for(lambda: bool(device.requests))
    # Asked on its lowest channel; the readings describe the whole device.
    assert device.requests[0] == 0


async def test_the_readings_become_sensors(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    entity_id = await _wait_for_sensor(hass, "state-ipv4")
    assert hass.states.get(entity_id).state == "192.168.1.49"

    rssi = entity_id_for(hass, "sensor", "state-wifi_rssi")
    state = hass.states.get(rssi)
    assert float(state.state) == -62
    assert state.attributes["unit_of_measurement"] == "dBm"
    assert state.attributes["device_class"] == "signal_strength"

    strength = hass.states.get(entity_id_for(hass, "sensor", "state-wifi_signal_strength"))
    assert float(strength.state) == 76

    reason = hass.states.get(
        entity_id_for(hass, "sensor", "state-last_connection_reset_cause_name")
    )
    assert reason.state == "activity_timeout"
    assert "wifi_connection_lost" in reason.attributes["options"]


async def test_an_uptime_becomes_the_instant_it_counts_from(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    entity_id = await _wait_for_sensor(hass, "state-uptime")
    state = hass.states.get(entity_id)
    assert state.attributes["device_class"] == "timestamp"

    booted = dt_util.parse_datetime(state.state)
    assert booted is not None
    # A day of uptime, give or take the moment the reading was taken.
    age = (dt_util.utcnow() - booted).total_seconds()
    assert 86_000 < age < 87_000


async def test_the_instant_does_not_wander_between_reports(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    """Recomputing "up since" on every read would churn the state endlessly."""
    entity_id = await _wait_for_sensor(hass, "state-uptime")
    first = hass.states.get(entity_id).state

    # A second report, one second further into the same uptime.
    device.state = channel_state(uptime=86_401)
    await device.report_value(1, b"\x01" + bytes(7))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == first


async def test_only_reported_readings_get_sensors(
    hass: HomeAssistant, port: int
) -> None:
    registry = er.async_get(hass)
    fake = DiagnosticDevice()
    fake.state = channel_state(fields=C.SUPLA_CHANNELSTATE_FIELD_IPV4)
    await fake.connect(port)
    try:
        await _wait_for_sensor(hass, "state-ipv4")
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-state-wifi_rssi")
            is None
        )
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-state-uptime")
            is None
        )
    finally:
        await fake.close()


async def test_a_device_that_never_answers_gets_no_diagnostics(
    hass: HomeAssistant, port: int
) -> None:
    registry = er.async_get(hass)
    fake = DiagnosticDevice()
    fake.answers = False
    await fake.connect(port)
    try:
        await wait_for(lambda: bool(fake.requests))
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-state-ipv4")
            is None
        )
    finally:
        await fake.close()


async def test_the_mac_lands_on_the_home_assistant_device(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    await _wait_for_sensor(hass, "state-ipv4")
    entry = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, GUID_HEX)})
    assert (dr.CONNECTION_NETWORK_MAC, "a8:a1:59:23:8e:88") in entry.connections


async def test_the_connection_sensor_reports_how_the_device_got_here(
    hass: HomeAssistant, device: DiagnosticDevice
) -> None:
    attributes = hass.states.get(
        entity_id_for(hass, "binary_sensor", "connectivity")
    ).attributes
    assert attributes["source_address"].startswith("127.0.0.1:")
    assert attributes["encrypted"] is False
    assert attributes["check_in_interval"] > 0


@pytest.fixture
def stored_diagnostics(hass_storage: dict) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "devices": {
                GUID_HEX: {
                    "guid": GUID_HEX,
                    "name": "Fake Device",
                    "channels": [],
                    "sub_devices": [],
                    "state_fields": REPORTED,
                    "mac": "a8:a1:59:23:8e:88",
                }
            }
        },
    }


async def test_diagnostics_entities_come_back_after_a_restart(
    hass: HomeAssistant, stored_diagnostics: None, port: int
) -> None:
    """Which readings a device offers is remembered; the values are not."""
    entity_id = entity_id_for(hass, "sensor", "state-ipv4")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    entry = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, GUID_HEX)})
    assert (dr.CONNECTION_NETWORK_MAC, "a8:a1:59:23:8e:88") in entry.connections

    fake = DiagnosticDevice()
    await fake.connect(port)
    try:
        await wait_for(lambda: hass.states.get(entity_id).state == "192.168.1.49")
    finally:
        await fake.close()
