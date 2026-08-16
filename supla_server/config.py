"""Channel and device configuration structures.

Layouts are taken verbatim from supla-common/proto.h, which wraps every wire
struct in `#pragma pack(push, 1)`, so nothing here is padded.

The central idea is that configuration is edited *in place*. A device sends the
bytes it is currently running, and a write copies those bytes and overwrites one
field at one offset. Reserved regions, fields this file does not model, and
fields a future protocol version adds all survive byte for byte. Nothing is ever
synthesised from scratch when the device has told us what it has.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from . import consts as C

CONFIG_TYPE_DEFAULT = C.SUPLA_CONFIG_TYPE_DEFAULT

CHANNEL_CONFIG_MAXSIZE = 512
DEVICE_CONFIG_MAXSIZE = 512


class ConfigError(ValueError):
    """A configuration value could not be encoded."""


@dataclass(frozen=True, slots=True)
class ConfigField:
    """One scalar inside a configuration struct."""

    key: str
    offset: int
    fmt: str
    #: False for values the device reports about itself, e.g. hardware limits.
    writable: bool = True
    #: Raw units per exposed unit, e.g. 1000 for a millisecond field shown in
    #: seconds, or 100 for a hundredths-of-a-degree field shown in degrees.
    scale: float = 1
    minimum: float | None = None
    maximum: float | None = None
    #: Names of the fields holding device-reported limits, if it has them.
    minimum_from: str | None = None
    maximum_from: str | None = None

    @property
    def size(self) -> int:
        return struct.calcsize(self.fmt)

    def decode(self, raw: bytes) -> int | None:
        if len(raw) < self.offset + self.size:
            return None
        return struct.unpack_from(self.fmt, raw, self.offset)[0]

    def bounds(self) -> tuple[float, float]:
        """Widest range the field can hold, in the unit it is presented in."""
        low, high = _limits(self.fmt)
        return low / self.scale, high / self.scale

    def encode_into(self, buffer: bytearray, value: int) -> None:
        low, high = _limits(self.fmt)
        if not low <= value <= high:
            raise ConfigError(
                f"{self.key}={value} does not fit in {self.fmt}"
            )
        struct.pack_into(self.fmt, buffer, self.offset, value)


def _limits(fmt: str) -> tuple[int, int]:
    size = struct.calcsize(fmt)
    signed = fmt[-1].islower()
    if signed:
        return -(1 << (size * 8 - 1)), (1 << (size * 8 - 1)) - 1
    return 0, (1 << (size * 8)) - 1


@dataclass(frozen=True, slots=True)
class ConfigSpec:
    """A whole configuration struct."""

    name: str
    size: int
    fields: tuple[ConfigField, ...] = dataclass_field(default_factory=tuple)

    def field(self, key: str) -> ConfigField | None:
        for item in self.fields:
            if item.key == key:
                return item
        return None

    def decode(self, raw: bytes | None) -> dict[str, int]:
        """Named values, skipping anything the payload is too short to hold."""
        if not raw:
            return {}
        decoded: dict[str, int] = {}
        for item in self.fields:
            value = item.decode(raw)
            if value is not None:
                decoded[item.key] = value
        return decoded

    def with_field(self, raw: bytes | None, key: str, value: int) -> bytes:
        """A copy of `raw` with one field replaced.

        A short or missing payload is zero-extended to the struct's full size;
        in SUPLA a zeroed configuration field reads as "not set", so the device
        keeps its own defaults for everything that was never filled in.
        """
        item = self.field(key)
        if item is None:
            raise ConfigError(f"{self.name} has no field {key!r}")
        if not item.writable:
            raise ConfigError(f"{self.name}.{key} is reported by the device only")
        buffer = bytearray(raw or b"")
        if len(buffer) < self.size:
            buffer.extend(bytes(self.size - len(buffer)))
        item.encode_into(buffer, value)
        return bytes(buffer)


# --- channel configuration -------------------------------------------------

# TChannelConfig_StaircaseTimer
STAIRCASE_TIMER = ConfigSpec(
    name="staircase_timer",
    size=4,
    fields=(ConfigField("time", 0, "<i", scale=1000, minimum=0, maximum=86400),),
)

# TChannelConfig_RollerShutter, shared by awnings, curtains, screens and
# roller garage doors.
ROLLER_SHUTTER = ConfigSpec(
    name="roller_shutter",
    size=44,
    fields=(
        ConfigField("closing_time", 0, "<i", scale=1000, minimum=0, maximum=600),
        ConfigField("opening_time", 4, "<i", scale=1000, minimum=0, maximum=600),
        # 0 - not set, 1 - false, 2 - true
        ConfigField("motor_upside_down", 8, "<B", minimum=0, maximum=2),
        ConfigField("buttons_upside_down", 9, "<B", minimum=0, maximum=2),
        ConfigField("time_margin", 10, "<b", minimum=-1, maximum=101),
        ConfigField("visualization_type", 11, "<B"),
    ),
)

# TChannelConfig_FacadeBlind, shared by vertical blinds.
FACADE_BLIND = ConfigSpec(
    name="facade_blind",
    size=53,
    fields=(
        ConfigField("closing_time", 0, "<i", scale=1000, minimum=0, maximum=600),
        ConfigField("opening_time", 4, "<i", scale=1000, minimum=0, maximum=600),
        ConfigField("tilting_time", 8, "<i", scale=1000, minimum=0, maximum=600),
        ConfigField("motor_upside_down", 12, "<B", minimum=0, maximum=2),
        ConfigField("buttons_upside_down", 13, "<B", minimum=0, maximum=2),
        ConfigField("time_margin", 14, "<b", minimum=-1, maximum=101),
        ConfigField("tilt_0_angle", 15, "<H", minimum=0, maximum=180),
        ConfigField("tilt_100_angle", 17, "<H", minimum=0, maximum=180),
        ConfigField("tilt_control_type", 19, "<B", minimum=0, maximum=3),
        ConfigField("visualization_type", 20, "<B"),
    ),
)

# TChannelConfig_BinarySensor
BINARY_SENSOR = ConfigSpec(
    name="binary_sensor",
    size=32,
    fields=(
        ConfigField("inverted_logic", 0, "<B", minimum=0, maximum=1),
        ConfigField("filtering_time", 1, "<H", minimum=0, maximum=65535),
        # Reported in units of 0.1 s, capped by proto.h at 36000.
        ConfigField("timeout", 3, "<H", scale=10, minimum=0, maximum=3600),
        # 0 - unused, 1 - off, 2..101 - 1..100 %
        ConfigField("sensitivity", 5, "<B", minimum=0, maximum=101),
        ConfigField("alarm_muted", 6, "<B", minimum=0, maximum=2),
    ),
)

# TChannelConfig_TemperatureAndHumidity
TEMPERATURE_AND_HUMIDITY = ConfigSpec(
    name="temperature_and_humidity",
    size=32,
    fields=(
        ConfigField(
            "temperature_adjustment",
            0,
            "<h",
            scale=100,
            minimum=-10,
            maximum=10,
            minimum_from="min_temperature_adjustment",
            maximum_from="max_temperature_adjustment",
        ),
        ConfigField(
            "humidity_adjustment",
            2,
            "<h",
            scale=100,
            minimum=-10,
            maximum=10,
            minimum_from="min_humidity_adjustment",
            maximum_from="max_humidity_adjustment",
        ),
        ConfigField("adjustment_applied_by_device", 4, "<B", writable=False),
        ConfigField("min_temperature_adjustment", 5, "<h", writable=False, scale=100),
        ConfigField("max_temperature_adjustment", 7, "<h", writable=False, scale=100),
        ConfigField("min_humidity_adjustment", 9, "<h", writable=False, scale=100),
        ConfigField("max_humidity_adjustment", 11, "<h", writable=False, scale=100),
    ),
)

# TChannelConfig_PowerSwitch, shared by light switches and staircase timers.
POWER_SWITCH = ConfigSpec(
    name="power_switch",
    size=42,
    fields=(
        ConfigField(
            "overcurrent_threshold",
            0,
            "<I",
            scale=100,
            minimum=0,
            maximum_from="overcurrent_max_allowed",
        ),
        ConfigField("overcurrent_max_allowed", 4, "<I", writable=False, scale=100),
        ConfigField("default_related_meter_is_set", 8, "<B", writable=False),
        ConfigField("default_related_meter_channel", 9, "<B", writable=False),
    ),
)

#: Channel function -> the struct its SUPLA_CONFIG_TYPE_DEFAULT config uses.
CHANNEL_CONFIG_SPECS: dict[int, ConfigSpec] = {
    C.SUPLA_CHANNELFNC_STAIRCASETIMER: STAIRCASE_TIMER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROOFWINDOW: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_TERRACE_AWNING: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_PROJECTOR_SCREEN: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_CURTAIN: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_ROLLER_GARAGE_DOOR: ROLLER_SHUTTER,
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEFACADEBLIND: FACADE_BLIND,
    C.SUPLA_CHANNELFNC_VERTICAL_BLIND: FACADE_BLIND,
    C.SUPLA_CHANNELFNC_HUMIDITYANDTEMPERATURE: TEMPERATURE_AND_HUMIDITY,
    C.SUPLA_CHANNELFNC_THERMOMETER: TEMPERATURE_AND_HUMIDITY,
    C.SUPLA_CHANNELFNC_HUMIDITY: TEMPERATURE_AND_HUMIDITY,
    C.SUPLA_CHANNELFNC_POWERSWITCH: POWER_SWITCH,
    C.SUPLA_CHANNELFNC_LIGHTSWITCH: POWER_SWITCH,
}

for _function in (
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATEWAY,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GARAGEDOOR,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROLLERSHUTTER,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROOFWINDOW,
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_WINDOW,
    C.SUPLA_CHANNELFNC_NOLIQUIDSENSOR,
    C.SUPLA_CHANNELFNC_MAILSENSOR,
    C.SUPLA_CHANNELFNC_HOTELCARDSENSOR,
    C.SUPLA_CHANNELFNC_ALARMARMAMENTSENSOR,
    C.SUPLA_CHANNELFNC_CONTAINER_LEVEL_SENSOR,
    C.SUPLA_CHANNELFNC_FLOOD_SENSOR,
    C.SUPLA_CHANNELFNC_MOTION_SENSOR,
    C.SUPLA_CHANNELFNC_BINARY_SENSOR,
):
    CHANNEL_CONFIG_SPECS[_function] = BINARY_SENSOR


def channel_config_spec(function: int) -> ConfigSpec | None:
    """The struct a channel's default config uses, or None if unmodelled."""
    return CHANNEL_CONFIG_SPECS.get(function)


# --- device configuration --------------------------------------------------

# SUPLA_DEVICE_CONFIG_FIELD_*
FIELD_STATUS_LED = 1 << 0
FIELD_SCREEN_BRIGHTNESS = 1 << 1
FIELD_BUTTON_VOLUME = 1 << 2
FIELD_DISABLE_USER_INTERFACE = 1 << 3
FIELD_AUTOMATIC_TIME_SYNC = 1 << 4
FIELD_HOME_SCREEN_OFF_DELAY = 1 << 5
FIELD_HOME_SCREEN_CONTENT = 1 << 6
FIELD_HOME_SCREEN_OFF_DELAY_TYPE = 1 << 7
FIELD_POWER_STATUS_LED = 1 << 8

STATUS_LED_ON_WHEN_CONNECTED = 0
STATUS_LED_OFF_WHEN_CONNECTED = 1
STATUS_LED_ALWAYS_OFF = 2

USER_INTERFACE_ENABLED = 0
USER_INTERFACE_DISABLED = 1
USER_INTERFACE_PARTIAL = 2

HOME_SCREEN_OFF_DELAY_ALWAYS_ENABLED = 0
HOME_SCREEN_OFF_DELAY_WHEN_DARK = 1

# SUPLA_DEVCFG_HOME_SCREEN_CONTENT_*
HOME_SCREEN_CONTENT_NONE = 1 << 0
HOME_SCREEN_CONTENT_TEMPERATURE = 1 << 1
HOME_SCREEN_CONTENT_TEMPERATURE_AND_HUMIDITY = 1 << 2
HOME_SCREEN_CONTENT_TIME = 1 << 3
HOME_SCREEN_CONTENT_TIME_DATE = 1 << 4
HOME_SCREEN_CONTENT_TEMPERATURE_TIME = 1 << 5
HOME_SCREEN_CONTENT_MAIN_AND_AUX_TEMPERATURE = 1 << 6
HOME_SCREEN_CONTENT_MODE_OR_TEMPERATURE = 1 << 7


@dataclass(frozen=True, slots=True)
class DeviceConfigField:
    """One entry of the device config blob, located by the Fields bitmap."""

    bit: int
    spec: ConfigSpec


DEVICE_CONFIG_FIELDS: tuple[DeviceConfigField, ...] = (
    DeviceConfigField(
        FIELD_STATUS_LED,
        ConfigSpec(
            "status_led",
            1,
            (ConfigField("status_led_type", 0, "<B", minimum=0, maximum=2),),
        ),
    ),
    DeviceConfigField(
        FIELD_SCREEN_BRIGHTNESS,
        ConfigSpec(
            "screen_brightness",
            3,
            (
                ConfigField("screen_brightness", 0, "<B", minimum=0, maximum=100),
                ConfigField("automatic", 1, "<B", minimum=0, maximum=1),
                ConfigField("adjustment_for_automatic", 2, "<b"),
            ),
        ),
    ),
    DeviceConfigField(
        FIELD_BUTTON_VOLUME,
        ConfigSpec(
            "button_volume",
            1,
            (ConfigField("volume", 0, "<B", minimum=0, maximum=100),),
        ),
    ),
    DeviceConfigField(
        FIELD_DISABLE_USER_INTERFACE,
        ConfigSpec(
            "disable_user_interface",
            5,
            (
                ConfigField("disable_user_interface", 0, "<B", minimum=0, maximum=2),
                ConfigField("min_allowed_setpoint", 1, "<H", scale=100),
                ConfigField("max_allowed_setpoint", 3, "<H", scale=100),
            ),
        ),
    ),
    DeviceConfigField(
        FIELD_AUTOMATIC_TIME_SYNC,
        ConfigSpec(
            "automatic_time_sync",
            1,
            (ConfigField("automatic_time_sync", 0, "<B", minimum=0, maximum=1),),
        ),
    ),
    DeviceConfigField(
        FIELD_HOME_SCREEN_OFF_DELAY,
        ConfigSpec(
            "home_screen_off_delay",
            2,
            (ConfigField("off_delay", 0, "<H", minimum=0, maximum=65535),),
        ),
    ),
    DeviceConfigField(
        FIELD_HOME_SCREEN_CONTENT,
        ConfigSpec(
            "home_screen_content",
            16,
            (
                ConfigField("content_available", 0, "<Q", writable=False),
                ConfigField("home_screen_content", 8, "<Q"),
            ),
        ),
    ),
    DeviceConfigField(
        FIELD_HOME_SCREEN_OFF_DELAY_TYPE,
        ConfigSpec(
            "home_screen_off_delay_type",
            1,
            (ConfigField("off_delay_type", 0, "<B", minimum=0, maximum=1),),
        ),
    ),
    DeviceConfigField(
        FIELD_POWER_STATUS_LED,
        ConfigSpec(
            "power_status_led",
            1,
            (ConfigField("disabled", 0, "<B", minimum=0, maximum=1),),
        ),
    ),
)

DEVICE_CONFIG_BY_NAME: dict[str, DeviceConfigField] = {
    entry.spec.name: entry for entry in DEVICE_CONFIG_FIELDS
}

#: Everything this file can locate. Bits above these are kept as an opaque
#: tail, because a field of unknown length cannot be walked past safely.
KNOWN_DEVICE_FIELDS = 0
for _entry in DEVICE_CONFIG_FIELDS:
    KNOWN_DEVICE_FIELDS |= _entry.bit


def device_config_layout(fields: int) -> dict[str, tuple[int, ConfigSpec]]:
    """Offset of every locatable field in a device config blob.

    proto.h stores fields "in order as they appear in Fields", so the blob is
    walked in ascending bit order. Walking stops at the first field whose size
    is unknown, since everything after it would be at a guessed offset.
    """
    layout: dict[str, tuple[int, ConfigSpec]] = {}
    offset = 0
    for bit in range(64):
        mask = 1 << bit
        if not fields & mask:
            continue
        entry = next((item for item in DEVICE_CONFIG_FIELDS if item.bit == mask), None)
        if entry is None:
            break
        layout[entry.spec.name] = (offset, entry.spec)
        offset += entry.spec.size
    return layout


def decode_device_config(fields: int, raw: bytes) -> dict[str, dict[str, int]]:
    decoded: dict[str, dict[str, int]] = {}
    for name, (offset, spec) in device_config_layout(fields).items():
        chunk = raw[offset : offset + spec.size]
        if len(chunk) == spec.size:
            decoded[name] = spec.decode(chunk)
    return decoded


def device_config_with_field(
    raw: bytes,
    fields: int,
    name: str,
    key: str,
    value: int,
) -> tuple[bytes, int]:
    """Return (blob, fields) with one device config value replaced.

    A field the device has not reported yet is inserted at its correct place in
    bit order and its bit added to the mask, so the blob stays in the layout
    proto.h specifies.
    """
    entry = DEVICE_CONFIG_BY_NAME.get(name)
    if entry is None:
        raise ConfigError(f"unknown device config field {name!r}")

    layout = device_config_layout(fields)
    if name in layout:
        offset, spec = layout[name]
        chunk = spec.with_field(raw[offset : offset + spec.size], key, value)
        return raw[:offset] + chunk + raw[offset + spec.size :], fields

    if fields & ~KNOWN_DEVICE_FIELDS:
        # An unmodelled field is present, so the tail cannot be split reliably.
        raise ConfigError(
            f"cannot place {name!r}: the device reports fields this build "
            "does not know how to measure"
        )

    insert_at = sum(
        item.spec.size
        for item in DEVICE_CONFIG_FIELDS
        if item.bit < entry.bit and fields & item.bit
    )
    chunk = entry.spec.with_field(b"", key, value)
    return raw[:insert_at] + chunk + raw[insert_at:], fields | entry.bit


def scaled(spec_or_field: ConfigField, raw_value: int | None) -> float | None:
    """Raw struct value converted to the unit the field is presented in."""
    if raw_value is None:
        return None
    if spec_or_field.scale == 1:
        return raw_value
    return raw_value / spec_or_field.scale


def unscaled(field: ConfigField, value: float) -> int:
    """The inverse of `scaled`, rounded to the nearest raw unit."""
    return int(round(value * field.scale))


def describe(values: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))
