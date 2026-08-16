"""Which device diagnostics become sensors.

Everything here comes out of `TDSC_ChannelState`, the struct SUPLA devices use
to report about themselves. It carries a bitmap saying which members were
actually filled in, so a sensor is only offered once its bit has been seen.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import SENSOR
from .models import DeviceSnapshot
from .server import consts as C

#: Prefix for the entity-key role of a diagnostics entity.
ROLE_PREFIX = "state"


@dataclass(frozen=True, slots=True)
class StateSensor:
    """One reading out of the device's self-report."""

    key: str
    bit: int
    label: str
    platform: str = SENSOR
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    icon: str | None = None
    options: tuple[str, ...] = ()
    #: The value is an age in seconds; show the instant it counts from instead,
    #: which stays still rather than ticking once a second.
    age_in_seconds: bool = False

    @property
    def role(self) -> str:
        return f"{ROLE_PREFIX}-{self.key}"


STATE_SENSORS: tuple[StateSensor, ...] = (
    StateSensor(
        "ipv4",
        C.SUPLA_CHANNELSTATE_FIELD_IPV4,
        "IP address",
        icon="mdi:ip-network-outline",
    ),
    StateSensor(
        "wifi_rssi",
        C.SUPLA_CHANNELSTATE_FIELD_WIFIRSSI,
        "Wi-Fi signal",
        device_class="signal_strength",
        unit="dBm",
        state_class="measurement",
    ),
    StateSensor(
        "wifi_signal_strength",
        C.SUPLA_CHANNELSTATE_FIELD_WIFISIGNALSTRENGTH,
        "Wi-Fi signal strength",
        unit="%",
        state_class="measurement",
        icon="mdi:wifi",
    ),
    StateSensor(
        "uptime",
        C.SUPLA_CHANNELSTATE_FIELD_UPTIME,
        "Up since",
        device_class="timestamp",
        age_in_seconds=True,
    ),
    StateSensor(
        "connection_uptime",
        C.SUPLA_CHANNELSTATE_FIELD_CONNECTIONUPTIME,
        "Connected since",
        device_class="timestamp",
        age_in_seconds=True,
    ),
    StateSensor(
        "last_connection_reset_cause_name",
        C.SUPLA_CHANNELSTATE_FIELD_LASTCONNECTIONRESETCAUSE,
        "Last disconnect reason",
        device_class="enum",
        options=tuple(C.CONNECTION_RESET_CAUSE_NAMES.values()),
        icon="mdi:lan-disconnect",
    ),
    StateSensor(
        "battery_level",
        C.SUPLA_CHANNELSTATE_FIELD_BATTERYLEVEL,
        "Battery",
        device_class="battery",
        unit="%",
        state_class="measurement",
    ),
    StateSensor(
        "battery_health",
        C.SUPLA_CHANNELSTATE_FIELD_BATTERYHEALTH,
        "Battery health",
        unit="%",
        state_class="measurement",
        icon="mdi:battery-heart-variant",
    ),
)


def device_state_sensors(device: DeviceSnapshot) -> tuple[StateSensor, ...]:
    """The diagnostics this device has actually reported."""
    if not device.state_fields:
        return ()
    return tuple(
        sensor for sensor in STATE_SENSORS if device.state_fields & sensor.bit
    )
