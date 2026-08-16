"""Configuration structs, and the exchange that carries them to a device."""

from __future__ import annotations

import asyncio
import struct

import pytest

from supla_server import config as cfg
from supla_server import consts as C
from supla_server.protocol import (
    SuplaPacket,
    decode_channel_config,
    decode_device_config,
    encode_channel_config,
    encode_device_config,
    encode_packet,
    iter_packets,
)
from supla_server.registry import ConfigRejected, DeviceRegistry
from supla_server.tcp_server import SuplaTcpServer

GUID = bytes(range(16))

RELAY = (0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER)
SENSOR = (1, C.SUPLA_CHANNELTYPE_BINARYSENSOR, C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR)


# --- struct layouts --------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "size"),
    [
        (cfg.STAIRCASE_TIMER, 4),
        (cfg.ROLLER_SHUTTER, 44),
        (cfg.FACADE_BLIND, 53),
        (cfg.BINARY_SENSOR, 32),
        (cfg.TEMPERATURE_AND_HUMIDITY, 32),
        (cfg.POWER_SWITCH, 42),
    ],
)
def test_struct_sizes_match_proto_h(spec: cfg.ConfigSpec, size: int) -> None:
    assert spec.size == size


@pytest.mark.parametrize(
    "spec",
    [
        cfg.STAIRCASE_TIMER,
        cfg.ROLLER_SHUTTER,
        cfg.FACADE_BLIND,
        cfg.BINARY_SENSOR,
        cfg.TEMPERATURE_AND_HUMIDITY,
        cfg.POWER_SWITCH,
    ],
)
def test_no_field_runs_past_the_end_of_its_struct(spec: cfg.ConfigSpec) -> None:
    for field in spec.fields:
        assert field.offset + field.size <= spec.size, f"{spec.name}.{field.key}"


@pytest.mark.parametrize(
    "spec",
    [cfg.ROLLER_SHUTTER, cfg.FACADE_BLIND, cfg.BINARY_SENSOR, cfg.POWER_SWITCH],
)
def test_fields_do_not_overlap(spec: cfg.ConfigSpec) -> None:
    used: dict[int, str] = {}
    for field in spec.fields:
        for offset in range(field.offset, field.offset + field.size):
            assert offset not in used, f"{spec.name}: {field.key} over {used[offset]}"
            used[offset] = field.key


def test_roller_shutter_round_trips() -> None:
    raw = cfg.ROLLER_SHUTTER.with_field(None, "opening_time", 12_500)
    raw = cfg.ROLLER_SHUTTER.with_field(raw, "closing_time", 11_000)
    values = cfg.ROLLER_SHUTTER.decode(raw)

    assert values["opening_time"] == 12_500
    assert values["closing_time"] == 11_000
    assert len(raw) == cfg.ROLLER_SHUTTER.size
    # Everything else is left at "not set".
    assert values["motor_upside_down"] == 0


def test_a_write_preserves_every_byte_it_does_not_own() -> None:
    """The whole point: unknown and reserved regions survive a write."""
    original = bytes(range(cfg.ROLLER_SHUTTER.size))
    updated = cfg.ROLLER_SHUTTER.with_field(original, "opening_time", 7_000)

    assert struct.unpack_from("<i", updated, 4)[0] == 7_000
    assert updated[:4] == original[:4]
    assert updated[8:] == original[8:]


def test_a_write_extends_a_short_payload_without_disturbing_it() -> None:
    partial = b"\x01\x02\x03\x04"
    updated = cfg.BINARY_SENSOR.with_field(partial, "sensitivity", 51)
    assert updated[:4] == partial
    assert len(updated) == cfg.BINARY_SENSOR.size
    assert cfg.BINARY_SENSOR.decode(updated)["sensitivity"] == 51


def test_device_reported_limits_cannot_be_written() -> None:
    with pytest.raises(cfg.ConfigError, match="device only"):
        cfg.POWER_SWITCH.with_field(None, "overcurrent_max_allowed", 100)


def test_a_value_too_large_for_its_field_is_refused() -> None:
    with pytest.raises(cfg.ConfigError, match="does not fit"):
        cfg.BINARY_SENSOR.with_field(None, "inverted_logic", 300)


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(cfg.ConfigError, match="no field"):
        cfg.STAIRCASE_TIMER.with_field(None, "nonsense", 1)


def test_a_short_payload_decodes_only_what_it_holds() -> None:
    assert cfg.ROLLER_SHUTTER.decode(b"\x10\x00\x00\x00") == {"closing_time": 16}
    assert cfg.ROLLER_SHUTTER.decode(None) == {}


# --- device configuration layout -------------------------------------------


def test_device_config_fields_are_laid_out_in_bit_order() -> None:
    fields = cfg.FIELD_STATUS_LED | cfg.FIELD_BUTTON_VOLUME | cfg.FIELD_POWER_STATUS_LED
    layout = cfg.device_config_layout(fields)
    assert layout["status_led"][0] == 0
    assert layout["button_volume"][0] == 1
    assert layout["power_status_led"][0] == 2


def test_device_config_layout_skips_absent_fields() -> None:
    # Screen brightness is 3 bytes and sits between the two.
    fields = cfg.FIELD_STATUS_LED | cfg.FIELD_SCREEN_BRIGHTNESS | cfg.FIELD_BUTTON_VOLUME
    layout = cfg.device_config_layout(fields)
    assert layout["screen_brightness"][0] == 1
    assert layout["button_volume"][0] == 4


def test_device_config_layout_stops_at_an_unmeasurable_field() -> None:
    """A field of unknown size makes every later offset a guess."""
    unknown = 1 << 40
    layout = cfg.device_config_layout(cfg.FIELD_STATUS_LED | unknown | (1 << 41))
    assert set(layout) == {"status_led"}


def test_changing_a_reported_device_field_edits_it_in_place() -> None:
    fields = cfg.FIELD_STATUS_LED | cfg.FIELD_BUTTON_VOLUME
    raw = bytes([cfg.STATUS_LED_ALWAYS_OFF, 40])

    updated, new_fields = cfg.device_config_with_field(
        raw, fields, "button_volume", "volume", 75
    )
    assert new_fields == fields
    assert updated == bytes([cfg.STATUS_LED_ALWAYS_OFF, 75])


def test_a_device_field_never_reported_is_inserted_in_bit_order() -> None:
    fields = cfg.FIELD_STATUS_LED | cfg.FIELD_BUTTON_VOLUME
    raw = bytes([cfg.STATUS_LED_ALWAYS_OFF, 40])

    # Screen brightness is bit 1, so it belongs between the two existing fields.
    updated, new_fields = cfg.device_config_with_field(
        raw, fields, "screen_brightness", "screen_brightness", 60
    )
    assert new_fields == fields | cfg.FIELD_SCREEN_BRIGHTNESS
    assert updated == bytes([cfg.STATUS_LED_ALWAYS_OFF, 60, 0, 0, 40])

    decoded = cfg.decode_device_config(new_fields, updated)
    assert decoded["screen_brightness"]["screen_brightness"] == 60
    assert decoded["button_volume"]["volume"] == 40


def test_inserting_is_refused_when_an_unmeasurable_field_is_present() -> None:
    fields = cfg.FIELD_STATUS_LED | (1 << 40)
    with pytest.raises(cfg.ConfigError, match="does not know how to measure"):
        cfg.device_config_with_field(
            bytes([0, 9, 9]), fields, "button_volume", "volume", 10
        )


def test_device_config_packet_round_trips() -> None:
    raw = encode_device_config(available_fields=0x1FF, fields=0x05, config=b"\x02\x50")
    assert decode_device_config(raw) == (1, 0x1FF, 0x05, b"\x02\x50")


def test_channel_config_packet_round_trips() -> None:
    raw = encode_channel_config(
        channel_number=7, function=110, config_type=0, config=b"\xaa\xbb"
    )
    assert decode_channel_config(raw) == (7, 110, 0, b"\xaa\xbb")


# --- the exchange with a device --------------------------------------------


def _pad(text: str, size: int) -> bytes:
    return text.encode().ljust(size, b"\x00")


def _register_payload(flags: int, channel_flags: int) -> bytes:
    payload = bytearray()
    payload += _pad("test@example.com", C.SUPLA_EMAIL_MAXSIZE)
    payload += bytes(16)
    payload += GUID
    payload += _pad("Config Device", C.SUPLA_DEVICE_NAME_MAXSIZE)
    payload += _pad("1.2.3", C.SUPLA_SOFTVER_MAXSIZE)
    payload += _pad("localhost", C.SUPLA_SERVER_NAME_MAXSIZE)
    payload += struct.pack("<ihh", flags, 1, 2)
    channels = [RELAY, SENSOR]
    payload += bytes([len(channels)])
    for number, type_, function in channels:
        payload += bytes([number])
        payload += struct.pack("<iiii", type_, 0, function, channel_flags)
        payload += bytes(8)
    return bytes(payload)


class ConfigDevice:
    """A device that reports configuration and answers configuration writes."""

    def __init__(self, *, accept: int = C.SUPLA_CONFIG_RESULT_TRUE) -> None:
        self.accept = accept
        #: Set to True to make the device ignore config writes entirely.
        self.silent = False
        self.registered = asyncio.Event()
        self.channel_configs: list[tuple[int, int, int, bytes]] = []
        self.device_configs: list[tuple[int, int, bytes]] = []
        self.config_results: list[tuple[int, int, bytes]] = []
        self._buffer = bytearray()

    async def connect(
        self,
        port: int,
        *,
        flags: int = C.SUPLA_DEVICE_FLAG_DEVICE_CONFIG_SUPPORTED,
        channel_flags: int = C.SUPLA_CHANNEL_FLAG_RUNTIME_CHANNEL_CONFIG_UPDATE,
    ) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read_loop())
        await self.send(
            C.SUPLA_DS_CALL_REGISTER_DEVICE_E, _register_payload(flags, channel_flags)
        )
        await asyncio.wait_for(self.registered.wait(), timeout=5)

    async def send(self, call_id: int, data: bytes) -> None:
        self._writer.write(
            encode_packet(SuplaPacket(version=25, rr_id=1, call_id=call_id, data=data))
        )
        await self._writer.drain()

    async def report_channel_config(
        self, channel_number: int, func: int, config: bytes
    ) -> None:
        await self.send(
            C.SUPLA_DS_CALL_SET_CHANNEL_CONFIG,
            encode_channel_config(
                channel_number=channel_number,
                function=func,
                config_type=C.SUPLA_CONFIG_TYPE_DEFAULT,
                config=config,
            ),
        )

    async def report_device_config(
        self, available: int, fields: int, config: bytes, *, end: bool = True
    ) -> None:
        await self.send(
            C.SUPLA_DS_CALL_SET_DEVICE_CONFIG,
            encode_device_config(
                available_fields=available,
                fields=fields,
                config=config,
                end_of_data=end,
            ),
        )

    async def ask_for_channel_config(self, channel_number: int) -> None:
        await self.send(
            C.SUPLA_DS_CALL_GET_CHANNEL_CONFIG,
            bytes([channel_number, C.SUPLA_CONFIG_TYPE_DEFAULT]) + struct.pack("<I", 0),
        )

    async def _read_loop(self) -> None:
        while True:
            chunk = await self._reader.read(4096)
            if not chunk:
                return
            self._buffer.extend(chunk)
            for packet in iter_packets(self._buffer):
                await self._on_packet(packet)

    async def _on_packet(self, packet: SuplaPacket) -> None:
        if packet.call_id == C.SUPLA_SD_CALL_REGISTER_DEVICE_RESULT:
            self.registered.set()
        elif packet.call_id == C.SUPLA_SD_CALL_GET_CHANNEL_CONFIG_RESULT:
            self.config_results.append(decode_channel_config(packet.data)[1:])
        elif packet.call_id == C.SUPLA_SD_CALL_SET_CHANNEL_CONFIG:
            number, func, config_type, raw = decode_channel_config(packet.data)
            self.channel_configs.append((number, func, config_type, raw))
            if not self.silent:
                await self.send(
                    C.SUPLA_DS_CALL_SET_CHANNEL_CONFIG_RESULT,
                    bytes([self.accept, config_type, number]),
                )
        elif packet.call_id == C.SUPLA_SD_CALL_SET_DEVICE_CONFIG:
            _end, available, fields, raw = decode_device_config(packet.data)
            self.device_configs.append((available, fields, raw))
            if not self.silent:
                await self.send(
                    C.SUPLA_DS_CALL_SET_DEVICE_CONFIG_RESULT,
                    bytes([self.accept]) + bytes(9),
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
    devices: list[ConfigDevice] = []

    async def connect(**kwargs) -> ConfigDevice:
        device = ConfigDevice(**kwargs.pop("device_kwargs", {}))
        await device.connect(port, **kwargs)
        devices.append(device)
        return device

    yield registry, connect

    for device in devices:
        await device.close()
    await server.stop()


async def test_capability_flags_are_read_from_registration(stack) -> None:
    registry, connect = stack
    await connect()
    device = registry.get(GUID)
    assert device.supports_device_config
    assert device.channels[0].accepts_runtime_config


async def test_a_device_reporting_its_channel_config_is_recorded(stack) -> None:
    registry, connect = stack
    fake = await connect()

    config = cfg.ROLLER_SHUTTER.with_field(None, "opening_time", 9_500)
    await fake.report_channel_config(0, RELAY[2], config)

    await _wait_for(lambda: registry.get(GUID).channels[0].config is not None)
    assert registry.get(GUID).channels[0].decoded_config()["opening_time"] == 9_500


async def test_config_of_a_type_we_do_not_model_is_ignored(stack) -> None:
    registry, connect = stack
    fake = await connect()

    await fake.send(
        C.SUPLA_DS_CALL_SET_CHANNEL_CONFIG,
        encode_channel_config(
            channel_number=0,
            function=RELAY[2],
            config_type=C.SUPLA_CONFIG_TYPE_WEEKLY_SCHEDULE,
            config=b"\x01" * 40,
        ),
    )
    await asyncio.sleep(0.1)
    assert registry.get(GUID).channels[0].config is None


async def test_writing_a_setting_sends_it_and_records_the_result(stack) -> None:
    registry, connect = stack
    fake = await connect()

    await registry.write_channel_config(GUID, 0, "opening_time", 8_000)

    assert len(fake.channel_configs) == 1
    number, func, config_type, raw = fake.channel_configs[0]
    assert (number, func, config_type) == (0, RELAY[2], C.SUPLA_CONFIG_TYPE_DEFAULT)
    assert cfg.ROLLER_SHUTTER.decode(raw)["opening_time"] == 8_000
    assert registry.get(GUID).channels[0].decoded_config()["opening_time"] == 8_000


async def test_a_write_builds_on_what_the_device_reported(stack) -> None:
    registry, connect = stack
    fake = await connect()

    reported = bytearray(bytes(range(cfg.ROLLER_SHUTTER.size)))
    await fake.report_channel_config(0, RELAY[2], bytes(reported))
    await _wait_for(lambda: registry.get(GUID).channels[0].config is not None)

    await registry.write_channel_config(GUID, 0, "opening_time", 8_000)

    _number, _func, _type, raw = fake.channel_configs[0]
    assert raw[:4] == bytes(reported[:4])
    assert raw[8:] == bytes(reported[8:])
    assert cfg.ROLLER_SHUTTER.decode(raw)["opening_time"] == 8_000


async def test_a_rejected_write_leaves_the_stored_config_alone(stack) -> None:
    registry, connect = stack
    await connect(
        device_kwargs={"accept": C.SUPLA_CONFIG_RESULT_FUNCTION_NOT_SUPPORTED}
    )

    with pytest.raises(ConfigRejected, match="function not supported"):
        await registry.write_channel_config(GUID, 0, "opening_time", 8_000)
    assert registry.get(GUID).channels[0].config is None


async def test_a_write_to_an_unconfigurable_channel_is_refused(stack) -> None:
    registry, connect = stack
    await connect()
    # A door sensor uses the binary sensor struct, which has no opening time.
    with pytest.raises(cfg.ConfigError, match="no field"):
        await registry.write_channel_config(GUID, 1, "opening_time", 100)


async def test_a_write_to_an_offline_device_is_refused(stack) -> None:
    registry, connect = stack
    fake = await connect()
    await fake.close()
    await _wait_for(lambda: not registry.get(GUID).online)

    with pytest.raises(RuntimeError, match="offline"):
        await registry.write_channel_config(GUID, 0, "opening_time", 8_000)


async def test_a_silent_device_times_out_rather_than_hanging(stack) -> None:
    registry, connect = stack
    fake = await connect()
    fake.silent = True

    device = registry.get(GUID)
    with pytest.raises(asyncio.TimeoutError):
        await device.session.send_channel_config(
            channel_number=0,
            func=RELAY[2],
            config_type=C.SUPLA_CONFIG_TYPE_DEFAULT,
            config=cfg.ROLLER_SHUTTER.with_field(None, "opening_time", 1),
            timeout=0.2,
        )


async def test_the_device_gets_its_stored_config_when_it_asks(stack) -> None:
    registry, connect = stack
    fake = await connect()
    await registry.write_channel_config(GUID, 0, "opening_time", 8_000)

    await fake.ask_for_channel_config(0)
    await _wait_for(lambda: bool(fake.config_results))

    func, config_type, raw = fake.config_results[0]
    assert (func, config_type) == (RELAY[2], C.SUPLA_CONFIG_TYPE_DEFAULT)
    assert cfg.ROLLER_SHUTTER.decode(raw)["opening_time"] == 8_000


async def test_configuration_survives_a_re_registration(stack) -> None:
    registry, connect = stack
    fake = await connect()
    await registry.write_channel_config(GUID, 0, "opening_time", 8_000)
    await fake.close()

    again = await connect()
    assert registry.get(GUID).channels[0].decoded_config()["opening_time"] == 8_000
    await again.close()


async def test_device_level_settings_are_recorded_and_written(stack) -> None:
    registry, connect = stack
    available = cfg.FIELD_STATUS_LED | cfg.FIELD_SCREEN_BRIGHTNESS
    fake = await connect()

    await fake.report_device_config(
        available, cfg.FIELD_STATUS_LED, bytes([cfg.STATUS_LED_ON_WHEN_CONNECTED])
    )
    await _wait_for(lambda: registry.get(GUID).device_config_available == available)

    await registry.write_device_config(
        GUID, "screen_brightness", "screen_brightness", 70
    )

    sent_available, sent_fields, raw = fake.device_configs[0]
    assert sent_available == available
    assert sent_fields == available
    assert raw == bytes([cfg.STATUS_LED_ON_WHEN_CONNECTED, 70, 0, 0])
    decoded = registry.get(GUID).decoded_device_config()
    assert decoded["screen_brightness"]["screen_brightness"] == 70
    assert decoded["status_led"]["status_led_type"] == cfg.STATUS_LED_ON_WHEN_CONNECTED


async def test_a_setting_the_device_does_not_offer_is_refused(stack) -> None:
    registry, connect = stack
    fake = await connect()
    await fake.report_device_config(cfg.FIELD_STATUS_LED, cfg.FIELD_STATUS_LED, b"\x00")
    await _wait_for(lambda: registry.get(GUID).device_config_available != 0)

    with pytest.raises(cfg.ConfigError, match="does not support"):
        await registry.write_device_config(GUID, "button_volume", "volume", 50)


async def test_a_split_device_config_is_reassembled(stack) -> None:
    registry, connect = stack
    available = cfg.FIELD_STATUS_LED | cfg.FIELD_BUTTON_VOLUME
    fake = await connect()

    await fake.report_device_config(
        available, cfg.FIELD_STATUS_LED, b"\x02", end=False
    )
    await asyncio.sleep(0.05)
    assert registry.get(GUID).device_config == b""

    await fake.report_device_config(available, cfg.FIELD_BUTTON_VOLUME, b"\x37")
    await _wait_for(lambda: registry.get(GUID).device_config == b"\x02\x37")

    decoded = registry.get(GUID).decoded_device_config()
    assert decoded["status_led"]["status_led_type"] == cfg.STATUS_LED_ALWAYS_OFF
    assert decoded["button_volume"]["volume"] == 0x37
