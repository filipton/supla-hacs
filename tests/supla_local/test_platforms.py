"""One device per channel kind, checking what each platform reads and sends."""

from __future__ import annotations

import struct

from conftest import GUID_HEX, entity_id_for, nth_command, wait_for
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.supla_local.const import DOMAIN
from custom_components.supla_local.server import consts as C


def ch(number: int, type_: int, function: int, value: bytes = bytes(8)):
    return (number, type_, function, value)


async def test_a_door_lock_reads_its_opening_sensor(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK),
            ch(
                1,
                C.SUPLA_CHANNELTYPE_BINARYSENSOR,
                C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR,
            ),
        ]
    )
    entity_id = entity_id_for(hass, "lock", "0")
    await wait_for(lambda: hass.states.get(entity_id).state == "locked")

    await hass.services.async_call(
        "lock", "open", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert await nth_command(device, 0) == b"\x01" + bytes(7)

    await device.report_value(1, b"\x01" + bytes(7))
    await wait_for(lambda: hass.states.get(entity_id).state == "unlocked")


async def test_a_gate_pulses_only_when_it_needs_to(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE),
            ch(
                1,
                C.SUPLA_CHANNELTYPE_BINARYSENSOR,
                C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE,
            ),
        ]
    )
    entity_id = entity_id_for(hass, "cover", "0")
    await wait_for(lambda: hass.states.get(entity_id).state == "closed")
    assert hass.states.get(entity_id).attributes["device_class"] == "gate"

    await hass.services.async_call(
        "cover", "open_cover", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert await nth_command(device, 0) == b"\x01" + bytes(7)

    await device.report_value(1, b"\x01" + bytes(7))
    await wait_for(lambda: hass.states.get(entity_id).state == "open")

    # Already open: pulsing again would close it.
    await hass.services.async_call(
        "cover", "open_cover", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert len([n for n, _ in device.commands if n == 0]) == 1


async def test_facade_blind_tilt_is_inverted(hass: HomeAssistant, connect) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_RELAY,
                C.SUPLA_CHANNELFNC_CONTROLLINGTHEFACADEBLIND,
            )
        ]
    )
    entity_id = entity_id_for(hass, "cover", "0")

    await hass.services.async_call(
        "cover",
        "set_cover_tilt_position",
        {ATTR_ENTITY_ID: entity_id, "tilt_position": 25},
        blocking=True,
    )
    position, tilt = struct.unpack_from("<bb", await nth_command(device, 0))
    assert position == -1  # tilt only
    assert tilt == 75 + C.RS_POSITION_OFFSET

    await device.report_value(0, bytes([40, 30, 0, 0, 0, 0, 0, 0]))
    await wait_for(
        lambda: hass.states.get(entity_id).attributes.get("current_tilt_position") == 70
    )
    assert hass.states.get(entity_id).attributes["current_position"] == 60


async def test_a_percentage_valve_reports_how_open_it_is(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_VALVE_PERCENTAGE,
                C.SUPLA_CHANNELFNC_VALVE_PERCENTAGE,
            )
        ]
    )
    entity_id = entity_id_for(hass, "valve", "0")

    await hass.services.async_call(
        "valve",
        "set_valve_position",
        {ATTR_ENTITY_ID: entity_id, "position": 25},
        blocking=True,
    )
    assert (await nth_command(device, 0))[0] == 75  # SUPLA counts closed percent

    await device.report_value(0, bytes([80, 0, 0, 0, 0, 0, 0, 0]))
    await wait_for(
        lambda: hass.states.get(entity_id).attributes.get("current_position") == 20
    )


async def test_an_open_close_valve_flags_flooding(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [ch(0, C.SUPLA_CHANNELTYPE_VALVE_OPENCLOSE, C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE)]
    )
    entity_id = entity_id_for(hass, "valve", "0")

    await device.report_value(0, bytes([1, 1, 0, 0, 0, 0, 0, 0]))
    await wait_for(lambda: hass.states.get(entity_id).state == "closed")
    assert hass.states.get(entity_id).attributes["flooding"] is True


async def test_engine_speed_is_a_number(hass: HomeAssistant, connect) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_ENGINE,
                C.SUPLA_CHANNELFNC_CONTROLLINGTHEENGINESPEED,
            )
        ]
    )
    entity_id = entity_id_for(hass, "number", "0")

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id, "value": 40},
        blocking=True,
    )
    assert (await nth_command(device, 0))[0] == 40
    await wait_for(lambda: float(hass.states.get(entity_id).state) == 40)


async def test_an_rgb_light_sends_colour_and_brightness_together(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_RGBLEDCONTROLLER,
                C.SUPLA_CHANNELFNC_RGBLIGHTING,
            )
        ]
    )
    entity_id = entity_id_for(hass, "light", "0")

    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: entity_id, "rgb_color": [255, 0, 0], "brightness": 255},
        blocking=True,
    )
    value = await nth_command(device, 0)
    _dimmer, color_brightness, blue, green, red, _on_off, command, _white = (
        struct.unpack("<BBBBBbbB", value)
    )
    assert (red, green, blue) == (255, 0, 0)
    assert color_brightness == 100
    assert command == C.RGBW_COMMAND_TURN_ON_RGB

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes["rgb_color"] == (255, 0, 0)


async def test_an_rgbw_channel_drives_its_two_halves_independently(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_DIMMERANDRGBLED,
                C.SUPLA_CHANNELFNC_DIMMERANDRGBLIGHTING,
            )
        ]
    )
    colour = entity_id_for(hass, "light", "0")
    white = entity_id_for(hass, "light", "0-white")

    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: white, "brightness": 255}, blocking=True
    )
    value = await nth_command(device, 0)
    assert value[0] == 100  # white dimmer
    assert value[1] == 0  # colour untouched
    assert value[6] == C.RGBW_COMMAND_TURN_ON_DIMMER

    # The white half being lit must not make the colour half look on.
    await wait_for(lambda: hass.states.get(white).state == STATE_ON)
    assert hass.states.get(colour).state == STATE_OFF


async def test_a_combined_probe_makes_two_sensors(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_HUMIDITYANDTEMPSENSOR,
                C.SUPLA_CHANNELFNC_HUMIDITYANDTEMPERATURE,
            )
        ]
    )
    temperature = entity_id_for(hass, "sensor", "0-temperature")
    humidity = entity_id_for(hass, "sensor", "0-humidity")

    await device.report_value(0, struct.pack("<ii", 21_500, 48_000))
    await wait_for(lambda: hass.states.get(temperature).state == "21.5")
    assert hass.states.get(humidity).state == "48.0"


async def test_a_disconnected_probe_reads_as_unknown(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [ch(0, C.SUPLA_CHANNELTYPE_THERMOMETER, C.SUPLA_CHANNELFNC_THERMOMETER)]
    )
    entity_id = entity_id_for(hass, "sensor", "0")
    await device.report_value(0, struct.pack("<d", -275.0))
    await wait_for(lambda: hass.states.get(entity_id).state == "unknown")


async def test_a_tank_reports_its_level_in_percent(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [ch(0, C.SUPLA_CHANNELTYPE_CONTAINER, C.SUPLA_CHANNELFNC_WATER_TANK)]
    )
    entity_id = entity_id_for(hass, "sensor", "0")
    # SUPLA encodes 0 as "no reading" and 1..101 as 0..100%.
    await device.report_value(0, bytes([51, 0, 0, 0, 0, 0, 0, 0]))
    await wait_for(lambda: hass.states.get(entity_id).state == "50")
    assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "%"


async def test_an_impulse_counter_gains_its_scaled_reading(
    hass: HomeAssistant, connect
) -> None:
    registry = er.async_get(hass)
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_IMPULSE_COUNTER,
                C.SUPLA_CHANNELFNC_IC_WATER_METER,
            )
        ]
    )
    assert entity_id_for(hass, "sensor", "0")
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-0-calculated")
        is None
    )

    payload = (
        struct.pack("<ii", 1234, 5000) + bytes(20) + struct.pack("<Qq", 42, 12_345)
    )
    await device.report_extended(
        0, C.EV_TYPE_IMPULSE_COUNTER_DETAILS_V1, payload
    )
    await wait_for(
        lambda: registry.async_get_entity_id(
            "sensor", DOMAIN, f"{GUID_HEX}-0-calculated"
        )
        is not None
    )
    calculated = entity_id_for(hass, "sensor", "0-calculated")
    assert hass.states.get(calculated).state == "12.345"
    assert hass.states.get(calculated).attributes["unit_of_measurement"] == "m³"


async def test_digiglass_is_a_switch(hass: HomeAssistant, connect) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_DIGIGLASS,
                C.SUPLA_CHANNELFNC_DIGIGLASS_VERTICAL,
            )
        ]
    )
    entity_id = entity_id_for(hass, "switch", "0")

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mask, active = struct.unpack_from("<HH", await nth_command(device, 0))
    assert (mask, active) == (0xFFFF, 0xFFFF)

    await device.report_value(0, bytes([0, 2]) + struct.pack("<H", 0b11) + bytes(4))
    await wait_for(lambda: hass.states.get(entity_id).state == STATE_ON)
    assert hass.states.get(entity_id).attributes["section_count"] == 2


async def test_a_heatpol_thermostat_sets_its_own_setpoint(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [
            ch(
                0,
                C.SUPLA_CHANNELTYPE_THERMOSTAT_HEATPOL_HOMEPLUS,
                C.SUPLA_CHANNELFNC_THERMOSTAT_HEATPOL_HOMEPLUS,
            )
        ]
    )
    entity_id = entity_id_for(hass, "climate", "0")

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, "temperature": 22.0},
        blocking=True,
    )
    is_on, _flags, _measured, preset = struct.unpack_from(
        "<BBhh", await nth_command(device, 0)
    )
    assert is_on == 1
    assert preset == 2200

    await device.report_value(0, struct.pack("<BBhh", 1, 0, 2105, 2200) + bytes(2))
    await wait_for(lambda: hass.states.get(entity_id).state == "heat")
    state = hass.states.get(entity_id)
    # Home Assistant renders Celsius to tenths.
    assert state.attributes["current_temperature"] == 21.1
    assert state.attributes["temperature"] == 22.0


async def test_an_hvac_thermostat_reports_what_it_is_doing(
    hass: HomeAssistant, connect
) -> None:
    device = await connect(
        [ch(0, C.SUPLA_CHANNELTYPE_HVAC, C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT)]
    )
    entity_id = entity_id_for(hass, "climate", "0")

    flags = (
        C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET
        | C.SUPLA_HVAC_VALUE_FLAG_HEATING
    )
    await device.report_value(
        0, struct.pack("<BBhhH", 1, C.SUPLA_HVAC_MODE_HEAT, 2150, 0, flags)
    )
    await wait_for(lambda: hass.states.get(entity_id).state == "heat")
    state = hass.states.get(entity_id)
    assert state.attributes["hvac_action"] == "heating"
    assert state.attributes["temperature"] == 21.5
    assert state.attributes["preset_mode"] == "manual"

    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, "preset_mode": "schedule"},
        blocking=True,
    )
    _is_on, mode, _heat, _cool, _flags = struct.unpack(
        "<BBhhH", await nth_command(device, 0)
    )
    assert mode == C.SUPLA_HVAC_MODE_CMD_WEEKLY_SCHEDULE


async def test_an_unassigned_channel_still_gets_a_switch(
    hass: HomeAssistant, connect
) -> None:
    """Function 0 means "not configured yet"; fall back to the hardware type."""
    await connect([ch(0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_NONE)])
    assert entity_id_for(hass, "switch", "0")


async def test_an_unsupported_channel_is_ignored(
    hass: HomeAssistant, connect
) -> None:
    await connect(
        [
            ch(0, C.SUPLA_CHANNELTYPE_BRIDGE, C.SUPLA_CHANNELFNC_NONE),
            ch(1, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_POWERSWITCH),
        ]
    )
    registry = er.async_get(hass)
    assert entity_id_for(hass, "switch", "1")
    assert not [
        entry
        for entry in registry.entities.values()
        if entry.unique_id == f"{GUID_HEX}-0" and entry.platform == DOMAIN
    ]
