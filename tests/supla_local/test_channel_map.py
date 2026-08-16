"""The channel -> entity mapping, on its own."""

from __future__ import annotations

import pytest

from custom_components.supla_local import channel_map as cm
from custom_components.supla_local.models import ChannelSnapshot, DeviceSnapshot
from custom_components.supla_local.server import consts as C


def channel(number: int = 0, **kwargs) -> ChannelSnapshot:
    kwargs.setdefault("type", 0)
    kwargs.setdefault("function", 0)
    return ChannelSnapshot(number=number, **kwargs)


@pytest.mark.parametrize(
    ("function", "platform"),
    [
        (C.SUPLA_CHANNELFNC_LIGHTSWITCH, cm.LIGHT),
        (C.SUPLA_CHANNELFNC_POWERSWITCH, cm.SWITCH),
        (C.SUPLA_CHANNELFNC_STAIRCASETIMER, cm.SWITCH),
        (C.SUPLA_CHANNELFNC_PUMPSWITCH, cm.SWITCH),
        (C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE, cm.COVER),
        (C.SUPLA_CHANNELFNC_CONTROLLINGTHEGARAGEDOOR, cm.COVER),
        (C.SUPLA_CHANNELFNC_CONTROLLINGTHEDOORLOCK, cm.LOCK),
        (C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATEWAYLOCK, cm.LOCK),
    ],
)
def test_relay_functions_pick_their_platform(function: int, platform: str) -> None:
    keys = cm.entity_keys(channel(type=C.SUPLA_CHANNELTYPE_RELAY, function=function))
    assert [key.platform for key in keys] == [platform]


def test_relay_without_a_function_falls_back_to_a_switch() -> None:
    keys = cm.entity_keys(channel(type=C.SUPLA_CHANNELTYPE_RELAY))
    assert [key.platform for key in keys] == [cm.SWITCH]


def test_temperature_and_humidity_channel_makes_two_sensors() -> None:
    keys = cm.entity_keys(
        channel(4, function=C.SUPLA_CHANNELFNC_HUMIDITYANDTEMPERATURE)
    )
    assert [(key.platform, key.suffix) for key in keys] == [
        (cm.SENSOR, "4-temperature"),
        (cm.SENSOR, "4-humidity"),
    ]


def test_rgbw_channel_makes_a_colour_and_a_white_light() -> None:
    keys = cm.entity_keys(
        channel(2, function=C.SUPLA_CHANNELFNC_DIMMERANDRGBLIGHTING)
    )
    assert [(key.platform, key.suffix) for key in keys] == [
        (cm.LIGHT, "2"),
        (cm.LIGHT, "2-white"),
    ]


def test_phase_sensors_appear_only_once_the_meter_has_reported_them() -> None:
    plain = channel(5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER)
    assert [key.suffix for key in cm.entity_keys(plain)] == ["5"]

    three_phase = channel(
        5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER, em_phases=3
    )
    assert [key.suffix for key in cm.entity_keys(three_phase)] == [
        "5",
        "5-phase-1",
        "5-phase-2",
        "5-phase-3",
    ]


def test_unknown_channels_produce_nothing() -> None:
    assert cm.entity_keys(channel(9, type=424242)) == []


def test_the_primary_entity_keeps_the_bare_unique_id() -> None:
    key = cm.entity_keys(channel(7, function=C.SUPLA_CHANNELFNC_VALVE_OPENCLOSE))[0]
    assert cm.unique_id("ABCD", key.suffix) == "ABCD-7"


def test_device_unique_ids_include_the_connectivity_entity() -> None:
    device = DeviceSnapshot(
        guid="ABCD",
        channels=(channel(1, function=C.SUPLA_CHANNELFNC_POWERSWITCH),),
    )
    assert cm.device_unique_ids(device) == {"ABCD-connectivity", "ABCD-1"}


def test_a_pulse_relay_pairs_with_the_nearest_matching_opening_sensor() -> None:
    gate = channel(3, function=C.SUPLA_CHANNELFNC_CONTROLLINGTHEGATE)
    device = DeviceSnapshot(
        guid="ABCD",
        channels=(
            channel(0, function=C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE),
            gate,
            channel(4, function=C.SUPLA_CHANNELFNC_OPENINGSENSOR_GATE),
            channel(5, function=C.SUPLA_CHANNELFNC_OPENINGSENSOR_DOOR),
        ),
    )
    assert cm.find_opening_sensor(device, gate) == 4


def test_pairing_prefers_the_same_sub_device_over_a_closer_number() -> None:
    thermostat = ChannelSnapshot(
        number=10, type=0, function=C.SUPLA_CHANNELFNC_HVAC_THERMOSTAT, sub_device_id=2
    )
    device = DeviceSnapshot(
        guid="ABCD",
        channels=(
            ChannelSnapshot(
                number=9, type=0, function=C.SUPLA_CHANNELFNC_THERMOMETER
            ),
            ChannelSnapshot(
                number=20,
                type=0,
                function=C.SUPLA_CHANNELFNC_THERMOMETER,
                sub_device_id=2,
            ),
            thermostat,
        ),
    )
    assert cm.find_thermometer(device, thermostat) == 20


def test_merge_keeps_extended_value_discoveries_across_re_registration() -> None:
    stored = DeviceSnapshot(
        guid="ABCD",
        channels=(
            channel(5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER, em_phases=3),
        ),
    )
    # A re-registration carries the channel list but no extended value yet.
    fresh = DeviceSnapshot(
        guid="ABCD",
        name="Renamed",
        channels=(channel(5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER),),
    )
    merged = stored.merge(fresh)
    assert merged.name == "Renamed"
    assert merged.channels[0].em_phases == 3


def test_merge_drops_stale_extras_when_the_channel_changes_kind() -> None:
    stored = DeviceSnapshot(
        guid="ABCD",
        channels=(
            channel(5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER, em_phases=3),
        ),
    )
    fresh = DeviceSnapshot(
        guid="ABCD",
        channels=(channel(5, function=C.SUPLA_CHANNELFNC_POWERSWITCH),),
    )
    assert stored.merge(fresh).channels[0].em_phases == 0


def test_snapshots_round_trip_through_json() -> None:
    device = DeviceSnapshot(
        guid="ABCD",
        name="Fake",
        soft_ver="1.2.3",
        manufacturer_id=1,
        product_id=2,
        proto_version=25,
        channels=(
            channel(5, function=C.SUPLA_CHANNELFNC_ELECTRICITY_METER, em_phases=3),
            channel(6, function=C.SUPLA_CHANNELFNC_IC_WATER_METER, ic_calculated=True),
        ),
    )
    assert DeviceSnapshot.from_json(device.to_json()) == device
