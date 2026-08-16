"""Per-channel value decoding and command encoding for all SUPLA channel types."""

from __future__ import annotations

import struct
from typing import Any

from . import consts as C

VALUE_SIZE = C.SUPLA_CHANNELVALUE_SIZE


class UnsupportedCommand(ValueError):
    """Channel kind cannot handle the requested command."""


# Channel "kind" groups channel functions that share a value layout and controls.
KIND_RELAY = "relay"
KIND_ROLLER_SHUTTER = "roller_shutter"
KIND_FACADE_BLIND = "facade_blind"
KIND_DIMMER = "dimmer"
KIND_RGB = "rgb"
KIND_DIMMER_RGB = "dimmer_rgb"
KIND_THERMOMETER = "thermometer"
KIND_HUMIDITY = "humidity"
KIND_TEMP_HUMIDITY = "temperature_humidity"
KIND_MEASUREMENT = "measurement"
KIND_BINARY_SENSOR = "binary_sensor"
KIND_ELECTRICITY_METER = "electricity_meter"
KIND_IMPULSE_COUNTER = "impulse_counter"
KIND_VALVE_OPEN_CLOSE = "valve_open_close"
KIND_VALVE_PERCENTAGE = "valve_percentage"
KIND_HVAC = "hvac"
KIND_THERMOSTAT_HEATPOL = "thermostat_heatpol"
KIND_DIGIGLASS = "digiglass"
KIND_CONTAINER = "container"
KIND_ENGINE_SPEED = "engine_speed"
KIND_ACTION_TRIGGER = "action_trigger"
KIND_UNKNOWN = "unknown"

_RELAY_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK,
    C.SUPLA_CHANNELFNC_POWERSWITCH,
    C.SUPLA_CHANNELFNC_LIGHTSWITCH,
    C.SUPLA_CHANNELFNC_RING,
    C.SUPLA_CHANNELFNC_ALARM,
    C.SUPLA_CHANNELFNC_NOTIFICATION,
    C.SUPLA_CHANNELFNC_STAIRCASETIMER,
    C.SUPLA_CHANNELFNC_PUMPSWITCH,
    C.SUPLA_CHANNELFNC_HEATORCOLDSOURCESWITCH,
}

_ROLLER_SHUTTER_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROOFWINDOW,
    C.SUPLA_CHANNELFNC_TERRACE_AWNING,
    C.SUPLA_CHANNELFNC_PROJECTOR_SCREEN,
    C.SUPLA_CHANNELFNC_CURTAIN,
    C.SUPLA_CHANNELFNC_ROLLER_GARAGE_DOOR,
}

_FACADE_BLIND_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEFACADEBLIND,
    C.SUPLA_CHANNELFNC_VERTICAL_BLIND,
}

_BINARY_SENSOR_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATEWAY,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GARAGEDOOR,
    C.SUPLA_CHANNELFNC_NOLIQUIDSENSOR,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROLLERSHUTTER,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROOFWINDOW,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_WINDOW,
    C.SUPLA_CHANNELFNC_HOTELCARDSENSOR,
    C.SUPLA_CHANNELFNC_ALARMARMAMENTSENSOR,
    C.SUPLA_CHANNELFNC_MAILSENSOR,
    C.SUPLA_CHANNELFNC_CONTAINER_LEVEL_SENSOR,
    C.SUPLA_CHANNELFNC_FLOOD_SENSOR,
    C.SUPLA_CHANNELFNC_MOTION_SENSOR,
    C.SUPLA_CHANNELFNC_BINARY_SENSOR,
}

_MEASUREMENT_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_DEPTHSENSOR: ("depth", "m"),
    C.SUPLA_CHANNELFNC_DISTANCESENSOR: ("distance", "m"),
    C.SUPLA_CHANNELFNC_WINDSENSOR: ("wind", "m/s"),
    C.SUPLA_CHANNELFNC_PRESSURESENSOR: ("pressure", "hPa"),
    C.SUPLA_CHANNELFNC_RAINSENSOR: ("rain", "mm"),
    C.SUPLA_CHANNELFNC_WEIGHTSENSOR: ("weight", "kg"),
    C.SUPLA_CHANNELFNC_GENERAL_PURPOSE_MEASUREMENT: ("measurement", ""),
    C.SUPLA_CHANNELFNC_GENERAL_PURPOSE_METER: ("meter", ""),
}

_IMPULSE_COUNTER_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_IC_ELECTRICITY_METER,
    C.SUPLA_CHANNELFNC_IC_GAS_METER,
    C.SUPLA_CHANNELFNC_IC_WATER_METER,
    C.SUPLA_CHANNELFNC_IC_HEAT_METER,
    C.SUPLA_CHANNELFNC_IC_EVENTS,
    C.SUPLA_CHANNELFNC_IC_SECONDS,
}

_HVAC_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT,
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_HEAT_COOL,
    C.SUPLA_CHANNELFNC_HVAC_DRYER,
    C.SUPLA_CHANNELFNC_HVAC_FAN,
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_DIFFERENTIAL,
    C.SUPLA_CHANNELFNC_HVAC_DOMESTIC_HOT_WATER,
    C.SUPLA_CHANNELFNC_HVAC_HRV,
}

_CONTAINER_FUNCTIONS = {
    C.SUPLA_CHANNELFNC_CONTAINER,
    C.SUPLA_CHANNELFNC_SEPTIC_TANK,
    C.SUPLA_CHANNELFNC_WATER_TANK,
}

_TYPE_FALLBACK_KINDS = {
    C.SUPLA_CHANNELTYPE_RELAY: KIND_RELAY,
    C.SUPLA_CHANNELTYPE_RELAYHFD4: KIND_RELAY,
    C.SUPLA_CHANNELTYPE_RELAYG5LA1A: KIND_RELAY,
    C.SUPLA_CHANNELTYPE_2XRELAYG5LA1A: KIND_RELAY,
    C.SUPLA_CHANNELTYPE_BINARYSENSOR: KIND_BINARY_SENSOR,
    C.SUPLA_CHANNELTYPE_SENSORNC: KIND_BINARY_SENSOR,
    C.SUPLA_CHANNELTYPE_CALLBUTTON: KIND_BINARY_SENSOR,
    C.SUPLA_CHANNELTYPE_DISTANCESENSOR: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_THERMOMETER: KIND_THERMOMETER,
    C.SUPLA_CHANNELTYPE_THERMOMETERDS18B20: KIND_THERMOMETER,
    C.SUPLA_CHANNELTYPE_HUMIDITYSENSOR: KIND_HUMIDITY,
    C.SUPLA_CHANNELTYPE_HUMIDITYANDTEMPSENSOR: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_DHT11: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_DHT22: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_DHT21: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_AM2302: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_AM2301: KIND_TEMP_HUMIDITY,
    C.SUPLA_CHANNELTYPE_WINDSENSOR: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_PRESSURESENSOR: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_RAINSENSOR: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_WEIGHTSENSOR: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_GENERAL_PURPOSE_MEASUREMENT: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_GENERAL_PURPOSE_METER: KIND_MEASUREMENT,
    C.SUPLA_CHANNELTYPE_CONTAINER: KIND_CONTAINER,
    C.SUPLA_CHANNELTYPE_DIMMER: KIND_DIMMER,
    C.SUPLA_CHANNELTYPE_RGBLEDCONTROLLER: KIND_RGB,
    C.SUPLA_CHANNELTYPE_DIMMERANDRGBLED: KIND_DIMMER_RGB,
    C.SUPLA_CHANNELTYPE_ELECTRICITY_METER: KIND_ELECTRICITY_METER,
    C.SUPLA_CHANNELTYPE_IMPULSE_COUNTER: KIND_IMPULSE_COUNTER,
    C.SUPLA_CHANNELTYPE_HVAC: KIND_HVAC,
    C.SUPLA_CHANNELTYPE_THERMOSTAT: KIND_THERMOSTAT_HEATPOL,
    C.SUPLA_CHANNELTYPE_THERMOSTAT_HEATPOL_HOMEPLUS: KIND_THERMOSTAT_HEATPOL,
    C.SUPLA_CHANNELTYPE_VALVE_OPENCLOSE: KIND_VALVE_OPEN_CLOSE,
    C.SUPLA_CHANNELTYPE_VALVE_PERCENTAGE: KIND_VALVE_PERCENTAGE,
    C.SUPLA_CHANNELTYPE_ENGINE: KIND_ENGINE_SPEED,
    C.SUPLA_CHANNELTYPE_ACTIONTRIGGER: KIND_ACTION_TRIGGER,
    C.SUPLA_CHANNELTYPE_DIGIGLASS: KIND_DIGIGLASS,
}

_FUNCTION_KINDS: dict[int, str] = {}
for _fn in _RELAY_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_RELAY
for _fn in _ROLLER_SHUTTER_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_ROLLER_SHUTTER
for _fn in _FACADE_BLIND_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_FACADE_BLIND
for _fn in _BINARY_SENSOR_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_BINARY_SENSOR
for _fn in _MEASUREMENT_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_MEASUREMENT
for _fn in _IMPULSE_COUNTER_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_IMPULSE_COUNTER
for _fn in _HVAC_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_HVAC
for _fn in _CONTAINER_FUNCTIONS:
    _FUNCTION_KINDS[_fn] = KIND_CONTAINER
_FUNCTION_KINDS.update(
    {
        C.SUPLA_CHANNELFNC_THERMOMETER: KIND_THERMOMETER,
        C.SUPLA_CHANNELFNC_HUMIDITY: KIND_HUMIDITY,
        C.SUPLA_CHANNELFNC_HUMIDITYANDTEMPERATURE: KIND_TEMP_HUMIDITY,
        C.SUPLA_CHANNELFNC_WEATHER_STATION: KIND_MEASUREMENT,
        C.SUPLA_CHANNELFNC_DIMMER: KIND_DIMMER,
        C.SUPLA_CHANNELFNC_DIMMER_CCT: KIND_DIMMER,
        C.SUPLA_CHANNELFNC_RGBLIGHTING: KIND_RGB,
        C.SUPLA_CHANNELFNC_DIMMERANDRGBLIGHTING: KIND_DIMMER_RGB,
        C.SUPLA_CHANNELFNC_DIMMER_CCT_AND_RGB: KIND_DIMMER_RGB,
        C.SUPLA_CHANNELFNC_ELECTRICITY_METER: KIND_ELECTRICITY_METER,
        C.SUPLA_CHANNELFNC_THERMOSTAT_HEATPOL_HOMEPLUS: KIND_THERMOSTAT_HEATPOL,
        C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE: KIND_VALVE_OPEN_CLOSE,
        C.SUPLA_CHANNELFNC_VALVE_PERCENTAGE: KIND_VALVE_PERCENTAGE,
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEENGINESPEED: KIND_ENGINE_SPEED,
        C.SUPLA_CHANNELFNC_ACTIONTRIGGER: KIND_ACTION_TRIGGER,
        C.SUPLA_CHANNELFNC_DIGIGLASS_HORIZONTAL: KIND_DIGIGLASS,
        C.SUPLA_CHANNELFNC_DIGIGLASS_VERTICAL: KIND_DIGIGLASS,
    }
)

# Actions the web panel / API may send, per kind.
_KIND_ACTIONS: dict[str, list[str]] = {
    KIND_RELAY: ["on", "off", "toggle"],
    KIND_ROLLER_SHUTTER: ["open", "close", "stop", "step", "position"],
    KIND_FACADE_BLIND: ["open", "close", "stop", "step", "position", "tilt"],
    KIND_DIMMER: ["on", "off", "brightness"],
    KIND_RGB: ["on", "off", "color", "color_brightness"],
    KIND_DIMMER_RGB: ["on", "off", "brightness", "color", "color_brightness"],
    KIND_VALVE_OPEN_CLOSE: ["open", "close"],
    KIND_VALVE_PERCENTAGE: ["open", "close", "position"],
    KIND_HVAC: [
        "off",
        "heat",
        "cool",
        "auto",
        "setpoint",
        "weekly_schedule",
        "manual",
        "turn_on",
    ],
    KIND_THERMOSTAT_HEATPOL: ["on", "off", "setpoint"],
    KIND_DIGIGLASS: ["on", "off", "mask"],
    KIND_ENGINE_SPEED: ["speed"],
}


def channel_kind(function: int, channel_type: int) -> str:
    """Classify a channel by its function, falling back to its hardware type."""
    kind = _FUNCTION_KINDS.get(function)
    if kind is not None:
        return kind
    return _TYPE_FALLBACK_KINDS.get(channel_type, KIND_UNKNOWN)


def function_name(function: int) -> str:
    return C.CHANNEL_FUNCTION_NAMES.get(function, f"UNKNOWN_{function}")


def type_name(channel_type: int) -> str:
    return C.CHANNEL_TYPE_NAMES.get(channel_type, f"UNKNOWN_{channel_type}")


def actions_for(kind: str) -> list[str]:
    return list(_KIND_ACTIONS.get(kind, []))


def is_controllable(kind: str) -> bool:
    return kind in _KIND_ACTIONS


def _pad(value: bytes) -> bytes:
    return value.ljust(VALUE_SIZE, b"\x00")[:VALUE_SIZE]


def _u8(raw: bytes, index: int) -> int:
    return raw[index] if len(raw) > index else 0


def _i8(raw: bytes, index: int) -> int:
    value = _u8(raw, index)
    return value - 256 if value > 127 else value


def decode_value(kind: str, raw: bytes) -> dict[str, Any]:
    """Decode an 8-byte channel value into a JSON-friendly dict."""
    raw = _pad(bytes(raw))
    decoded: dict[str, Any] = {"raw": raw.hex()}

    if kind == KIND_RELAY:
        # TRelayChannel_Value: hi(1) flags(uint16) RelayMode(1)
        decoded["on"] = _u8(raw, 0) > 0
        decoded["flags"] = struct.unpack_from("<H", raw, 1)[0]
    elif kind == KIND_BINARY_SENSOR:
        decoded["on"] = _u8(raw, 0) > 0
    elif kind == KIND_ROLLER_SHUTTER:
        # TDSC_RollerShutterValue
        position = _i8(raw, 0)
        decoded["position"] = position
        decoded["calibrating"] = position == -1
        decoded["bottom_position"] = _i8(raw, 2)
        decoded["flags"] = struct.unpack_from("<h", raw, 3)[0]
    elif kind == KIND_FACADE_BLIND:
        # TDSC_FacadeBlindValue
        decoded["position"] = _i8(raw, 0)
        decoded["tilt"] = _i8(raw, 1)
        decoded["flags"] = struct.unpack_from("<h", raw, 3)[0]
    elif kind == KIND_DIMMER:
        brightness = _u8(raw, 0)
        decoded["brightness"] = brightness if 0 <= brightness <= 100 else 0
        decoded["on"] = decoded["brightness"] > 0
    elif kind in (KIND_RGB, KIND_DIMMER_RGB):
        decoded.update(_decode_rgbw(raw))
    elif kind == KIND_THERMOMETER:
        decoded["temperature"] = _round(struct.unpack_from("<d", raw, 0)[0])
    elif kind == KIND_HUMIDITY:
        humidity = struct.unpack_from("<i", raw, 4)[0]
        decoded["humidity"] = _round(humidity / 1000.0)
    elif kind == KIND_TEMP_HUMIDITY:
        temperature, humidity = struct.unpack_from("<ii", raw, 0)
        decoded["temperature"] = _round(temperature / 1000.0)
        decoded["humidity"] = _round(humidity / 1000.0)
    elif kind == KIND_MEASUREMENT:
        decoded["value"] = _round(struct.unpack_from("<d", raw, 0)[0])
    elif kind == KIND_ELECTRICITY_METER:
        # TElectricityMeter_Value: flags(1) + total_forward_active_energy(uint32) * 0.01 kWh
        decoded["flags"] = _u8(raw, 0)
        total = struct.unpack_from("<I", raw, 1)[0]
        decoded["total_forward_active_energy_kwh"] = _round(total / 100.0)
    elif kind == KIND_IMPULSE_COUNTER:
        decoded["counter"] = struct.unpack_from("<Q", raw, 0)[0]
    elif kind == KIND_VALVE_OPEN_CLOSE:
        decoded["closed"] = _u8(raw, 0) > 0
        decoded["open"] = not decoded["closed"]
        decoded["flags"] = _u8(raw, 1)
    elif kind == KIND_VALVE_PERCENTAGE:
        decoded["closed_percent"] = _u8(raw, 0)
        decoded["flags"] = _u8(raw, 1)
    elif kind == KIND_HVAC:
        decoded.update(_decode_hvac(raw))
    elif kind == KIND_THERMOSTAT_HEATPOL:
        # TThermostat_Value
        decoded["on"] = _u8(raw, 0) > 0
        decoded["flags"] = _u8(raw, 1)
        measured, preset = struct.unpack_from("<hh", raw, 2)
        decoded["measured_temperature"] = _round(measured / 100.0)
        decoded["preset_temperature"] = _round(preset / 100.0)
    elif kind == KIND_DIGIGLASS:
        # TDigiglass_Value: flags(1) sectionCount(1) mask(uint16)
        decoded["flags"] = _u8(raw, 0)
        decoded["section_count"] = _u8(raw, 1)
        decoded["mask"] = struct.unpack_from("<H", raw, 2)[0]
    elif kind == KIND_CONTAINER:
        # TContainerChannel_Value: level(1) flags(uint16); level 0 unknown, 1-101 => 0-100%
        level = _u8(raw, 0)
        decoded["level"] = level - 1 if level > 0 else None
        decoded["flags"] = struct.unpack_from("<H", raw, 1)[0]
    elif kind == KIND_ENGINE_SPEED:
        decoded["speed"] = _u8(raw, 0)
    elif kind == KIND_ACTION_TRIGGER:
        decoded["actions"] = struct.unpack_from("<I", raw, 0)[0]
    else:
        decoded["byte0"] = _u8(raw, 0)

    return decoded


def _round(value: float) -> float:
    return round(value, 4)


def _decode_rgbw(raw: bytes) -> dict[str, Any]:
    brightness, color_brightness, blue, green, red, on_off, command, white_temp = struct.unpack(
        "<BBBBBbbB", raw
    )
    return {
        "brightness": brightness,
        "color_brightness": color_brightness,
        "color": f"#{red:02x}{green:02x}{blue:02x}",
        "red": red,
        "green": green,
        "blue": blue,
        "on": brightness > 0 or color_brightness > 0,
        "on_off": on_off,
        "command": command,
        "white_temperature": white_temp,
    }


def _decode_hvac(raw: bytes) -> dict[str, Any]:
    is_on, mode, setpoint_heat, setpoint_cool, flags = struct.unpack("<BBhhH", raw)
    result: dict[str, Any] = {
        "is_on": is_on,
        "on": is_on > 0,
        "mode": C.HVAC_MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
        "mode_id": mode,
        "flags": flags,
        "heating": bool(flags & C.SUPLA_HVAC_VALUE_FLAG_HEATING),
        "cooling": bool(flags & C.SUPLA_HVAC_VALUE_FLAG_COOLING),
        "weekly_schedule": bool(flags & C.SUPLA_HVAC_VALUE_FLAG_WEEKLY_SCHEDULE),
    }
    if flags & C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET:
        result["setpoint_heat"] = _round(setpoint_heat / 100.0)
    if flags & C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_COOL_SET:
        result["setpoint_cool"] = _round(setpoint_cool / 100.0)
    if is_on > 1:
        # 2..102 encodes 0-100% output level
        result["level"] = is_on - 2
    return result


def encode_command(
    kind: str,
    command: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> bytes:
    """
    Build the 8-byte value for SUPLA_SD_CALL_CHANNEL_SET_VALUE.

    `command` uses an "action" key plus action-specific parameters.
    `current` is the last decoded value, used by actions like toggle.
    """
    action = str(command.get("action", "")).lower()
    current = current or {}

    if kind == KIND_RELAY:
        return _encode_relay(action, current)
    if kind == KIND_ROLLER_SHUTTER:
        return _encode_roller_shutter(action, command)
    if kind == KIND_FACADE_BLIND:
        return _encode_facade_blind(action, command, current)
    if kind in (KIND_DIMMER, KIND_RGB, KIND_DIMMER_RGB):
        return _encode_rgbw(kind, action, command, current)
    if kind == KIND_VALVE_OPEN_CLOSE:
        return _valve_open_close(action)
    if kind == KIND_VALVE_PERCENTAGE:
        return _valve_percentage(action, command)
    if kind == KIND_HVAC:
        return _encode_hvac(action, command)
    if kind == KIND_THERMOSTAT_HEATPOL:
        return _encode_thermostat_heatpol(action, command, current)
    if kind == KIND_DIGIGLASS:
        return _encode_digiglass(action, command)
    if kind == KIND_ENGINE_SPEED:
        return _pad(bytes([_percent(command.get("speed", command.get("value", 0)))]))

    raise UnsupportedCommand(f"channel kind '{kind}' is read-only")


def _percent(value: Any, *, low: int = 0, high: int = 100) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise UnsupportedCommand(f"expected a number, got {value!r}") from exc
    return max(low, min(high, number))


def _encode_relay(action: str, current: dict[str, Any]) -> bytes:
    if action in ("on", "open", "unlock", "turn_on"):
        on = True
    elif action in ("off", "close", "lock", "turn_off"):
        on = False
    elif action == "toggle":
        on = not bool(current.get("on"))
    else:
        raise UnsupportedCommand(f"unsupported relay action '{action}'")
    return _pad(bytes([1 if on else 0]))


def _encode_roller_shutter(action: str, command: dict[str, Any]) -> bytes:
    if action == "open":
        position = C.RS_CMD_UP
    elif action == "close":
        position = C.RS_CMD_DOWN
    elif action == "stop":
        position = C.RS_CMD_STOP
    elif action == "step":
        position = C.RS_CMD_STEP_BY_STEP
    elif action == "position":
        position = _percent(command.get("position")) + C.RS_POSITION_OFFSET
    else:
        raise UnsupportedCommand(f"unsupported roller shutter action '{action}'")
    return _pad(struct.pack("<b", position))


def _encode_facade_blind(
    action: str,
    command: dict[str, Any],
    current: dict[str, Any],
) -> bytes:
    tilt = -1
    if action == "open":
        position = C.RS_CMD_UP
    elif action == "close":
        position = C.RS_CMD_DOWN
    elif action == "stop":
        position = C.RS_CMD_STOP
    elif action == "step":
        position = C.RS_CMD_STEP_BY_STEP
    elif action == "position":
        position = _percent(command.get("position")) + C.RS_POSITION_OFFSET
        if command.get("tilt") is not None:
            tilt = _percent(command.get("tilt")) + C.RS_POSITION_OFFSET
    elif action == "tilt":
        position = -1
        tilt = _percent(command.get("tilt")) + C.RS_POSITION_OFFSET
    else:
        raise UnsupportedCommand(f"unsupported facade blind action '{action}'")
    return _pad(struct.pack("<bb", position, tilt))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise UnsupportedCommand(f"invalid color '{value}', expected #rrggbb")
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError as exc:
        raise UnsupportedCommand(f"invalid color '{value}'") from exc


def _encode_rgbw(
    kind: str,
    action: str,
    command: dict[str, Any],
    current: dict[str, Any],
) -> bytes:
    brightness = int(current.get("brightness", 0) or 0)
    color_brightness = int(current.get("color_brightness", 0) or 0)
    red, green, blue = (
        int(current.get("red", 255) or 0),
        int(current.get("green", 255) or 0),
        int(current.get("blue", 255) or 0),
    )
    white_temp = int(current.get("white_temperature", 0) or 0)
    rgbw_command = C.RGBW_COMMAND_NOT_SET

    if action == "on":
        if kind == KIND_DIMMER:
            brightness = brightness or 100
            rgbw_command = C.RGBW_COMMAND_TURN_ON_DIMMER
        elif kind == KIND_RGB:
            color_brightness = color_brightness or 100
            rgbw_command = C.RGBW_COMMAND_TURN_ON_RGB
        else:
            brightness = brightness or 100
            color_brightness = color_brightness or 100
            rgbw_command = C.RGBW_COMMAND_TURN_ON_ALL
    elif action == "off":
        brightness = 0
        color_brightness = 0
        rgbw_command = {
            KIND_DIMMER: C.RGBW_COMMAND_TURN_OFF_DIMMER,
            KIND_RGB: C.RGBW_COMMAND_TURN_OFF_RGB,
        }.get(kind, C.RGBW_COMMAND_TURN_OFF_ALL)
    elif action == "toggle":
        rgbw_command = {
            KIND_DIMMER: C.RGBW_COMMAND_TOGGLE_DIMMER,
            KIND_RGB: C.RGBW_COMMAND_TOGGLE_RGB,
        }.get(kind, C.RGBW_COMMAND_TOGGLE_ALL)
    elif action == "brightness":
        brightness = _percent(command.get("brightness", command.get("value")))
        rgbw_command = (
            C.RGBW_COMMAND_TURN_ON_DIMMER if brightness > 0 else C.RGBW_COMMAND_TURN_OFF_DIMMER
        )
    elif action == "color_brightness":
        color_brightness = _percent(command.get("color_brightness", command.get("value")))
        rgbw_command = (
            C.RGBW_COMMAND_TURN_ON_RGB if color_brightness > 0 else C.RGBW_COMMAND_TURN_OFF_RGB
        )
    elif action == "color":
        red, green, blue = _hex_to_rgb(str(command.get("color", "")))
        if command.get("color_brightness") is not None:
            color_brightness = _percent(command["color_brightness"])
        elif color_brightness == 0:
            color_brightness = 100
        rgbw_command = C.RGBW_COMMAND_TURN_ON_RGB
    else:
        raise UnsupportedCommand(f"unsupported light action '{action}'")

    if command.get("white_temperature") is not None:
        white_temp = _percent(command["white_temperature"])

    return struct.pack(
        "<BBBBBbbB",
        _percent(brightness),
        _percent(color_brightness),
        blue & 0xFF,
        green & 0xFF,
        red & 0xFF,
        0,
        rgbw_command,
        _percent(white_temp),
    )


def _valve_open_close(action: str) -> bytes:
    if action in ("open", "on"):
        closed = 0
    elif action in ("close", "off"):
        closed = 1
    else:
        raise UnsupportedCommand(f"unsupported valve action '{action}'")
    return _pad(bytes([closed]))


def _valve_percentage(action: str, command: dict[str, Any]) -> bytes:
    if action == "open":
        closed_percent = 0
    elif action == "close":
        closed_percent = 100
    elif action == "position":
        closed_percent = _percent(command.get("position"))
    else:
        raise UnsupportedCommand(f"unsupported valve action '{action}'")
    return _pad(bytes([closed_percent]))


def _encode_hvac(action: str, command: dict[str, Any]) -> bytes:
    flags = 0
    setpoint_heat = 0
    setpoint_cool = 0

    if action == "off":
        mode = C.SUPLA_HVAC_MODE_OFF
    elif action == "heat":
        mode = C.SUPLA_HVAC_MODE_HEAT
    elif action == "cool":
        mode = C.SUPLA_HVAC_MODE_COOL
    elif action == "auto":
        mode = C.SUPLA_HVAC_MODE_HEAT_COOL
    elif action == "turn_on":
        mode = C.SUPLA_HVAC_MODE_CMD_TURN_ON
    elif action == "weekly_schedule":
        mode = C.SUPLA_HVAC_MODE_CMD_WEEKLY_SCHEDULE
    elif action == "manual":
        # Leave the weekly schedule and keep whatever mode is running.
        mode = C.SUPLA_HVAC_MODE_CMD_SWITCH_TO_MANUAL
    elif action == "setpoint":
        mode = C.SUPLA_HVAC_MODE_NOT_SET
    else:
        raise UnsupportedCommand(f"unsupported HVAC action '{action}'")

    if command.get("setpoint_heat") is not None:
        setpoint_heat = int(round(float(command["setpoint_heat"]) * 100))
        flags |= C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET
    if command.get("setpoint_cool") is not None:
        setpoint_cool = int(round(float(command["setpoint_cool"]) * 100))
        flags |= C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_COOL_SET

    if action == "setpoint" and not flags:
        raise UnsupportedCommand("setpoint action needs setpoint_heat or setpoint_cool")

    is_on = 0 if mode == C.SUPLA_HVAC_MODE_OFF else 1
    return struct.pack("<BBhhH", is_on, mode, setpoint_heat, setpoint_cool, flags)


def _encode_thermostat_heatpol(
    action: str,
    command: dict[str, Any],
    current: dict[str, Any],
) -> bytes:
    preset = float(current.get("preset_temperature", 0) or 0)
    if action == "on":
        is_on = 1
    elif action == "off":
        is_on = 0
    elif action == "setpoint":
        is_on = 1
        if command.get("setpoint") is None:
            raise UnsupportedCommand("setpoint action needs a setpoint value")
        preset = float(command["setpoint"])
    else:
        raise UnsupportedCommand(f"unsupported thermostat action '{action}'")
    # TThermostat_Value is 6 bytes; channel values always go out as 8.
    return _pad(struct.pack("<BBhh", is_on, 0, 0, int(round(preset * 100))))


def _encode_digiglass(action: str, command: dict[str, Any]) -> bytes:
    # TCSD_Digiglass_NewValue: mask(uint16) active_bits(uint16)
    if action == "on":
        mask, active = 0xFFFF, 0xFFFF
    elif action == "off":
        mask, active = 0x0000, 0xFFFF
    elif action == "mask":
        mask = int(command.get("mask", 0)) & 0xFFFF
        active = int(command.get("active_bits", 0xFFFF)) & 0xFFFF
    else:
        raise UnsupportedCommand(f"unsupported digiglass action '{action}'")
    return _pad(struct.pack("<HH", mask, active))


def normalize_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept shorthand bodies like {"on": true} or {"brightness": 40}."""
    command = dict(payload)
    if command.get("action"):
        return command

    if "on" in command:
        command["action"] = "on" if command["on"] else "off"
    elif command.get("brightness") is not None:
        command["action"] = "brightness"
    elif command.get("color") is not None:
        command["action"] = "color"
    elif command.get("color_brightness") is not None:
        command["action"] = "color_brightness"
    elif command.get("position") is not None:
        command["action"] = "position"
    elif command.get("tilt") is not None:
        command["action"] = "tilt"
    elif command.get("speed") is not None:
        command["action"] = "speed"
    elif command.get("setpoint_heat") is not None or command.get("setpoint_cool") is not None:
        command["action"] = "setpoint"
    else:
        raise UnsupportedCommand("command needs an 'action' field")
    return command


# TDSC_ChannelState, byte offsets from proto.h under #pragma pack(1).
# ReceiverID and ChannelID are unused when it arrives as an extended value, so
# everything is read by absolute offset rather than sequentially.
_STATE_SIZE = 50
_STATE_FIELDS: tuple[tuple[int, str, int, str], ...] = (
    # (bit, name, offset, struct format)
    (C.SUPLA_CHANNELSTATE_FIELD_BATTERYLEVEL, "battery_level", 26, "<B"),
    (C.SUPLA_CHANNELSTATE_FIELD_BATTERYPOWERED, "battery_powered", 27, "<B"),
    (C.SUPLA_CHANNELSTATE_FIELD_WIFIRSSI, "wifi_rssi", 28, "<b"),
    (C.SUPLA_CHANNELSTATE_FIELD_WIFISIGNALSTRENGTH, "wifi_signal_strength", 29, "<B"),
    (C.SUPLA_CHANNELSTATE_FIELD_BRIDGENODEONLINE, "bridge_node_online", 30, "<B"),
    (
        C.SUPLA_CHANNELSTATE_FIELD_BRIDGENODESIGNALSTRENGTH,
        "bridge_node_signal_strength",
        31,
        "<B",
    ),
    (C.SUPLA_CHANNELSTATE_FIELD_UPTIME, "uptime", 32, "<I"),
    (C.SUPLA_CHANNELSTATE_FIELD_CONNECTIONUPTIME, "connection_uptime", 36, "<I"),
    (C.SUPLA_CHANNELSTATE_FIELD_BATTERYHEALTH, "battery_health", 40, "<B"),
    (
        C.SUPLA_CHANNELSTATE_FIELD_LASTCONNECTIONRESETCAUSE,
        "last_connection_reset_cause",
        41,
        "<B",
    ),
    (C.SUPLA_CHANNELSTATE_FIELD_LIGHTSOURCELIFESPAN, "light_source_lifespan", 42, "<H"),
    (C.SUPLA_CHANNELSTATE_FIELD_SWITCHCYCLECOUNT, "switch_cycle_count", 12, "<I"),
    (C.SUPLA_CHANNELSTATE_FIELD_DEVICE_BATTERYLEVEL, "device_battery_level", 26, "<B"),
)


def decode_channel_state(raw: bytes) -> dict[str, Any]:
    """TDSC_ChannelState -> only the members the device says it filled in.

    The struct grew over protocol versions, so a short payload simply yields
    fewer keys rather than an error.
    """
    if len(raw) < 12:
        raise ValueError("short channel state")

    fields = struct.unpack_from("<i", raw, 8)[0]
    state: dict[str, Any] = {"channel": raw[4], "fields": fields}

    if fields & C.SUPLA_CHANNELSTATE_FIELD_IPV4 and len(raw) >= 20:
        # Carried as the four address bytes in order, so read them as octets
        # rather than as an integer whose byte order would be a guess.
        state["ipv4"] = ".".join(str(octet) for octet in raw[16:20])
    if fields & C.SUPLA_CHANNELSTATE_FIELD_MAC and len(raw) >= 26:
        state["mac"] = ":".join(f"{octet:02x}" for octet in raw[20:26])

    for bit, name, offset, fmt in _STATE_FIELDS:
        if not fields & bit:
            continue
        if len(raw) < offset + struct.calcsize(fmt):
            continue
        state[name] = struct.unpack_from(fmt, raw, offset)[0]

    if "last_connection_reset_cause" in state:
        state["last_connection_reset_cause_name"] = C.CONNECTION_RESET_CAUSE_NAMES.get(
            state["last_connection_reset_cause"], "unknown"
        )
    if "battery_powered" in state:
        state["battery_powered"] = bool(state["battery_powered"])
    if "bridge_node_online" in state:
        state["bridge_node_online"] = bool(state["bridge_node_online"])
    return state


def decode_extended_value(ev_type: int, raw: bytes) -> dict[str, Any]:
    """Decode the common extended value payloads; keep raw bytes for the rest."""
    decoded: dict[str, Any] = {"type": ev_type, "size": len(raw)}

    if ev_type == C.EV_TYPE_ELECTRICITY_METER_MEASUREMENT_V3 and len(raw) >= 24:
        forward = struct.unpack_from("<QQQ", raw, 0)
        decoded["total_forward_active_energy_kwh"] = [
            round(value / 100000.0, 5) for value in forward
        ]
    elif ev_type == C.EV_TYPE_IMPULSE_COUNTER_DETAILS_V1 and len(raw) >= 44:
        total_cost, price_per_unit = struct.unpack_from("<ii", raw, 0)
        counter, calculated = struct.unpack_from("<Qq", raw, 28)
        decoded["total_cost"] = round(total_cost / 100.0, 2)
        decoded["price_per_unit"] = round(price_per_unit / 10000.0, 4)
        decoded["counter"] = counter
        decoded["calculated_value"] = round(calculated / 1000.0, 3)
    elif ev_type in (
        C.EV_TYPE_CHANNEL_STATE_V1,
        C.EV_TYPE_CHANNEL_AND_TIMER_STATE_V1,
    ):
        # The combined value starts with the channel state; the timer half is
        # a countdown this integration does not model.
        decoded["state"] = decode_channel_state(raw[:_STATE_SIZE])
    else:
        decoded["raw"] = raw[:64].hex()

    return decoded
