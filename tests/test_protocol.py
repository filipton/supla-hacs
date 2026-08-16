"""Protocol framing and register decode tests."""

from __future__ import annotations

import struct

from supla_server.consts import (
    SUPLA_CHANNELVALUE_SIZE,
    SUPLA_DEVICE_NAME_MAXSIZE,
    SUPLA_DS_CALL_REGISTER_DEVICE_B,
    SUPLA_DS_CALL_REGISTER_DEVICE_E,
    SUPLA_EMAIL_MAXSIZE,
    SUPLA_GUID_SIZE,
    SUPLA_LOCATION_PWD_MAXSIZE,
    SUPLA_PROTO_VERSION,
    SUPLA_RESULTCODE_TRUE,
    SUPLA_SD_CALL_REGISTER_DEVICE_RESULT,
    SUPLA_SERVER_NAME_MAXSIZE,
    SUPLA_SOFTVER_MAXSIZE,
    SUPLA_TAG,
)
from supla_server.protocol import (
    SuplaPacket,
    decode_register_device,
    encode_packet,
    encode_register_device_result,
    try_decode_packet,
)


def _pad(value: bytes, size: int) -> bytes:
    return value + b"\x00" * (size - len(value))


def test_packet_round_trip() -> None:
    original = SuplaPacket(
        version=12,
        rr_id=7,
        call_id=SUPLA_SD_CALL_REGISTER_DEVICE_RESULT,
        data=encode_register_device_result(
            result_code=SUPLA_RESULTCODE_TRUE,
            activity_timeout=100,
            version=12,
            version_min=1,
        ),
    )
    raw = encode_packet(original)
    assert raw.startswith(SUPLA_TAG)
    assert raw.endswith(SUPLA_TAG)

    decoded, consumed = try_decode_packet(raw)
    assert decoded is not None
    assert consumed == len(raw)
    assert decoded.version == original.version
    assert decoded.rr_id == original.rr_id
    assert decoded.call_id == original.call_id
    assert decoded.data == original.data


def test_packet_needs_more_data() -> None:
    packet = SuplaPacket(version=1, rr_id=1, call_id=40, data=b"\x00" * 16)
    raw = encode_packet(packet)
    partial, consumed = try_decode_packet(raw[:10])
    assert partial is None
    assert consumed == 0


def test_decode_register_device_b() -> None:
    guid = bytes(range(SUPLA_GUID_SIZE))
    channel_value = bytes([1]) + bytes(SUPLA_CHANNELVALUE_SIZE - 1)
    # Number + Type + FuncList + Default + value
    channel = (
        bytes([0])
        + struct.pack("<iii", 2900, 0, 140)
        + channel_value
    )
    payload = (
        struct.pack("<i", 1)
        + _pad(b"secret", SUPLA_LOCATION_PWD_MAXSIZE)
        + guid
        + _pad(b"Test Relay", SUPLA_DEVICE_NAME_MAXSIZE)
        + _pad(b"2.0", SUPLA_SOFTVER_MAXSIZE)
        + bytes([1])
        + channel
    )
    reg = decode_register_device(SUPLA_DS_CALL_REGISTER_DEVICE_B, payload)
    assert reg.guid == guid
    assert reg.name == "Test Relay"
    assert reg.soft_ver == "2.0"
    assert reg.location_id == 1
    assert reg.location_pwd == "secret"
    assert len(reg.channels) == 1
    assert reg.channels[0].number == 0
    assert reg.channels[0].type == 2900
    assert reg.channels[0].default == 140
    assert reg.channels[0].value[0] == 1


def test_decode_register_device_e() -> None:
    guid = bytes([0xDF, 0x16, 0xAF, 0x7D] + [0] * 12)
    channel_value = bytes(SUPLA_CHANNELVALUE_SIZE)
    channel = (
        bytes([0])
        + struct.pack("<iiii", 2900, 0, 140, 0)
        + channel_value
    )
    payload = (
        _pad(b"user@example.com", SUPLA_EMAIL_MAXSIZE)
        + bytes(range(16))
        + guid
        + _pad(b"ZAMEL ROW-01", SUPLA_DEVICE_NAME_MAXSIZE)
        + _pad(b"2.8.0", SUPLA_SOFTVER_MAXSIZE)
        + _pad(b"192.168.1.10", SUPLA_SERVER_NAME_MAXSIZE)
        + struct.pack("<ihh", 0, 1, 2)
        + bytes([1])
        + channel
    )
    reg = decode_register_device(SUPLA_DS_CALL_REGISTER_DEVICE_E, payload)
    assert reg.email == "user@example.com"
    assert reg.name == "ZAMEL ROW-01"
    assert reg.manufacturer_id == 1
    assert reg.product_id == 2
    assert len(reg.channels) == 1
    assert reg.channels[0].default == 140


def test_how_protocol_works_register_result_shape() -> None:
    """Result payload layout matches TSD_SuplaRegisterDeviceResult."""
    data = encode_register_device_result(
        result_code=SUPLA_RESULTCODE_TRUE,
        activity_timeout=100,
        version=SUPLA_PROTO_VERSION,
        version_min=1,
    )
    assert len(data) == 7
    result_code, timeout, version, version_min = struct.unpack("<iBBB", data)
    assert result_code == SUPLA_RESULTCODE_TRUE
    assert timeout == 100
    assert version == SUPLA_PROTO_VERSION
    assert version_min == 1
