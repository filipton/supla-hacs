"""The single source of truth for "which entities does this channel produce".

Kept free of Home Assistant imports so it can be reasoned about (and tested)
on its own. Device classes and units are returned as the plain strings that
back Home Assistant's enums, so callers can do `CoverDeviceClass(value)`.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config_map
from .const import (
    BINARY_SENSOR,
    CLIMATE,
    COVER,
    EVENT,
    FUNCTION_LABELS,
    KIND_LABELS,
    LIGHT,
    LOCK,
    NUMBER,
    PLATFORMS,
    SELECT,
    SENSOR,
    SWITCH,
    VALVE,
)
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K
from .server import consts as C

__all__ = [
    "BINARY_SENSOR",
    "CLIMATE",
    "COVER",
    "EVENT",
    "LIGHT",
    "LOCK",
    "NUMBER",
    "PLATFORMS",
    "SELECT",
    "SENSOR",
    "SWITCH",
    "VALVE",
]

# Roles disambiguate several entities carved out of one channel. The empty role
# is the channel's primary entity and keeps the bare "<guid>-<number>" id.
ROLE_PRIMARY = ""
ROLE_TEMPERATURE = "temperature"
ROLE_HUMIDITY = "humidity"
ROLE_PHASE = "phase"
ROLE_CALCULATED = "calculated"
ROLE_WHITE = "white"

#: Device-level connectivity entity; not tied to any channel.
CONNECTIVITY_KEY = "connectivity"


@dataclass(frozen=True, slots=True)
class EntityKey:
    """Identifies one entity derived from one channel."""

    platform: str
    channel: int
    kind: str
    role: str = ROLE_PRIMARY
    index: int = 0

    @property
    def suffix(self) -> str:
        """Tail of the entity's unique id, stable across restarts."""
        parts: list[str] = [str(self.channel)]
        if self.role:
            parts.append(self.role)
        if self.index:
            parts.append(str(self.index))
        return "-".join(parts)


def unique_id(guid: str, suffix: str) -> str:
    return f"{guid}-{suffix}"


# --- relay fan-out ---------------------------------------------------------

_RELAY_PLATFORMS: dict[int, str] = {
    C.SUPLA_CHANNELFNC_LIGHTSWITCH: LIGHT,
    C.SUPLA_CHANNELFNC_POWERSWITCH: SWITCH,
    C.SUPLA_CHANNELFNC_STAIRCASETIMER: SWITCH,
    C.SUPLA_CHANNELFNC_PUMPSWITCH: SWITCH,
    C.SUPLA_CHANNELFNC_HEATORCOLDSOURCESWITCH: SWITCH,
    C.SUPLA_CHANNELFNC_RING: SWITCH,
    C.SUPLA_CHANNELFNC_ALARM: SWITCH,
    C.SUPLA_CHANNELFNC_NOTIFICATION: SWITCH,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE: COVER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR: COVER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK: LOCK,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK: LOCK,
}

#: Relay functions driven as a momentary pulse: one command triggers the motor
#: or strike, and the real state comes from a paired opening sensor.
IMPULSE_RELAY_FUNCTIONS = frozenset(
    {
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE,
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR,
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK,
        C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK,
    }
)

_SINGLE_PLATFORM_KINDS: dict[str, str] = {
    K.KIND_ROLLER_SHUTTER: COVER,
    K.KIND_FACADE_BLIND: COVER,
    K.KIND_DIMMER: LIGHT,
    K.KIND_RGB: LIGHT,
    K.KIND_BINARY_SENSOR: BINARY_SENSOR,
    K.KIND_THERMOMETER: SENSOR,
    K.KIND_HUMIDITY: SENSOR,
    K.KIND_MEASUREMENT: SENSOR,
    K.KIND_CONTAINER: SENSOR,
    K.KIND_HVAC: CLIMATE,
    K.KIND_THERMOSTAT_HEATPOL: CLIMATE,
    K.KIND_VALVE_OPEN_CLOSE: VALVE,
    K.KIND_VALVE_PERCENTAGE: VALVE,
    K.KIND_DIGIGLASS: SWITCH,
    K.KIND_ENGINE_SPEED: NUMBER,
    K.KIND_ACTION_TRIGGER: EVENT,
}


def _value_keys(channel: ChannelSnapshot) -> list[EntityKey]:
    """Entities that read or drive the channel's value."""
    kind = channel.kind
    number = channel.number

    if kind == K.KIND_RELAY:
        platform = _RELAY_PLATFORMS.get(channel.function, SWITCH)
        return [EntityKey(platform, number, kind)]

    if kind == K.KIND_DIMMER_RGB:
        # Two physically independent outputs sharing one channel: an RGB strip
        # and a white dimmer, each with its own brightness. Modelling them as
        # one HA light would mean inventing a master brightness SUPLA has no
        # command for, so they get one entity each.
        return [
            EntityKey(LIGHT, number, kind),
            EntityKey(LIGHT, number, kind, ROLE_WHITE),
        ]

    if kind == K.KIND_TEMP_HUMIDITY:
        return [
            EntityKey(SENSOR, number, kind, ROLE_TEMPERATURE),
            EntityKey(SENSOR, number, kind, ROLE_HUMIDITY),
        ]

    if kind == K.KIND_ELECTRICITY_METER:
        keys = [EntityKey(SENSOR, number, kind)]
        keys += [
            EntityKey(SENSOR, number, kind, ROLE_PHASE, phase)
            for phase in range(1, channel.em_phases + 1)
        ]
        return keys

    if kind == K.KIND_IMPULSE_COUNTER:
        keys = [EntityKey(SENSOR, number, kind)]
        if channel.ic_calculated:
            keys.append(EntityKey(SENSOR, number, kind, ROLE_CALCULATED))
        return keys

    platform = _SINGLE_PLATFORM_KINDS.get(kind)
    if platform is None:
        return []
    return [EntityKey(platform, number, kind)]


def config_keys(channel: ChannelSnapshot) -> list[EntityKey]:
    """Editable settings the channel offers, as configuration entities."""
    return [
        EntityKey(setting.platform, channel.number, channel.kind, setting.role)
        for setting in config_map.channel_settings(channel)
    ]


def entity_keys(channel: ChannelSnapshot) -> list[EntityKey]:
    """Entities produced by a single channel; empty when unsupported."""
    return _value_keys(channel) + config_keys(channel)


def device_entity_keys(device: DeviceSnapshot) -> list[EntityKey]:
    keys: list[EntityKey] = []
    for channel in device.channels:
        keys.extend(entity_keys(channel))
    return keys


def device_config_keys(device: DeviceSnapshot) -> list[config_map.Setting]:
    """Device-level settings this device says it supports."""
    return list(config_map.device_settings(device))


def device_unique_ids(device: DeviceSnapshot) -> set[str]:
    """Every unique id this device should own, including device-level ones."""
    ids = {unique_id(device.guid, CONNECTIVITY_KEY)}
    ids.update(unique_id(device.guid, key.suffix) for key in device_entity_keys(device))
    ids.update(
        unique_id(device.guid, setting.role) for setting in device_config_keys(device)
    )
    return ids


# --- labels ----------------------------------------------------------------

_ROLE_LABELS = {
    ROLE_TEMPERATURE: "Temperature",
    ROLE_HUMIDITY: "Humidity",
    ROLE_CALCULATED: "Total",
    ROLE_WHITE: "Dimmer",
}


def label(channel: ChannelSnapshot, key: EntityKey) -> str:
    """Entity name shown under the device, e.g. "Roller shutter 3"."""
    if key.role.startswith(f"{config_map.ROLE_PREFIX}-"):
        for setting in config_map.channel_settings(channel):
            if setting.role == key.role:
                return f"{setting.label} {channel.number}"
    if key.role in _ROLE_LABELS:
        base = _ROLE_LABELS[key.role]
    elif key.role == ROLE_PHASE:
        return f"Energy phase {key.index}"
    else:
        base = FUNCTION_LABELS.get(channel.function) or KIND_LABELS.get(
            channel.kind, "Channel"
        )
    return f"{base} {channel.number}"


# --- per-platform metadata -------------------------------------------------

_BINARY_SENSOR_CLASSES: dict[int, str] = {
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATEWAY: "opening",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE: "opening",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GARAGEDOOR: "garage_door",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR: "door",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROLLERSHUTTER: "opening",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROOFWINDOW: "window",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_WINDOW: "window",
    C.SUPLA_CHANNELFNC_NOLIQUIDSENSOR: "problem",
    C.SUPLA_CHANNELFNC_CONTAINER_LEVEL_SENSOR: "problem",
    C.SUPLA_CHANNELFNC_FLOOD_SENSOR: "moisture",
    C.SUPLA_CHANNELFNC_MOTION_SENSOR: "motion",
    C.SUPLA_CHANNELFNC_HOTELCARDSENSOR: "presence",
}


def binary_sensor_device_class(function: int) -> str | None:
    return _BINARY_SENSOR_CLASSES.get(function)


_COVER_CLASSES: dict[int, str] = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER: "shutter",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROOFWINDOW: "window",
    C.SUPLA_CHANNELFNC_TERRACE_AWNING: "awning",
    C.SUPLA_CHANNELFNC_PROJECTOR_SCREEN: "shade",
    C.SUPLA_CHANNELFNC_CURTAIN: "curtain",
    C.SUPLA_CHANNELFNC_ROLLER_GARAGE_DOOR: "garage",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEFACADEBLIND: "blind",
    C.SUPLA_CHANNELFNC_VERTICAL_BLIND: "blind",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE: "gate",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR: "garage",
}


def cover_device_class(function: int) -> str | None:
    return _COVER_CLASSES.get(function)


# (device_class, unit) for the `measurement` kind.
_MEASUREMENT_META: dict[int, tuple[str | None, str | None]] = {
    C.SUPLA_CHANNELFNC_DEPTHSENSOR: ("distance", "m"),
    C.SUPLA_CHANNELFNC_DISTANCESENSOR: ("distance", "m"),
    C.SUPLA_CHANNELFNC_WINDSENSOR: ("wind_speed", "m/s"),
    C.SUPLA_CHANNELFNC_PRESSURESENSOR: ("pressure", "hPa"),
    C.SUPLA_CHANNELFNC_RAINSENSOR: ("precipitation", "mm"),
    C.SUPLA_CHANNELFNC_WEIGHTSENSOR: ("weight", "kg"),
}


def measurement_meta(function: int) -> tuple[str | None, str | None]:
    return _MEASUREMENT_META.get(function, (None, None))


# (device_class, unit) for an impulse counter's calculated reading.
_IMPULSE_COUNTER_META: dict[int, tuple[str | None, str | None]] = {
    C.SUPLA_CHANNELFNC_IC_ELECTRICITY_METER: ("energy", "kWh"),
    C.SUPLA_CHANNELFNC_IC_GAS_METER: ("gas", "m³"),
    C.SUPLA_CHANNELFNC_IC_WATER_METER: ("water", "m³"),
    C.SUPLA_CHANNELFNC_IC_HEAT_METER: ("energy", "kWh"),
    C.SUPLA_CHANNELFNC_IC_SECONDS: ("duration", "s"),
}


def impulse_counter_meta(function: int) -> tuple[str | None, str | None]:
    return _IMPULSE_COUNTER_META.get(function, (None, None))


_HVAC_MODES: dict[int, tuple[str, ...]] = {
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT: ("off", "heat"),
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_HEAT_COOL: ("off", "heat", "cool", "heat_cool"),
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_DIFFERENTIAL: ("off", "heat", "cool"),
    C.SUPLA_CHANNELFNC_HVAC_DOMESTIC_HOT_WATER: ("off", "heat"),
    C.SUPLA_CHANNELFNC_HVAC_DRYER: ("off", "dry"),
    C.SUPLA_CHANNELFNC_HVAC_FAN: ("off", "fan_only"),
    C.SUPLA_CHANNELFNC_HVAC_HRV: ("off", "fan_only"),
}


def hvac_modes(function: int) -> tuple[str, ...]:
    return _HVAC_MODES.get(function, ("off", "heat"))


# --- cross-channel pairing -------------------------------------------------

_PAIRED_OPENING_SENSORS: dict[int, tuple[int, ...]] = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE: (
        C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE,
    ),
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR: (
        C.SUPLA_CHANNELFNC_OPENINGSENSOR_GARAGEDOOR,
    ),
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK: (
        C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
    ),
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK: (
        C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATEWAY,
    ),
}


def find_opening_sensor(device: DeviceSnapshot, channel: ChannelSnapshot) -> int | None:
    """Channel number of the sensor that reports the real state of a pulse relay."""
    wanted = _PAIRED_OPENING_SENSORS.get(channel.function)
    if not wanted:
        return None
    return _nearest(device, channel, lambda other: other.function in wanted)


_TEMPERATURE_KINDS = (K.KIND_THERMOMETER, K.KIND_TEMP_HUMIDITY)


def find_thermometer(device: DeviceSnapshot, channel: ChannelSnapshot) -> int | None:
    """Channel number to read `current_temperature` from for a thermostat."""
    return _nearest(device, channel, lambda other: other.kind in _TEMPERATURE_KINDS)


def _nearest(device: DeviceSnapshot, channel: ChannelSnapshot, match) -> int | None:
    """Closest matching channel, preferring the same sub-device.

    SUPLA gives no explicit pairing, but hardware numbers related channels
    next to each other, so proximity is the best signal available.
    """
    candidates = [
        other
        for other in device.channels
        if other.number != channel.number and match(other)
    ]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda other: (
            other.sub_device_id != channel.sub_device_id,
            abs(other.number - channel.number),
            other.number,
        ),
    )
    return best.number
