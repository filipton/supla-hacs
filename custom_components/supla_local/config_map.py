"""Which configuration fields become editable Home Assistant entities.

`server/config.py` knows the wire layout; this file decides which of those
fields a person should see, what to call them and how to present them. Only
settings a device says it supports are ever offered.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import NUMBER, SELECT, SWITCH
from .models import ChannelSnapshot, DeviceSnapshot
from .server import config as cfg

#: Prefix for the entity-key role of a configuration entity.
ROLE_PREFIX = "config"


@dataclass(frozen=True, slots=True)
class Setting:
    """One configuration field, as presented in Home Assistant."""

    key: str
    platform: str
    label: str
    #: Device config only: which struct inside the blob the field lives in.
    group: str = ""
    unit: str | None = None
    step: float = 1
    minimum: float | None = None
    maximum: float | None = None
    #: Select options as (raw value, label), in the order they should appear.
    values: tuple[tuple[int, str], ...] = ()
    #: Select only: sibling field whose bits say which values this device offers.
    values_gated_by: str = ""
    #: Switch only: SUPLA's 0 = not set, 1 = false, 2 = true encoding.
    tri_state: bool = False
    #: Switch only: the stored value means the opposite of the entity's name.
    inverted: bool = False
    icon: str | None = None

    @property
    def role(self) -> str:
        name = f"{self.group}-{self.key}" if self.group else self.key
        return f"{ROLE_PREFIX}-{name}"


# --- channel settings ------------------------------------------------------

_TIME_STEP = 0.1

_UPSIDE_DOWN = (
    Setting(
        "motor_upside_down",
        SWITCH,
        "Motor direction reversed",
        tri_state=True,
        icon="mdi:swap-vertical",
    ),
    Setting(
        "buttons_upside_down",
        SWITCH,
        "Buttons reversed",
        tri_state=True,
        icon="mdi:swap-vertical",
    ),
)

_TRAVEL_TIMES = (
    Setting("opening_time", NUMBER, "Opening time", unit="s", step=_TIME_STEP),
    Setting("closing_time", NUMBER, "Closing time", unit="s", step=_TIME_STEP),
)

CHANNEL_SETTINGS: dict[str, tuple[Setting, ...]] = {
    cfg.STAIRCASE_TIMER.name: (
        Setting("time", NUMBER, "Timer duration", unit="s", icon="mdi:timer-outline"),
    ),
    cfg.ROLLER_SHUTTER.name: _TRAVEL_TIMES + _UPSIDE_DOWN,
    cfg.FACADE_BLIND.name: _TRAVEL_TIMES
    + (Setting("tilting_time", NUMBER, "Tilting time", unit="s", step=_TIME_STEP),)
    + _UPSIDE_DOWN
    + (
        Setting("tilt_0_angle", NUMBER, "Tilt 0 angle", unit="°", maximum=180),
        Setting("tilt_100_angle", NUMBER, "Tilt 100 angle", unit="°", maximum=180),
        Setting(
            "tilt_control_type",
            SELECT,
            "Tilt behaviour",
            values=(
                (0, "Unknown"),
                (1, "Stands in position"),
                (2, "Changes position"),
                (3, "Tilts only when closed"),
            ),
        ),
    ),
    cfg.BINARY_SENSOR.name: (
        Setting("inverted_logic", SWITCH, "Inverted logic", icon="mdi:swap-horizontal"),
        Setting(
            "filtering_time",
            NUMBER,
            "Input filtering time",
            unit="ms",
            icon="mdi:filter-outline",
        ),
        Setting("timeout", NUMBER, "Reset timeout", unit="s", step=_TIME_STEP),
    ),
    cfg.TEMPERATURE_AND_HUMIDITY.name: (
        Setting(
            "temperature_adjustment",
            NUMBER,
            "Temperature offset",
            unit="°C",
            step=0.01,
            icon="mdi:thermometer-plus",
        ),
        Setting(
            "humidity_adjustment",
            NUMBER,
            "Humidity offset",
            unit="%",
            step=0.01,
            icon="mdi:water-percent",
        ),
    ),
    cfg.POWER_SWITCH.name: (
        Setting(
            "overcurrent_threshold",
            NUMBER,
            "Overcurrent threshold",
            unit="A",
            step=0.01,
            icon="mdi:flash-alert",
        ),
    ),
}


def channel_settings(channel: ChannelSnapshot) -> tuple[Setting, ...]:
    """Settings this channel actually offers."""
    spec = channel.config_spec
    if spec is None or not channel.accepts_runtime_config:
        return ()
    values = channel.decoded_config()
    offered = []
    for setting in CHANNEL_SETTINGS.get(spec.name, ()):
        field = spec.field(setting.key)
        if field is None:
            continue
        # proto.h: a zero hardware limit means the feature is not available.
        if field.maximum_from and not values.get(field.maximum_from, 0):
            continue
        offered.append(setting)
    return tuple(offered)


# --- device settings -------------------------------------------------------

DEVICE_SETTINGS: tuple[Setting, ...] = (
    Setting(
        "status_led_type",
        SELECT,
        "Status LED",
        group=cfg.DEVICE_CONFIG_BY_NAME["status_led"].spec.name,
        values=(
            (cfg.STATUS_LED_ON_WHEN_CONNECTED, "On when connected"),
            (cfg.STATUS_LED_OFF_WHEN_CONNECTED, "Off when connected"),
            (cfg.STATUS_LED_ALWAYS_OFF, "Always off"),
        ),
        icon="mdi:led-on",
    ),
    Setting(
        "disabled",
        SWITCH,
        "Power status LED",
        group="power_status_led",
        inverted=True,
        icon="mdi:led-outline",
    ),
    Setting(
        "screen_brightness",
        NUMBER,
        "Screen brightness",
        group="screen_brightness",
        unit="%",
        maximum=100,
        icon="mdi:brightness-6",
    ),
    Setting(
        "automatic",
        SWITCH,
        "Automatic screen brightness",
        group="screen_brightness",
        icon="mdi:brightness-auto",
    ),
    Setting(
        "volume",
        NUMBER,
        "Button volume",
        group="button_volume",
        unit="%",
        maximum=100,
        icon="mdi:volume-high",
    ),
    Setting(
        "disable_user_interface",
        SELECT,
        "Local controls",
        group="disable_user_interface",
        values=(
            (cfg.USER_INTERFACE_ENABLED, "Enabled"),
            (cfg.USER_INTERFACE_DISABLED, "Disabled"),
            (cfg.USER_INTERFACE_PARTIAL, "Partially disabled"),
        ),
        icon="mdi:gesture-tap-button",
    ),
    Setting(
        "automatic_time_sync",
        SWITCH,
        "Automatic time sync",
        group="automatic_time_sync",
        icon="mdi:clock-check-outline",
    ),
    Setting(
        "off_delay",
        NUMBER,
        "Home screen off delay",
        group="home_screen_off_delay",
        unit="s",
        maximum=65535,
        icon="mdi:monitor-off",
    ),
    Setting(
        "off_delay_type",
        SELECT,
        "Home screen off delay applies",
        group="home_screen_off_delay_type",
        values=(
            (cfg.HOME_SCREEN_OFF_DELAY_ALWAYS_ENABLED, "Always"),
            (cfg.HOME_SCREEN_OFF_DELAY_WHEN_DARK, "Only when dark"),
        ),
    ),
    Setting(
        "home_screen_content",
        SELECT,
        "Home screen content",
        group="home_screen_content",
        values=(
            (cfg.HOME_SCREEN_CONTENT_NONE, "Nothing"),
            (cfg.HOME_SCREEN_CONTENT_TEMPERATURE, "Temperature"),
            (cfg.HOME_SCREEN_CONTENT_TEMPERATURE_AND_HUMIDITY, "Temperature and humidity"),
            (cfg.HOME_SCREEN_CONTENT_TIME, "Time"),
            (cfg.HOME_SCREEN_CONTENT_TIME_DATE, "Time and date"),
            (cfg.HOME_SCREEN_CONTENT_TEMPERATURE_TIME, "Temperature and time"),
            (cfg.HOME_SCREEN_CONTENT_MAIN_AND_AUX_TEMPERATURE, "Main and auxiliary temperature"),
            (cfg.HOME_SCREEN_CONTENT_MODE_OR_TEMPERATURE, "Mode or temperature"),
        ),
        values_gated_by="content_available",
        icon="mdi:monitor-dashboard",
    ),
)

DEVICE_SETTINGS_BY_ROLE: dict[str, Setting] = {
    setting.role: setting for setting in DEVICE_SETTINGS
}


def device_settings(device: DeviceSnapshot) -> tuple[Setting, ...]:
    """Device-level settings this device says it supports."""
    available = device.device_config_available
    if not available:
        return ()
    offered = []
    for setting in DEVICE_SETTINGS:
        entry = cfg.DEVICE_CONFIG_BY_NAME.get(setting.group)
        if entry is None or not available & entry.bit:
            continue
        offered.append(setting)
    return tuple(offered)


def spec_for(setting: Setting) -> cfg.ConfigSpec | None:
    """The struct a device-level setting lives in."""
    entry = cfg.DEVICE_CONFIG_BY_NAME.get(setting.group)
    return entry.spec if entry is not None else None


def options_for(setting: Setting, values: dict[str, int]) -> list[tuple[int, str]]:
    """Select options, narrowed to what the device reports as available."""
    if not setting.values_gated_by:
        return list(setting.values)
    mask = values.get(setting.values_gated_by, 0)
    if not mask:
        return []
    return [(raw, label) for raw, label in setting.values if mask & raw]
