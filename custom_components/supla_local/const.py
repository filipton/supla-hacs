"""Constants for the SUPLA Local integration."""

from __future__ import annotations

from typing import Final

from .server import consts as C

DOMAIN: Final = "supla_local"

CONF_TCP_PORT: Final = "tcp_port"
CONF_ENABLE_TLS: Final = "enable_tls"
CONF_TLS_PORT: Final = "tls_port"

DEFAULT_TCP_PORT: Final = C.DEFAULT_TCP_PORT
DEFAULT_TLS_PORT: Final = C.DEFAULT_TLS_PORT
DEFAULT_ENABLE_TLS: Final = True

MANUFACTURER: Final = "SUPLA"

# Platform names, matching homeassistant.const.Platform values. Kept here so
# both the channel map and the configuration map can use them without a cycle.
BINARY_SENSOR: Final = "binary_sensor"
CLIMATE: Final = "climate"
COVER: Final = "cover"
EVENT: Final = "event"
LIGHT: Final = "light"
LOCK: Final = "lock"
NUMBER: Final = "number"
SELECT: Final = "select"
SENSOR: Final = "sensor"
SWITCH: Final = "switch"
VALVE: Final = "valve"

PLATFORMS: Final[tuple[str, ...]] = (
    BINARY_SENSOR,
    CLIMATE,
    COVER,
    EVENT,
    LIGHT,
    LOCK,
    NUMBER,
    SELECT,
    SENSOR,
    SWITCH,
    VALVE,
)

#: Sub-directory of the HA config dir holding the generated TLS key pair.
CERT_DIRNAME: Final = DOMAIN

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1
#: The registry listener fires on every reported value, so writes are coalesced.
STORAGE_SAVE_DELAY: Final = 15

#: Dispatcher signal carrying "some state of this device changed", per GUID.
SIGNAL_DEVICE_UPDATE: Final = f"{DOMAIN}_device_update_{{}}"

#: Dispatcher signal for one button press, per GUID and channel number.
SIGNAL_ACTION_TRIGGER: Final = f"{DOMAIN}_action_{{}}_{{}}"

#: Bus event fired for every SUPLA action trigger (button press).
EVENT_ACTION_TRIGGER: Final = f"{DOMAIN}_action_trigger"

# SUPLA_ACTION_CAP_* from supla-common/proto.h, in bit order.
ACTION_TRIGGER_CAPS: Final[tuple[tuple[int, str], ...]] = (
    (1 << 0, "turn_on"),
    (1 << 1, "turn_off"),
    (1 << 2, "toggle_x1"),
    (1 << 3, "toggle_x2"),
    (1 << 4, "toggle_x3"),
    (1 << 5, "toggle_x4"),
    (1 << 6, "toggle_x5"),
    (1 << 7, "hold"),
    (1 << 8, "press_x1"),
    (1 << 9, "press_x2"),
    (1 << 10, "press_x3"),
    (1 << 11, "press_x4"),
    (1 << 12, "press_x5"),
)

ACTION_TRIGGER_EVENT_TYPES: Final = tuple(name for _bit, name in ACTION_TRIGGER_CAPS)

# Human-readable channel labels. SUPLA channel captions live on the cloud server,
# never on the device link, so the function name is the best name we can offer;
# users rename entities in HA afterwards.
FUNCTION_LABELS: Final[dict[int, str]] = {
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK: "Gateway lock",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE: "Gate",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR: "Garage door",
    C.SUPLA_CHANNELFNC_THERMOMETER: "Temperature",
    C.SUPLA_CHANNELFNC_HUMIDITY: "Humidity",
    C.SUPLA_CHANNELFNC_HUMIDITYANDTEMPERATURE: "Climate",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATEWAY: "Gateway",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE: "Gate",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_GARAGEDOOR: "Garage door",
    C.SUPLA_CHANNELFNC_NOLIQUIDSENSOR: "Liquid",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK: "Door lock",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR: "Door",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROLLERSHUTTER: "Roller shutter",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEROOFWINDOW: "Roof window",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROLLERSHUTTER: "Roller shutter",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_ROOFWINDOW: "Roof window",
    C.SUPLA_CHANNELFNC_POWERSWITCH: "Power",
    C.SUPLA_CHANNELFNC_LIGHTSWITCH: "Light",
    C.SUPLA_CHANNELFNC_RING: "Ring",
    C.SUPLA_CHANNELFNC_ALARM: "Alarm",
    C.SUPLA_CHANNELFNC_NOTIFICATION: "Notification",
    C.SUPLA_CHANNELFNC_DIMMER: "Dimmer",
    C.SUPLA_CHANNELFNC_DIMMER_CCT: "Dimmer",
    C.SUPLA_CHANNELFNC_RGBLIGHTING: "RGB light",
    C.SUPLA_CHANNELFNC_DIMMERANDRGBLIGHTING: "RGB light",
    C.SUPLA_CHANNELFNC_DIMMER_CCT_AND_RGB: "RGB light",
    C.SUPLA_CHANNELFNC_DEPTHSENSOR: "Depth",
    C.SUPLA_CHANNELFNC_DISTANCESENSOR: "Distance",
    C.SUPLA_CHANNELFNC_OPENINGSENSOR_WINDOW: "Window",
    C.SUPLA_CHANNELFNC_HOTELCARDSENSOR: "Hotel card",
    C.SUPLA_CHANNELFNC_ALARMARMAMENTSENSOR: "Alarm armed",
    C.SUPLA_CHANNELFNC_MAILSENSOR: "Mail",
    C.SUPLA_CHANNELFNC_WINDSENSOR: "Wind",
    C.SUPLA_CHANNELFNC_PRESSURESENSOR: "Pressure",
    C.SUPLA_CHANNELFNC_RAINSENSOR: "Rain",
    C.SUPLA_CHANNELFNC_WEIGHTSENSOR: "Weight",
    C.SUPLA_CHANNELFNC_WEATHER_STATION: "Weather station",
    C.SUPLA_CHANNELFNC_STAIRCASETIMER: "Staircase timer",
    C.SUPLA_CHANNELFNC_ELECTRICITY_METER: "Energy",
    C.SUPLA_CHANNELFNC_IC_ELECTRICITY_METER: "Electricity meter",
    C.SUPLA_CHANNELFNC_IC_GAS_METER: "Gas meter",
    C.SUPLA_CHANNELFNC_IC_WATER_METER: "Water meter",
    C.SUPLA_CHANNELFNC_IC_HEAT_METER: "Heat meter",
    C.SUPLA_CHANNELFNC_IC_EVENTS: "Events",
    C.SUPLA_CHANNELFNC_IC_SECONDS: "Runtime",
    C.SUPLA_CHANNELFNC_THERMOSTAT_HEATPOL_HOMEPLUS: "Thermostat",
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT: "Thermostat",
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_HEAT_COOL: "Thermostat",
    C.SUPLA_CHANNELFNC_HVAC_DRYER: "Dryer",
    C.SUPLA_CHANNELFNC_HVAC_FAN: "Fan",
    C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT_DIFFERENTIAL: "Differential thermostat",
    C.SUPLA_CHANNELFNC_HVAC_DOMESTIC_HOT_WATER: "Hot water",
    C.SUPLA_CHANNELFNC_HVAC_HRV: "Heat recovery",
    C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE: "Valve",
    C.SUPLA_CHANNELFNC_VALVE_PERCENTAGE: "Valve",
    C.SUPLA_CHANNELFNC_GENERAL_PURPOSE_MEASUREMENT: "Measurement",
    C.SUPLA_CHANNELFNC_GENERAL_PURPOSE_METER: "Meter",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEENGINESPEED: "Engine speed",
    C.SUPLA_CHANNELFNC_ACTIONTRIGGER: "Button",
    C.SUPLA_CHANNELFNC_DIGIGLASS_HORIZONTAL: "Digiglass",
    C.SUPLA_CHANNELFNC_DIGIGLASS_VERTICAL: "Digiglass",
    C.SUPLA_CHANNELFNC_CONTROLLINGTHEFACADEBLIND: "Facade blind",
    C.SUPLA_CHANNELFNC_TERRACE_AWNING: "Awning",
    C.SUPLA_CHANNELFNC_PROJECTOR_SCREEN: "Projector screen",
    C.SUPLA_CHANNELFNC_CURTAIN: "Curtain",
    C.SUPLA_CHANNELFNC_VERTICAL_BLIND: "Vertical blind",
    C.SUPLA_CHANNELFNC_ROLLER_GARAGE_DOOR: "Garage door",
    C.SUPLA_CHANNELFNC_PUMPSWITCH: "Pump",
    C.SUPLA_CHANNELFNC_HEATORCOLDSOURCESWITCH: "Heat source",
    C.SUPLA_CHANNELFNC_CONTAINER: "Container",
    C.SUPLA_CHANNELFNC_SEPTIC_TANK: "Septic tank",
    C.SUPLA_CHANNELFNC_WATER_TANK: "Water tank",
    C.SUPLA_CHANNELFNC_CONTAINER_LEVEL_SENSOR: "Container level",
    C.SUPLA_CHANNELFNC_FLOOD_SENSOR: "Flood",
    C.SUPLA_CHANNELFNC_MOTION_SENSOR: "Motion",
    C.SUPLA_CHANNELFNC_BINARY_SENSOR: "Sensor",
}

#: Used when a channel has no assigned function yet (function == 0).
KIND_LABELS: Final[dict[str, str]] = {
    "relay": "Relay",
    "roller_shutter": "Roller shutter",
    "facade_blind": "Facade blind",
    "dimmer": "Dimmer",
    "rgb": "RGB light",
    "dimmer_rgb": "RGB light",
    "thermometer": "Temperature",
    "humidity": "Humidity",
    "temperature_humidity": "Climate",
    "measurement": "Measurement",
    "binary_sensor": "Sensor",
    "electricity_meter": "Energy",
    "impulse_counter": "Counter",
    "valve_open_close": "Valve",
    "valve_percentage": "Valve",
    "hvac": "Thermostat",
    "thermostat_heatpol": "Thermostat",
    "digiglass": "Digiglass",
    "container": "Container",
    "engine_speed": "Engine speed",
    "action_trigger": "Button",
}
