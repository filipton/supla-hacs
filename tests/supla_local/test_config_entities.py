"""Device and channel settings, edited from Home Assistant."""

from __future__ import annotations

import struct

import pytest
from conftest import GUID_HEX, entity_id_for, wait_for
from fake_device import FakeDevice
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.supla_local.const import DOMAIN, STORAGE_KEY
from custom_components.supla_local.server import config as cfg
from custom_components.supla_local.server import consts as C
from custom_components.supla_local.server.protocol import (
    SuplaPacket,
    decode_channel_config,
    decode_device_config,
    encode_channel_config,
    encode_device_config,
)

CONFIGURABLE = C.SUPLA_CHANNEL_FLAG_RUNTIME_CHANNEL_CONFIG_UPDATE

SHUTTER = (
    0,
    C.SUPLA_CHANNELTYPE_RELAY,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER,
    bytes(8),
)
DOOR = (
    1,
    C.SUPLA_CHANNELTYPE_BINARYSENSOR,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
    bytes(8),
)
STAIRCASE = (
    2,
    C.SUPLA_CHANNELTYPE_RELAY,
    C.SUPLA_CHANNELFNC_STAIRCASETIMER,
    bytes(8),
)


class ConfigurableDevice(FakeDevice):
    """A fake device that reports and accepts configuration."""

    def __init__(self) -> None:
        super().__init__()
        self.accept = C.SUPLA_CONFIG_RESULT_TRUE
        self.channel_configs: list[tuple[int, int, int, bytes]] = []
        self.served_configs: list[tuple[int, int, int, bytes]] = []
        self.device_configs: list[tuple[int, int, bytes]] = []

    async def _read_loop(self) -> None:  # noqa: D401 - see FakeDevice
        from custom_components.supla_local.server.protocol import iter_packets

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
        elif packet.call_id == C.SUPLA_SD_CALL_GET_CHANNEL_CONFIG_RESULT:
            self.served_configs.append(decode_channel_config(packet.data))
        elif packet.call_id == C.SUPLA_SD_CALL_CHANNEL_SET_VALUE:
            self.commands.append((packet.data[4], packet.data[9:17]))
        elif packet.call_id == C.SUPLA_SD_CALL_SET_CHANNEL_CONFIG:
            number, func, config_type, raw = decode_channel_config(packet.data)
            self.channel_configs.append((number, func, config_type, raw))
            await self._send(
                C.SUPLA_DS_CALL_SET_CHANNEL_CONFIG_RESULT,
                bytes([self.accept, config_type, number]),
            )
        elif packet.call_id == C.SUPLA_SD_CALL_SET_DEVICE_CONFIG:
            _end, available, fields, raw = decode_device_config(packet.data)
            self.device_configs.append((available, fields, raw))
            await self._send(
                C.SUPLA_DS_CALL_SET_DEVICE_CONFIG_RESULT,
                bytes([self.accept]) + bytes(9),
            )

    async def report_channel_config(self, number: int, func: int, raw: bytes) -> None:
        await self._send(
            C.SUPLA_DS_CALL_SET_CHANNEL_CONFIG,
            encode_channel_config(
                channel_number=number,
                function=func,
                config_type=C.SUPLA_CONFIG_TYPE_DEFAULT,
                config=raw,
            ),
        )

    async def report_device_config(
        self, available: int, fields: int, raw: bytes
    ) -> None:
        await self._send(
            C.SUPLA_DS_CALL_SET_DEVICE_CONFIG,
            encode_device_config(
                available_fields=available, fields=fields, config=raw
            ),
        )

    async def ask_for_channel_config(self, number: int) -> None:
        await self._send(
            C.SUPLA_DS_CALL_GET_CHANNEL_CONFIG,
            bytes([number, C.SUPLA_CONFIG_TYPE_DEFAULT]) + struct.pack("<I", 0),
        )


@pytest.fixture
async def device(port: int):
    """A configurable device with a shutter, a door sensor and a timer."""
    fake = ConfigurableDevice()
    await fake.connect(
        port,
        channels=[
            (number, type_, function, value)
            for number, type_, function, value in (SHUTTER, DOOR, STAIRCASE)
        ],
    )
    yield fake
    await fake.close()


async def _connect_with_flags(port: int, flags: int) -> ConfigurableDevice:
    """Registration payloads carry per-channel flags; patch them in."""
    import fake_device as fd

    original = fd.register_payload

    def patched(channels=None, **kwargs):
        raw = bytearray(original(channels, **kwargs))
        # Channel entries start after the fixed header; each is 21 bytes with
        # Flags as the last int before the 8 value bytes.
        head = (
            C.SUPLA_EMAIL_MAXSIZE
            + 16
            + 16
            + C.SUPLA_DEVICE_NAME_MAXSIZE
            + C.SUPLA_SOFTVER_MAXSIZE
            + C.SUPLA_SERVER_NAME_MAXSIZE
            + 8
            + 1
        )
        count = raw[head - 1]
        for index in range(count):
            at = head + index * 25 + 1 + 12
            struct.pack_into("<i", raw, at, flags)
        return bytes(raw)

    fd.register_payload = patched
    try:
        fake = ConfigurableDevice()
        await fake.connect(
            port, channels=[SHUTTER, DOOR, STAIRCASE]
        )
        return fake
    finally:
        fd.register_payload = original


# --- which entities appear -------------------------------------------------


async def test_no_settings_appear_until_a_device_offers_them(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    """Neither flag nor reported config, so nothing is configurable."""
    registry = er.async_get(hass)
    await wait_for(
        lambda: registry.async_get_entity_id("cover", DOMAIN, f"{GUID_HEX}-0")
    )
    assert (
        registry.async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is None
    )


async def test_reporting_a_config_makes_the_settings_appear(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    registry = er.async_get(hass)
    raw = cfg.ROLLER_SHUTTER.with_field(None, "opening_time", 9_500)
    await device.report_channel_config(0, SHUTTER[2], raw)

    await wait_for(
        lambda: registry.async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is not None
    )
    entity_id = entity_id_for(hass, "number", "0-config-opening_time")
    assert float(hass.states.get(entity_id).state) == 9.5
    assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "s"


async def test_the_runtime_flag_alone_is_enough(hass: HomeAssistant, port: int) -> None:
    registry = er.async_get(hass)
    fake = await _connect_with_flags(port, CONFIGURABLE)
    try:
        await wait_for(
            lambda: registry.async_get_entity_id(
                "number", DOMAIN, f"{GUID_HEX}-2-config-time"
            )
            is not None
        )
        # Nothing reported yet, so the value is unknown rather than a made-up 0.
        assert (
            hass.states.get(entity_id_for(hass, "number", "2-config-time")).state
            == STATE_UNKNOWN
        )
    finally:
        await fake.close()


async def test_each_channel_offers_only_its_own_settings(
    hass: HomeAssistant, port: int
) -> None:
    registry = er.async_get(hass)
    fake = await _connect_with_flags(port, CONFIGURABLE)
    try:
        await wait_for(
            lambda: registry.async_get_entity_id(
                "switch", DOMAIN, f"{GUID_HEX}-1-config-inverted_logic"
            )
            is not None
        )
        # A door sensor has no travel times, a shutter has no inverted logic.
        assert (
            registry.async_get_entity_id(
                "number", DOMAIN, f"{GUID_HEX}-1-config-opening_time"
            )
            is None
        )
        assert (
            registry.async_get_entity_id(
                "switch", DOMAIN, f"{GUID_HEX}-0-config-inverted_logic"
            )
            is None
        )
        assert entity_id_for(hass, "number", "1-config-filtering_time")
    finally:
        await fake.close()


# --- writing ---------------------------------------------------------------


async def test_setting_a_number_reaches_the_device(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    await device.report_channel_config(0, SHUTTER[2], bytes(cfg.ROLLER_SHUTTER.size))
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is not None
    )
    entity_id = entity_id_for(hass, "number", "0-config-opening_time")

    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: entity_id, "value": 12.5}, blocking=True
    )

    number, func, config_type, raw = device.channel_configs[0]
    assert (number, func, config_type) == (0, SHUTTER[2], C.SUPLA_CONFIG_TYPE_DEFAULT)
    # Presented in seconds, carried in milliseconds.
    assert cfg.ROLLER_SHUTTER.decode(raw)["opening_time"] == 12_500
    assert float(hass.states.get(entity_id).state) == 12.5


async def test_a_write_keeps_the_bytes_it_does_not_own(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    reported = bytes(range(cfg.ROLLER_SHUTTER.size))
    await device.report_channel_config(0, SHUTTER[2], reported)
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is not None
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id_for(hass, "number", "0-config-opening_time"), "value": 5},
        blocking=True,
    )

    _n, _f, _t, raw = device.channel_configs[0]
    assert raw[:4] == reported[:4]
    assert raw[8:] == reported[8:]


async def test_a_tri_state_switch_reports_unknown_before_it_is_set(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    await device.report_channel_config(0, SHUTTER[2], bytes(cfg.ROLLER_SHUTTER.size))
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "switch", DOMAIN, f"{GUID_HEX}-0-config-motor_upside_down"
        )
        is not None
    )
    entity_id = entity_id_for(hass, "switch", "0-config-motor_upside_down")
    assert hass.states.get(entity_id).state == STATE_UNKNOWN

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    _n, _f, _t, raw = device.channel_configs[0]
    # SUPLA writes 2 for true, keeping 0 free to mean "no opinion".
    assert cfg.ROLLER_SHUTTER.decode(raw)["motor_upside_down"] == 2
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert cfg.ROLLER_SHUTTER.decode(device.channel_configs[1][3])["motor_upside_down"] == 1


async def test_a_plain_switch_uses_zero_and_one(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    await device.report_channel_config(1, DOOR[2], bytes(cfg.BINARY_SENSOR.size))
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "switch", DOMAIN, f"{GUID_HEX}-1-config-inverted_logic"
        )
        is not None
    )
    entity_id = entity_id_for(hass, "switch", "1-config-inverted_logic")
    assert hass.states.get(entity_id).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert cfg.BINARY_SENSOR.decode(device.channel_configs[0][3])["inverted_logic"] == 1


async def test_a_refused_write_surfaces_the_reason(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    await device.report_channel_config(0, SHUTTER[2], bytes(cfg.ROLLER_SHUTTER.size))
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is not None
    )
    device.accept = C.SUPLA_CONFIG_RESULT_LOCAL_CONFIG_DISABLED

    with pytest.raises(HomeAssistantError, match="local configuration disabled"):
        await hass.services.async_call(
            "number",
            "set_value",
            {
                ATTR_ENTITY_ID: entity_id_for(hass, "number", "0-config-opening_time"),
                "value": 5,
            },
            blocking=True,
        )


# --- device-level settings -------------------------------------------------


async def test_device_settings_appear_from_the_availability_mask(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    registry = er.async_get(hass)
    available = cfg.FIELD_STATUS_LED | cfg.FIELD_SCREEN_BRIGHTNESS
    await device.report_device_config(
        available, cfg.FIELD_STATUS_LED, bytes([cfg.STATUS_LED_ALWAYS_OFF])
    )

    await wait_for(
        lambda: registry.async_get_entity_id(
            "select", DOMAIN, f"{GUID_HEX}-config-status_led-status_led_type"
        )
        is not None
    )
    assert entity_id_for(hass, "number", "config-screen_brightness-screen_brightness")
    assert entity_id_for(hass, "switch", "config-screen_brightness-automatic")
    # Not offered by this device.
    assert (
        registry.async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-config-button_volume-volume"
        )
        is None
    )

    status_led = entity_id_for(hass, "select", "config-status_led-status_led_type")
    state = hass.states.get(status_led)
    assert state.state == "Always off"
    assert state.attributes["options"] == [
        "On when connected",
        "Off when connected",
        "Always off",
    ]


async def test_changing_a_device_setting_reaches_the_device(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    available = cfg.FIELD_STATUS_LED | cfg.FIELD_SCREEN_BRIGHTNESS
    await device.report_device_config(
        available, cfg.FIELD_STATUS_LED, bytes([cfg.STATUS_LED_ALWAYS_OFF])
    )
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "select", DOMAIN, f"{GUID_HEX}-config-status_led-status_led_type"
        )
        is not None
    )

    await hass.services.async_call(
        "select",
        "select_option",
        {
            ATTR_ENTITY_ID: entity_id_for(
                hass, "select", "config-status_led-status_led_type"
            ),
            "option": "On when connected",
        },
        blocking=True,
    )
    sent_available, sent_fields, raw = device.device_configs[0]
    assert sent_available == available
    assert raw[0] == cfg.STATUS_LED_ON_WHEN_CONNECTED

    # A setting the device never reported is inserted at its proper offset.
    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: entity_id_for(
                hass, "number", "config-screen_brightness-screen_brightness"
            ),
            "value": 80,
        },
        blocking=True,
    )
    _available, fields, raw = device.device_configs[1]
    assert fields == available
    assert raw == bytes([cfg.STATUS_LED_ON_WHEN_CONNECTED, 80, 0, 0])


# --- persistence -----------------------------------------------------------


async def test_a_device_asking_for_its_config_gets_what_we_hold(
    hass: HomeAssistant, device: ConfigurableDevice
) -> None:
    """In SUPLA the server owns configuration and answers when a device asks."""
    await device.report_channel_config(0, SHUTTER[2], bytes(cfg.ROLLER_SHUTTER.size))
    await wait_for(
        lambda: er.async_get(hass).async_get_entity_id(
            "number", DOMAIN, f"{GUID_HEX}-0-config-opening_time"
        )
        is not None
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: entity_id_for(hass, "number", "0-config-opening_time"),
            "value": 7,
        },
        blocking=True,
    )

    await device.ask_for_channel_config(0)
    await wait_for(lambda: bool(device.served_configs))

    number, func, config_type, raw = device.served_configs[0]
    assert (number, func, config_type) == (0, SHUTTER[2], C.SUPLA_CONFIG_TYPE_DEFAULT)
    assert cfg.ROLLER_SHUTTER.decode(raw)["opening_time"] == 7_000


@pytest.fixture
def stored_shutter_config(hass_storage: dict) -> None:
    """A device remembered from a previous run, configuration included."""
    config = cfg.ROLLER_SHUTTER.with_field(None, "closing_time", 6_250)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "devices": {
                GUID_HEX: {
                    "guid": GUID_HEX,
                    "name": "Fake Device",
                    "channels": [
                        {
                            "number": 0,
                            "type": SHUTTER[1],
                            "function": SHUTTER[2],
                            "config": config.hex(),
                        }
                    ],
                    "sub_devices": [],
                }
            }
        },
    }


async def test_stored_configuration_brings_back_its_entities(
    hass: HomeAssistant, stored_shutter_config: None, port: int
) -> None:
    """Reported configuration alone proves a channel is configurable."""
    entity_id = entity_id_for(hass, "number", "0-config-closing_time")
    # Unavailable until the device reconnects, but the entity is already there.
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    fake = ConfigurableDevice()
    await fake.connect(port, channels=[SHUTTER, DOOR, STAIRCASE])
    try:
        await wait_for(lambda: hass.states.get(entity_id).state != STATE_UNAVAILABLE)
        assert float(hass.states.get(entity_id).state) == 6.25
    finally:
        await fake.close()
