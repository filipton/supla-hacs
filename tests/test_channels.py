"""Value decoding and command encoding for the supported channel types."""

from __future__ import annotations

import struct

import pytest

from supla_server import channels, consts as C


def test_kind_classification_prefers_function() -> None:
    assert (
        channels.channel_kind(C.SUPLA_CHANNELFNC_LIGHTSWITCH, C.SUPLA_CHANNELTYPE_RELAY)
        == channels.KIND_RELAY
    )
    assert (
        channels.channel_kind(C.SUPLA_CHANNELFNC_CURTAIN, C.SUPLA_CHANNELTYPE_RELAY)
        == channels.KIND_ROLLER_SHUTTER
    )
    # Function 0 (not configured yet) falls back to the hardware type.
    assert (
        channels.channel_kind(0, C.SUPLA_CHANNELTYPE_THERMOMETER)
        == channels.KIND_THERMOMETER
    )
    assert channels.channel_kind(0, 123456) == channels.KIND_UNKNOWN


def test_relay_decode_and_encode() -> None:
    decoded = channels.decode_value(channels.KIND_RELAY, bytes([1, 0, 0, 0, 0, 0, 0, 0]))
    assert decoded["on"] is True

    on = channels.encode_command(channels.KIND_RELAY, {"action": "on"})
    assert on == bytes([1, 0, 0, 0, 0, 0, 0, 0])

    toggled = channels.encode_command(channels.KIND_RELAY, {"action": "toggle"}, decoded)
    assert toggled[0] == 0


def test_thermometer_and_humidity_decoding() -> None:
    temp = channels.decode_value(channels.KIND_THERMOMETER, struct.pack("<d", 21.75))
    assert temp["temperature"] == 21.75

    raw = struct.pack("<ii", 22500, 48200)
    both = channels.decode_value(channels.KIND_TEMP_HUMIDITY, raw)
    assert both["temperature"] == 22.5
    assert both["humidity"] == 48.2

    only_humidity = channels.decode_value(channels.KIND_HUMIDITY, raw)
    assert only_humidity["humidity"] == 48.2


def test_roller_shutter_position_command() -> None:
    raw = struct.pack("<bbbhbbb", 40, 0, 100, 0, 0, 0, 0)[:8].ljust(8, b"\x00")
    decoded = channels.decode_value(channels.KIND_ROLLER_SHUTTER, raw)
    assert decoded["position"] == 40

    assert channels.encode_command(channels.KIND_ROLLER_SHUTTER, {"action": "open"})[0] == 2
    assert channels.encode_command(channels.KIND_ROLLER_SHUTTER, {"action": "close"})[0] == 1
    assert channels.encode_command(channels.KIND_ROLLER_SHUTTER, {"action": "stop"})[0] == 0
    # Target positions are offset by 10 on the wire.
    value = channels.encode_command(
        channels.KIND_ROLLER_SHUTTER, {"action": "position", "position": 75}
    )
    assert value[0] == 85


def test_facade_blind_tilt_only_leaves_position_unset() -> None:
    value = channels.encode_command(
        channels.KIND_FACADE_BLIND, {"action": "tilt", "tilt": 30}
    )
    position, tilt = struct.unpack_from("<bb", value)
    assert position == -1
    assert tilt == 40


def test_rgb_color_encoding_round_trips() -> None:
    value = channels.encode_command(
        channels.KIND_RGB, {"action": "color", "color": "#112233"}
    )
    decoded = channels.decode_value(channels.KIND_RGB, value)
    assert decoded["color"] == "#112233"
    assert decoded["color_brightness"] == 100
    assert decoded["command"] == C.RGBW_COMMAND_TURN_ON_RGB


def test_dimmer_brightness_encoding() -> None:
    value = channels.encode_command(
        channels.KIND_DIMMER, {"action": "brightness", "brightness": 42}
    )
    assert value[0] == 42
    assert value[6] == C.RGBW_COMMAND_TURN_ON_DIMMER
    assert channels.decode_value(channels.KIND_DIMMER, value)["brightness"] == 42


def test_hvac_decode_and_setpoint_command() -> None:
    flags = (
        C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET | C.SUPLA_HVAC_VALUE_FLAG_HEATING
    )
    raw = struct.pack("<BBhhH", 1, C.SUPLA_HVAC_MODE_HEAT, 2150, 0, flags)
    decoded = channels.decode_value(channels.KIND_HVAC, raw)
    assert decoded["mode"] == "HEAT"
    assert decoded["setpoint_heat"] == 21.5
    assert decoded["heating"] is True

    value = channels.encode_command(
        channels.KIND_HVAC, {"action": "heat", "setpoint_heat": 23.0}
    )
    is_on, mode, heat, _cool, out_flags = struct.unpack("<BBhhH", value)
    assert (is_on, mode, heat) == (1, C.SUPLA_HVAC_MODE_HEAT, 2300)
    assert out_flags & C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET


def test_meter_and_container_decoding() -> None:
    em = channels.decode_value(
        channels.KIND_ELECTRICITY_METER, bytes([0]) + struct.pack("<I", 12345) + bytes(3)
    )
    assert em["total_forward_active_energy_kwh"] == 123.45

    ic = channels.decode_value(channels.KIND_IMPULSE_COUNTER, struct.pack("<Q", 987654))
    assert ic["counter"] == 987654

    container = channels.decode_value(
        channels.KIND_CONTAINER, bytes([61]) + struct.pack("<H", 1) + bytes(5)
    )
    assert container["level"] == 60


def test_valve_and_digiglass_commands() -> None:
    assert channels.encode_command(channels.KIND_VALVE_OPEN_CLOSE, {"action": "close"})[0] == 1
    assert (
        channels.encode_command(
            channels.KIND_VALVE_PERCENTAGE, {"action": "position", "position": 30}
        )[0]
        == 30
    )
    mask, active = struct.unpack_from(
        "<HH", channels.encode_command(channels.KIND_DIGIGLASS, {"action": "on"})
    )
    assert (mask, active) == (0xFFFF, 0xFFFF)


def test_read_only_kinds_reject_commands() -> None:
    with pytest.raises(channels.UnsupportedCommand):
        channels.encode_command(channels.KIND_THERMOMETER, {"action": "on"})
    with pytest.raises(channels.UnsupportedCommand):
        channels.encode_command(channels.KIND_BINARY_SENSOR, {"action": "on"})


def test_normalize_shorthand_commands() -> None:
    assert channels.normalize_command({"on": True})["action"] == "on"
    assert channels.normalize_command({"brightness": 10})["action"] == "brightness"
    assert channels.normalize_command({"position": 10})["action"] == "position"
    with pytest.raises(channels.UnsupportedCommand):
        channels.normalize_command({})


def test_every_function_maps_to_a_kind() -> None:
    unmapped = [
        name
        for function, name in C.CHANNEL_FUNCTION_NAMES.items()
        if function != C.SUPLA_CHANNELFNC_NONE
        and channels.channel_kind(function, 0) == channels.KIND_UNKNOWN
    ]
    assert unmapped == []
