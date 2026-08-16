"""End to end: a real device over a real socket, driven from Home Assistant."""

from __future__ import annotations

import asyncio
import struct

import pytest
from conftest import GUID_HEX, entity_id_for, flush_store, nth_command, wait_for
from fake_device import FakeDevice
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.supla_local.const import (
    CONF_ENABLE_TLS,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DOMAIN,
    EVENT_ACTION_TRIGGER,
    STORAGE_KEY,
)
from custom_components.supla_local.server import consts as C


async def test_a_connecting_device_creates_its_entities(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    """Every channel of the fake device lands on the right platform."""
    registry = er.async_get(hass)
    await wait_for(lambda: registry.async_get_entity_id("switch", DOMAIN, f"{GUID_HEX}-1"))

    expected = {
        ("light", "0"),  # LIGHTSWITCH relay
        ("switch", "1"),  # POWERSWITCH relay
        ("light", "2"),  # dimmer
        ("cover", "3"),  # roller shutter on a relay
        ("sensor", "4"),  # thermometer
        ("climate", "5"),  # HVAC
        ("binary_sensor", "6"),  # door sensor
        ("valve", "7"),  # open/close valve
        ("event", "8"),  # action trigger
        ("binary_sensor", "connectivity"),  # device level
    }
    for platform, suffix in expected:
        assert registry.async_get_entity_id(platform, DOMAIN, f"{GUID_HEX}-{suffix}")


async def test_the_device_is_registered_with_its_own_metadata(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entry = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, GUID_HEX)})
    assert entry is not None
    assert entry.name == "Fake Device"
    assert entry.sw_version == "1.2.3"
    assert entry.manufacturer == "SUPLA"
    assert entry.serial_number == GUID_HEX


async def test_turning_a_switch_on_reaches_the_device(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "switch", "1")
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert await nth_command(device, 1) == b"\x01" + bytes(7)
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert await nth_command(device, 1, 1) == bytes(8)


async def test_state_changed_at_the_wall_switch_shows_up(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "switch", "1")
    assert hass.states.get(entity_id).state == STATE_OFF

    await device.report_value(1, b"\x01" + bytes(7))
    await wait_for(lambda: hass.states.get(entity_id).state == STATE_ON)


async def test_dimmer_brightness_is_scaled_to_percent(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "light", "2")
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: entity_id, "brightness": 128},
        blocking=True,
    )
    value = await nth_command(device, 2)
    assert value[0] == 50  # 128/255 of full scale
    assert value[6] == C.RGBW_COMMAND_TURN_ON_DIMMER
    assert hass.states.get(entity_id).attributes["brightness"] == 128


async def test_cover_position_is_inverted_on_the_way_out(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    """Home Assistant 30% open is SUPLA 70 closed, offset by the command base."""
    entity_id = entity_id_for(hass, "cover", "3")
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {ATTR_ENTITY_ID: entity_id, "position": 30},
        blocking=True,
    )
    assert (await nth_command(device, 3))[0] == 70 + C.RS_POSITION_OFFSET

    await hass.services.async_call(
        "cover", "open_cover", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert (await nth_command(device, 3, 1))[0] == C.RS_CMD_UP


async def test_cover_position_is_inverted_on_the_way_in(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "cover", "3")

    await device.report_value(3, bytes([100, 0, 0, 0, 0, 0, 0, 0]))
    await wait_for(lambda: hass.states.get(entity_id).state == "closed")
    assert hass.states.get(entity_id).attributes["current_position"] == 0

    await device.report_value(3, bytes(8))
    await wait_for(lambda: hass.states.get(entity_id).state == "open")
    assert hass.states.get(entity_id).attributes["current_position"] == 100


async def test_calibrating_covers_report_no_position(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "cover", "3")
    await device.report_value(3, struct.pack("<b", -1) + bytes(7))
    await wait_for(
        lambda: hass.states.get(entity_id).attributes.get("calibrating") is True
    )
    # Home Assistant omits the attribute entirely when the position is unknown.
    assert "current_position" not in hass.states.get(entity_id).attributes


async def test_the_thermostat_reads_the_nearby_thermometer(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "climate", "5")
    await wait_for(
        lambda: hass.states.get(entity_id).attributes.get("current_temperature") == 20.5
    )


async def test_setting_a_thermostat_setpoint(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "climate", "5")
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, "temperature": 21.5},
        blocking=True,
    )
    value = await nth_command(device, 5)
    _is_on, mode, setpoint_heat, _cool, flags = struct.unpack("<BBhhH", value)
    assert mode == C.SUPLA_HVAC_MODE_NOT_SET
    assert setpoint_heat == 2150
    assert flags & C.SUPLA_HVAC_VALUE_FLAG_SETPOINT_TEMP_HEAT_SET


async def test_a_button_press_becomes_an_event(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "event", "8")
    events = async_capture_events(hass, EVENT_ACTION_TRIGGER)

    await device.press(8, 1 << 8)  # SUPLA_ACTION_CAP_SHORT_PRESS_x1
    await wait_for(lambda: bool(events))
    assert events[0].data["actions"] == ["press_x1"]
    assert events[0].data["channel"] == 8

    await wait_for(
        lambda: hass.states.get(entity_id).attributes.get("event_type") == "press_x1"
    )


async def test_a_repeated_button_press_fires_again(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    """The bitmask does not change between two identical presses."""
    events = async_capture_events(hass, EVENT_ACTION_TRIGGER)
    await device.press(8, 1 << 8)
    await device.press(8, 1 << 8)
    await wait_for(lambda: len(events) == 2)


async def test_entities_go_unavailable_when_the_device_drops_off(
    hass: HomeAssistant, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "switch", "1")
    connectivity = entity_id_for(hass, "binary_sensor", "connectivity")
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    await device.close()
    await wait_for(lambda: hass.states.get(entity_id).state == STATE_UNAVAILABLE)
    # The connectivity entity is the one thing that stays readable.
    assert hass.states.get(connectivity).state == STATE_OFF


async def test_reconnecting_does_not_duplicate_entities(
    hass: HomeAssistant, entry: MockConfigEntry, port: int, device: FakeDevice
) -> None:
    entity_id = entity_id_for(hass, "switch", "1")
    await device.close()
    await wait_for(lambda: hass.states.get(entity_id).state == STATE_UNAVAILABLE)

    again = FakeDevice()
    await again.connect(port)
    try:
        await wait_for(lambda: hass.states.get(entity_id).state != STATE_UNAVAILABLE)
        assert entity_id_for(hass, "switch", "1") == entity_id
        assert not hass.states.async_entity_ids("switch.fake_device_power_1_2")
    finally:
        await again.close()


async def test_channels_that_disappear_take_their_entities_with_them(
    hass: HomeAssistant, port: int, device: FakeDevice
) -> None:
    registry = er.async_get(hass)
    assert entity_id_for(hass, "switch", "1")
    await device.close()

    smaller = FakeDevice()
    await smaller.connect(
        port,
        channels=[(0, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_LIGHTSWITCH, bytes(8))],
    )
    try:
        await wait_for(
            lambda: registry.async_get_entity_id("switch", DOMAIN, f"{GUID_HEX}-1")
            is None
        )
        assert registry.async_get_entity_id("light", DOMAIN, f"{GUID_HEX}-0")
    finally:
        await smaller.close()


async def test_a_channel_that_changes_platform_moves_rather_than_doubles(
    hass: HomeAssistant, port: int, device: FakeDevice
) -> None:
    """Reassigning channel 1 from power switch to light switch."""
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", DOMAIN, f"{GUID_HEX}-1")
    await device.close()

    changed = FakeDevice()
    await changed.connect(
        port,
        channels=[(1, C.SUPLA_CHANNELTYPE_RELAY, C.SUPLA_CHANNELFNC_LIGHTSWITCH, bytes(8))],
    )
    try:
        await wait_for(
            lambda: registry.async_get_entity_id("light", DOMAIN, f"{GUID_HEX}-1")
            is not None
        )
        assert registry.async_get_entity_id("switch", DOMAIN, f"{GUID_HEX}-1") is None
    finally:
        await changed.close()


async def test_seen_devices_are_persisted(
    hass: HomeAssistant, device: FakeDevice, hass_storage: dict
) -> None:
    await flush_store(hass)

    stored = hass_storage[STORAGE_KEY]["data"]["devices"][GUID_HEX]
    assert stored["name"] == "Fake Device"
    assert {channel["number"] for channel in stored["channels"]} == set(range(9))
    # Values are deliberately not persisted; a restored entity is unavailable,
    # never showing a reading from before the restart.
    assert "value" not in stored["channels"][0]


@pytest.fixture
def stored_device(hass_storage: dict) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "devices": {
                GUID_HEX: {
                    "guid": GUID_HEX,
                    "name": "Fake Device",
                    "soft_ver": "1.2.3",
                    "manufacturer_id": 1,
                    "product_id": 2,
                    "proto_version": 25,
                    "channels": [
                        {
                            "number": 1,
                            "type": C.SUPLA_CHANNELTYPE_RELAY,
                            "function": C.SUPLA_CHANNELFNC_POWERSWITCH,
                        }
                    ],
                    "sub_devices": [],
                }
            }
        },
    }


async def test_entities_come_back_before_the_device_reconnects(
    hass: HomeAssistant, stored_device: None, port: int
) -> None:
    """After a restart the entities exist immediately, marked unavailable."""
    entity_id = entity_id_for(hass, "switch", "1")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, GUID_HEX)})


async def test_a_restored_entity_becomes_live_when_its_device_dials_in(
    hass: HomeAssistant, stored_device: None, port: int
) -> None:
    entity_id = entity_id_for(hass, "switch", "1")
    device = FakeDevice()
    await device.connect(port)
    try:
        await wait_for(lambda: hass.states.get(entity_id).state == STATE_OFF)
    finally:
        await device.close()


async def test_unloading_the_entry_frees_the_port(
    hass: HomeAssistant, entry: MockConfigEntry, port: int
) -> None:
    manager = entry.runtime_data  # cleared by Home Assistant on unload
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not manager.running
    assert manager.bound_ports == []


METER_CHANNEL = [
    (
        0,
        C.SUPLA_CHANNELTYPE_ELECTRICITY_METER,
        C.SUPLA_CHANNELFNC_ELECTRICITY_METER,
        bytes(8),
    )
]


async def test_meter_phases_appear_once_the_device_reports_them(
    hass: HomeAssistant, port: int
) -> None:
    """Per-phase energy is only visible in the extended value."""
    registry = er.async_get(hass)
    device = FakeDevice()
    await device.connect(port, channels=METER_CHANNEL)
    try:
        await wait_for(
            lambda: registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-0")
        )
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-0-phase-1")
            is None
        )

        await device.report_extended(
            0,
            C.EV_TYPE_ELECTRICITY_METER_MEASUREMENT_V3,
            struct.pack("<QQQ", 100_000, 200_000, 300_000),
        )
        await wait_for(
            lambda: registry.async_get_entity_id(
                "sensor", DOMAIN, f"{GUID_HEX}-0-phase-3"
            )
            is not None
        )
        assert hass.states.get(entity_id_for(hass, "sensor", "0-phase-2")).state == "2.0"
    finally:
        await device.close()


async def test_meter_phases_survive_a_re_registration(
    hass: HomeAssistant, port: int
) -> None:
    """Re-registration carries the channel list but no extended value yet."""
    registry = er.async_get(hass)
    device = FakeDevice()
    await device.connect(port, channels=METER_CHANNEL)
    await device.report_extended(
        0,
        C.EV_TYPE_ELECTRICITY_METER_MEASUREMENT_V3,
        struct.pack("<QQQ", 100_000, 200_000, 300_000),
    )
    await wait_for(
        lambda: registry.async_get_entity_id("sensor", DOMAIN, f"{GUID_HEX}-0-phase-3")
        is not None
    )
    await device.close()

    again = FakeDevice()
    await again.connect(port, channels=METER_CHANNEL)
    try:
        entity_id = entity_id_for(hass, "sensor", "0-phase-3")
        await wait_for(
            lambda: hass.states.get(entity_id).state != STATE_UNAVAILABLE
        )
    finally:
        await again.close()


async def test_tls_is_served_with_a_generated_certificate(
    hass: HomeAssistant, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TCP_PORT: 0, CONF_ENABLE_TLS: True, CONF_TLS_PORT: 0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(entry.runtime_data.bound_ports) == 2
    assert (tmp_path / "supla_local" / "server.crt").is_file()
    assert (tmp_path / "supla_local" / "server.key").is_file()


async def test_a_connected_device_cannot_be_deleted(
    hass: HomeAssistant, entry: MockConfigEntry, device: FakeDevice
) -> None:
    """It would just re-register and come back a second later."""
    from custom_components.supla_local import async_remove_config_entry_device

    device_entry = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, GUID_HEX)})
    assert not await async_remove_config_entry_device(hass, entry, device_entry)

    await device.close()
    await wait_for(lambda: not entry.runtime_data.registry.get(GUID_HEX).online)
    assert await async_remove_config_entry_device(hass, entry, device_entry)
    assert GUID_HEX not in entry.runtime_data.devices


async def test_diagnostics_describe_the_device_tree(
    hass: HomeAssistant, entry: MockConfigEntry, device: FakeDevice
) -> None:
    from homeassistant.components.diagnostics import REDACTED
    from homeassistant.helpers.json import json_dumps

    from custom_components.supla_local.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["server"]["running"] is True
    assert data["server"]["bound_ports"]

    reported = data["devices"][0]
    assert reported["online"] is True
    assert reported["stored"]["name"] == "Fake Device"
    assert reported["live"]["email"] == REDACTED
    assert {entity["platform"] for entity in reported["entities"]} >= {
        "light",
        "switch",
        "cover",
    }
    # The download endpoint serialises with Home Assistant's encoder.
    assert json_dumps(data)


async def test_unloading_while_a_device_is_connected(
    hass: HomeAssistant, entry: MockConfigEntry, device: FakeDevice
) -> None:
    """Shutdown must not wait on the device's own connection to end by itself."""
    manager = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert manager.bound_ports == []
    await asyncio.wait_for(device.wait_closed(), timeout=5)


async def test_reloading_rebinds_the_same_port(
    hass: HomeAssistant, entry: MockConfigEntry, port: int, device: FakeDevice
) -> None:
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TCP_PORT: port})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.bound_ports == [port]

    again = FakeDevice()
    await again.connect(port)
    try:
        entity_id = entity_id_for(hass, "switch", "1")
        await wait_for(lambda: hass.states.get(entity_id).state != STATE_UNAVAILABLE)
    finally:
        await again.close()
