"""SUPLA packet framing and structure encode/decode."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Iterator
from zoneinfo import ZoneInfo

from .consts import (
    DEFAULT_ACTIVITY_TIMEOUT,
    REGISTER_DEVICE_CALLS,
    SOFT_VERSION,
    SUPLA_AUTHKEY_SIZE,
    SUPLA_CHANNELVALUE_SIZE,
    SUPLA_DEVICE_NAME_MAXSIZE,
    SUPLA_DS_CALL_REGISTER_DEVICE,
    SUPLA_DS_CALL_REGISTER_DEVICE_B,
    SUPLA_DS_CALL_REGISTER_DEVICE_C,
    SUPLA_DS_CALL_REGISTER_DEVICE_D,
    SUPLA_DS_CALL_REGISTER_DEVICE_E,
    SUPLA_DS_CALL_REGISTER_DEVICE_F,
    SUPLA_DS_CALL_REGISTER_DEVICE_G,
    SUPLA_EMAIL_MAXSIZE,
    SUPLA_GUID_SIZE,
    SUPLA_LOCATION_PWD_MAXSIZE,
    SUPLA_PACKET_HEADER_SIZE,
    SUPLA_PACKET_MIN_SIZE,
    SUPLA_PROTO_VERSION,
    SUPLA_PROTO_VERSION_MIN,
    SUPLA_RESULTCODE_TRUE,
    SUPLA_SERVER_NAME_MAXSIZE,
    SUPLA_SOFTVER_MAXSIZE,
    SUPLA_TAG,
    SUPLA_TAG_SIZE,
    SUPLA_TIMEZONE_MAXSIZE,
)


@dataclass(slots=True)
class SuplaPacket:
    version: int
    rr_id: int
    call_id: int
    data: bytes


@dataclass(slots=True)
class DeviceChannel:
    number: int
    type: int
    func_list: int = 0
    default: int = 0
    flags: int = 0
    value: bytes = field(default_factory=lambda: bytes(SUPLA_CHANNELVALUE_SIZE))
    offline: int = 0
    value_validity_sec: int = 0
    default_icon: int = 0
    sub_device_id: int = 0


@dataclass(slots=True)
class RegisterDevice:
    call_id: int
    guid: bytes
    name: str
    soft_ver: str
    channels: list[DeviceChannel]
    location_id: int | None = None
    location_pwd: str | None = None
    email: str | None = None
    auth_key: bytes | None = None
    server_name: str | None = None
    flags: int = 0
    manufacturer_id: int = 0
    product_id: int = 0


class ProtocolError(ValueError):
    """Invalid SUPLA framing or payload."""


def guid_to_hex(guid: bytes) -> str:
    return guid.hex().upper()


def hex_to_guid(value: str) -> bytes:
    cleaned = value.replace("-", "").replace(":", "").strip()
    data = bytes.fromhex(cleaned)
    if len(data) != SUPLA_GUID_SIZE:
        raise ValueError(f"GUID must be {SUPLA_GUID_SIZE} bytes, got {len(data)}")
    return data


def _c_string(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _pad(value: bytes | str, size: int) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    if len(value) >= size:
        return value[: size - 1] + b"\x00" if size > 0 else b""
    return value + b"\x00" * (size - len(value))


def encode_packet(packet: SuplaPacket) -> bytes:
    """Wire format: SUPLA + header + data + trailing SUPLA."""
    body = struct.pack(
        "<BIII",
        packet.version & 0xFF,
        packet.rr_id & 0xFFFFFFFF,
        packet.call_id & 0xFFFFFFFF,
        len(packet.data) & 0xFFFFFFFF,
    )
    return SUPLA_TAG + body + packet.data + SUPLA_TAG


def try_decode_packet(buffer: bytearray | memoryview | bytes) -> tuple[SuplaPacket | None, int]:
    """
    Try to read one framed packet from the start of buffer.

    Returns (packet, bytes_consumed) or (None, 0) if more data is needed.
    Raises ProtocolError on corrupted framing.
    """
    view = memoryview(buffer)
    if len(view) < SUPLA_PACKET_MIN_SIZE:
        return None, 0

    if bytes(view[:SUPLA_TAG_SIZE]) != SUPLA_TAG:
        raise ProtocolError(f"expected SUPLA tag, got {bytes(view[:SUPLA_TAG_SIZE])!r}")

    version, rr_id, call_id, data_size = struct.unpack_from(
        "<BIII", view, SUPLA_TAG_SIZE
    )
    total = SUPLA_TAG_SIZE + SUPLA_PACKET_HEADER_SIZE + data_size + SUPLA_TAG_SIZE
    if len(view) < total:
        return None, 0

    data_start = SUPLA_TAG_SIZE + SUPLA_PACKET_HEADER_SIZE
    data_end = data_start + data_size
    trailing = bytes(view[data_end : data_end + SUPLA_TAG_SIZE])
    if trailing != SUPLA_TAG:
        raise ProtocolError(f"expected trailing SUPLA tag, got {trailing!r}")

    packet = SuplaPacket(
        version=version,
        rr_id=rr_id,
        call_id=call_id,
        data=bytes(view[data_start:data_end]),
    )
    return packet, total


def iter_packets(buffer: bytearray) -> Iterator[SuplaPacket]:
    """Consume complete packets from a mutable buffer in place."""
    while True:
        packet, consumed = try_decode_packet(buffer)
        if packet is None:
            return
        del buffer[:consumed]
        yield packet


def encode_set_channel_config_result(
    *,
    channel_number: int,
    config_type: int = 0,
    result: int = 1,
) -> bytes:
    """TSDS_SetChannelConfigResult: Result, ConfigType, ChannelNumber."""
    return bytes([result & 0xFF, config_type & 0xFF, channel_number & 0xFF])


def encode_set_device_config_result(result: int = 1) -> bytes:
    """TSDS_SetDeviceConfigResult: Result + 9 reserved bytes."""
    return bytes([result & 0xFF]) + bytes(9)


def encode_channel_config(
    *,
    channel_number: int,
    function: int,
    config_type: int = 0,
    config: bytes = b"",
) -> bytes:
    """TSD_ChannelConfig: ChannelNumber, Func, ConfigType, ConfigSize, Config."""
    return (
        struct.pack(
            "<BiBH",
            channel_number & 0xFF,
            function,
            config_type & 0xFF,
            len(config),
        )
        + config
    )


def decode_get_channel_config_request(data: bytes) -> tuple[int, int, int]:
    """TDS_GetChannelConfigRequest: ChannelNumber, ConfigType, Flags."""
    if len(data) < 2:
        raise ProtocolError("short get channel config request")
    channel_number = data[0]
    config_type = data[1]
    flags = struct.unpack_from("<I", data, 2)[0] if len(data) >= 6 else 0
    return channel_number, config_type, flags


def encode_channel_state_request(channel_number: int, sender_id: int = 0) -> bytes:
    """TCSD_ChannelStateRequest: SenderID, then a 4 byte union holding the
    channel number in the server -> device direction."""
    return struct.pack("<i", sender_id) + bytes([channel_number & 0xFF]) + bytes(3)


def decode_channel_config(data: bytes) -> tuple[int, int, int, bytes]:
    """TSD_ChannelConfig -> (channel_number, func, config_type, config).

    Shared by SUPLA_DS_CALL_SET_CHANNEL_CONFIG and the results of a channel
    config exchange in either direction.
    """
    if len(data) < 8:
        raise ProtocolError("short channel config")
    channel_number, func, config_type, size = struct.unpack_from("<BiBH", data, 0)
    return channel_number, func, config_type, data[8 : 8 + size]


def decode_set_channel_config_result(data: bytes) -> tuple[int, int, int]:
    """TSDS_SetChannelConfigResult -> (result, config_type, channel_number)."""
    if len(data) < 3:
        raise ProtocolError("short set channel config result")
    return data[0], data[1], data[2]


def encode_channel_config_finished(channel_number: int) -> bytes:
    """TSD_ChannelConfigFinished: ChannelNumber."""
    return bytes([channel_number & 0xFF])


def decode_device_config(data: bytes) -> tuple[int, int, int, bytes]:
    """TSDS_SetDeviceConfig -> (end_of_data, available_fields, fields, config)."""
    if len(data) < 27:
        raise ProtocolError("short device config")
    end_of_data = data[0]
    # data[1:9] is a reserved zero block.
    available_fields, fields, size = struct.unpack_from("<QQH", data, 9)
    return end_of_data, available_fields, fields, data[27 : 27 + size]


def encode_device_config(
    *,
    available_fields: int,
    fields: int,
    config: bytes = b"",
    end_of_data: bool = True,
) -> bytes:
    """TSDS_SetDeviceConfig, as sent by the server."""
    return (
        bytes([1 if end_of_data else 0])
        + bytes(8)
        + struct.pack("<QQH", available_fields, fields, len(config))
        + config
    )


def decode_set_device_config_result(data: bytes) -> int:
    """TSDS_SetDeviceConfigResult: Result + 9 reserved bytes."""
    if not data:
        raise ProtocolError("short set device config result")
    return data[0]


def decode_channel_extended_value(data: bytes) -> tuple[int, int, bytes]:
    """TDS_SuplaDeviceChannelExtendedValue -> (channel_number, ev_type, payload)."""
    if len(data) < 6:
        raise ProtocolError("short extended value")
    channel_number = data[0]
    ev_type = data[1]
    size = struct.unpack_from("<I", data, 2)[0]
    payload = data[6 : 6 + size]
    return channel_number, ev_type, payload


def decode_action_trigger(data: bytes) -> tuple[int, int]:
    """TDS_ActionTrigger -> (channel_number, action_trigger_bitmask)."""
    if len(data) < 5:
        raise ProtocolError("short action trigger")
    return data[0], struct.unpack_from("<i", data, 1)[0]


def decode_subdevice_details(data: bytes) -> dict[str, object]:
    """TDS_SubdeviceDetails: SubDeviceId, Name, SoftVer, ProductCode, SerialNumber."""
    if len(data) < 1:
        raise ProtocolError("short subdevice details")
    offset = 1
    name = _c_string(data[offset : offset + SUPLA_DEVICE_NAME_MAXSIZE])
    offset += SUPLA_DEVICE_NAME_MAXSIZE
    soft_ver = _c_string(data[offset : offset + SUPLA_SOFTVER_MAXSIZE])
    offset += SUPLA_SOFTVER_MAXSIZE
    product_code = _c_string(data[offset : offset + 51])
    offset += 51
    serial_number = _c_string(data[offset : offset + 51])
    return {
        "sub_device_id": data[0],
        "name": name,
        "soft_ver": soft_ver,
        "product_code": product_code,
        "serial_number": serial_number,
    }


def encode_get_version_result(
    *,
    version: int = SUPLA_PROTO_VERSION,
    version_min: int = SUPLA_PROTO_VERSION_MIN,
    soft_ver: str = SOFT_VERSION,
) -> bytes:
    return (
        bytes([version_min & 0xFF, version & 0xFF])
        + _pad(soft_ver, SUPLA_SOFTVER_MAXSIZE)
    )


def encode_version_error(
    *,
    server_version_min: int = SUPLA_PROTO_VERSION_MIN,
    server_version: int = SUPLA_PROTO_VERSION,
) -> bytes:
    return bytes([server_version_min & 0xFF, server_version & 0xFF])


def encode_ping_result(data: bytes) -> bytes:
    """Echo timeval payload back to the device."""
    return data


def encode_set_activity_timeout_result(
    activity_timeout: int = DEFAULT_ACTIVITY_TIMEOUT,
    minimum: int = 10,
    maximum: int = 240,
) -> bytes:
    return bytes([activity_timeout & 0xFF, minimum & 0xFF, maximum & 0xFF])


def encode_registration_enabled_result(
    *,
    client_timestamp: int | None = None,
    iodevice_timestamp: int | None = None,
) -> bytes:
    far = int(time.time()) + 10 * 365 * 24 * 3600
    client = far if client_timestamp is None else client_timestamp
    device = far if iodevice_timestamp is None else iodevice_timestamp
    return struct.pack("<II", client & 0xFFFFFFFF, device & 0xFFFFFFFF)


def encode_register_device_result(
    *,
    result_code: int = SUPLA_RESULTCODE_TRUE,
    activity_timeout: int = DEFAULT_ACTIVITY_TIMEOUT,
    version: int = SUPLA_PROTO_VERSION,
    version_min: int = SUPLA_PROTO_VERSION_MIN,
) -> bytes:
    return struct.pack(
        "<iBBB",
        result_code,
        activity_timeout & 0xFF,
        version & 0xFF,
        version_min & 0xFF,
    )


def encode_channel_new_value(
    *,
    channel_number: int,
    value: bytes,
    sender_id: int = 1,
    duration_ms: int = 0,
) -> bytes:
    if len(value) != SUPLA_CHANNELVALUE_SIZE:
        raise ValueError(f"channel value must be {SUPLA_CHANNELVALUE_SIZE} bytes")
    return (
        struct.pack("<iBI", sender_id, channel_number & 0xFF, duration_ms & 0xFFFFFFFF)
        + value
    )


def encode_channel_functions(functions: list[int]) -> bytes:
    count = len(functions)
    return bytes([count & 0xFF]) + b"".join(struct.pack("<i", fn) for fn in functions)


#: Zone reported to devices that ask for the user's local time. Devices run
#: staircase timers and weekly schedules off it, so hosts should set their own.
_DEFAULT_TIMEZONE: tzinfo | None = None


def set_default_timezone(tz: tzinfo | None) -> None:
    global _DEFAULT_TIMEZONE
    _DEFAULT_TIMEZONE = tz


def encode_user_local_time_result(
    when: datetime | None = None,
    tz: tzinfo | None = None,
) -> bytes:
    zone = tz or _DEFAULT_TIMEZONE or ZoneInfo("UTC")
    now = when or datetime.now(zone)
    day_of_week = (now.isoweekday() % 7) + 1
    zone_name = getattr(zone, "key", None) or now.tzname() or "UTC"
    tz_name = zone_name.encode("utf-8")[: SUPLA_TIMEZONE_MAXSIZE - 1]
    tz_field = tz_name + b"\x00"
    return (
        struct.pack(
            "<HBBBBBBI",
            now.year,
            now.month,
            now.day,
            day_of_week,
            now.hour,
            now.minute,
            now.second,
            len(tz_field),
        )
        + tz_field
    )


def make_response(
    request: SuplaPacket,
    call_id: int,
    data: bytes,
    *,
    version: int | None = None,
) -> SuplaPacket:
    return SuplaPacket(
        version=version if version is not None else request.version,
        rr_id=request.rr_id,
        call_id=call_id,
        data=data,
    )


def decode_set_activity_timeout(data: bytes) -> int:
    if not data:
        raise ProtocolError("empty set activity timeout")
    return data[0]


def decode_channel_value_changed(call_id: int, data: bytes) -> tuple[int, bytes, int]:
    """Return (channel_number, value, offline_flag)."""
    if not data:
        raise ProtocolError("empty channel value changed")
    channel_number = data[0]
    if call_id == 100:
        value = data[1 : 1 + SUPLA_CHANNELVALUE_SIZE]
        return channel_number, value.ljust(SUPLA_CHANNELVALUE_SIZE, b"\x00"), 0
    if call_id == 102:
        offline = data[1] if len(data) > 1 else 0
        value = data[2 : 2 + SUPLA_CHANNELVALUE_SIZE]
        return channel_number, value.ljust(SUPLA_CHANNELVALUE_SIZE, b"\x00"), offline
    offline = data[1] if len(data) > 1 else 0
    value = data[6 : 6 + SUPLA_CHANNELVALUE_SIZE]
    return channel_number, value.ljust(SUPLA_CHANNELVALUE_SIZE, b"\x00"), offline


def decode_channel_set_value_result(data: bytes) -> tuple[int, int, bool]:
    if len(data) < 6:
        raise ProtocolError("short channel set value result")
    channel_number = data[0]
    sender_id = struct.unpack_from("<i", data, 1)[0]
    success = bool(data[5])
    return channel_number, sender_id, success


def _read_channels_a(data: bytes, offset: int, count: int) -> list[DeviceChannel]:
    size = 13
    channels: list[DeviceChannel] = []
    for _ in range(count):
        chunk = data[offset : offset + size]
        if len(chunk) < size:
            break
        number = chunk[0]
        type_ = struct.unpack_from("<i", chunk, 1)[0]
        value = chunk[5:13]
        channels.append(DeviceChannel(number=number, type=type_, value=value))
        offset += size
    return channels


def _read_channels_b(data: bytes, offset: int, count: int) -> list[DeviceChannel]:
    size = 21
    channels: list[DeviceChannel] = []
    for _ in range(count):
        chunk = data[offset : offset + size]
        if len(chunk) < size:
            break
        number = chunk[0]
        type_, func_list, default = struct.unpack_from("<iii", chunk, 1)
        value = chunk[13:21]
        channels.append(
            DeviceChannel(
                number=number,
                type=type_,
                func_list=func_list,
                default=default,
                value=value,
            )
        )
        offset += size
    return channels


def _read_channels_c(data: bytes, offset: int, count: int) -> list[DeviceChannel]:
    size = 25
    channels: list[DeviceChannel] = []
    for _ in range(count):
        chunk = data[offset : offset + size]
        if len(chunk) < size:
            break
        number = chunk[0]
        type_, func_list, default, flags = struct.unpack_from("<iiii", chunk, 1)
        value = chunk[17:25]
        channels.append(
            DeviceChannel(
                number=number,
                type=type_,
                func_list=func_list,
                default=default,
                flags=flags,
                value=value,
            )
        )
        offset += size
    return channels


def _read_channels_d(data: bytes, offset: int, count: int) -> list[DeviceChannel]:
    size = 35
    channels: list[DeviceChannel] = []
    for _ in range(count):
        chunk = data[offset : offset + size]
        if len(chunk) < size:
            break
        number = chunk[0]
        type_, func_list, default = struct.unpack_from("<iii", chunk, 1)
        flags = struct.unpack_from("<q", chunk, 13)[0]
        offline = chunk[21]
        validity = struct.unpack_from("<I", chunk, 22)[0]
        value = chunk[26:34]
        icon = chunk[34]
        channels.append(
            DeviceChannel(
                number=number,
                type=type_,
                func_list=func_list,
                default=default,
                flags=flags,
                offline=offline,
                value_validity_sec=validity,
                value=value,
                default_icon=icon,
            )
        )
        offset += size
    return channels


def _read_channels_e(data: bytes, offset: int, count: int) -> list[DeviceChannel]:
    size = 36
    channels: list[DeviceChannel] = []
    for _ in range(count):
        chunk = data[offset : offset + size]
        if len(chunk) < size:
            break
        number = chunk[0]
        type_, func_list, default = struct.unpack_from("<iii", chunk, 1)
        flags = struct.unpack_from("<q", chunk, 13)[0]
        offline = chunk[21]
        validity = struct.unpack_from("<I", chunk, 22)[0]
        value = chunk[26:34]
        icon = chunk[34]
        sub_id = chunk[35]
        channels.append(
            DeviceChannel(
                number=number,
                type=type_,
                func_list=func_list,
                default=default,
                flags=flags,
                offline=offline,
                value_validity_sec=validity,
                value=value,
                default_icon=icon,
                sub_device_id=sub_id,
            )
        )
        offset += size
    return channels


def decode_register_device(call_id: int, data: bytes) -> RegisterDevice:
    if call_id not in REGISTER_DEVICE_CALLS:
        raise ProtocolError(f"not a register device call: {call_id}")

    if call_id in (
        SUPLA_DS_CALL_REGISTER_DEVICE,
        SUPLA_DS_CALL_REGISTER_DEVICE_B,
        SUPLA_DS_CALL_REGISTER_DEVICE_C,
    ):
        return _decode_location_register(call_id, data)
    return _decode_email_register(call_id, data)


def _decode_location_register(call_id: int, data: bytes) -> RegisterDevice:
    need = (
        4
        + SUPLA_LOCATION_PWD_MAXSIZE
        + SUPLA_GUID_SIZE
        + SUPLA_DEVICE_NAME_MAXSIZE
        + SUPLA_SOFTVER_MAXSIZE
    )
    if call_id == SUPLA_DS_CALL_REGISTER_DEVICE_C:
        need += SUPLA_SERVER_NAME_MAXSIZE
    need += 1
    if len(data) < need:
        raise ProtocolError("short location register payload")

    offset = 0
    location_id = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    location_pwd = _c_string(data[offset : offset + SUPLA_LOCATION_PWD_MAXSIZE])
    offset += SUPLA_LOCATION_PWD_MAXSIZE
    guid = bytes(data[offset : offset + SUPLA_GUID_SIZE])
    offset += SUPLA_GUID_SIZE
    name = _c_string(data[offset : offset + SUPLA_DEVICE_NAME_MAXSIZE])
    offset += SUPLA_DEVICE_NAME_MAXSIZE
    soft_ver = _c_string(data[offset : offset + SUPLA_SOFTVER_MAXSIZE])
    offset += SUPLA_SOFTVER_MAXSIZE

    server_name = None
    if call_id == SUPLA_DS_CALL_REGISTER_DEVICE_C:
        server_name = _c_string(data[offset : offset + SUPLA_SERVER_NAME_MAXSIZE])
        offset += SUPLA_SERVER_NAME_MAXSIZE

    channel_count = data[offset]
    offset += 1

    if call_id == SUPLA_DS_CALL_REGISTER_DEVICE:
        channels = _read_channels_a(data, offset, channel_count)
    else:
        channels = _read_channels_b(data, offset, channel_count)

    return RegisterDevice(
        call_id=call_id,
        guid=guid,
        name=name,
        soft_ver=soft_ver,
        channels=channels,
        location_id=location_id,
        location_pwd=location_pwd,
        server_name=server_name,
    )


def _decode_email_register(call_id: int, data: bytes) -> RegisterDevice:
    offset = 0
    need = (
        SUPLA_EMAIL_MAXSIZE
        + SUPLA_AUTHKEY_SIZE
        + SUPLA_GUID_SIZE
        + SUPLA_DEVICE_NAME_MAXSIZE
        + SUPLA_SOFTVER_MAXSIZE
        + SUPLA_SERVER_NAME_MAXSIZE
        + 1
    )
    if call_id in (
        SUPLA_DS_CALL_REGISTER_DEVICE_E,
        SUPLA_DS_CALL_REGISTER_DEVICE_F,
        SUPLA_DS_CALL_REGISTER_DEVICE_G,
    ):
        need += 4 + 2 + 2
    if len(data) < need:
        raise ProtocolError("short email register payload")

    email = _c_string(data[offset : offset + SUPLA_EMAIL_MAXSIZE])
    offset += SUPLA_EMAIL_MAXSIZE
    auth_key = bytes(data[offset : offset + SUPLA_AUTHKEY_SIZE])
    offset += SUPLA_AUTHKEY_SIZE
    guid = bytes(data[offset : offset + SUPLA_GUID_SIZE])
    offset += SUPLA_GUID_SIZE
    name = _c_string(data[offset : offset + SUPLA_DEVICE_NAME_MAXSIZE])
    offset += SUPLA_DEVICE_NAME_MAXSIZE
    soft_ver = _c_string(data[offset : offset + SUPLA_SOFTVER_MAXSIZE])
    offset += SUPLA_SOFTVER_MAXSIZE
    server_name = _c_string(data[offset : offset + SUPLA_SERVER_NAME_MAXSIZE])
    offset += SUPLA_SERVER_NAME_MAXSIZE

    flags = 0
    manufacturer_id = 0
    product_id = 0
    if call_id in (
        SUPLA_DS_CALL_REGISTER_DEVICE_E,
        SUPLA_DS_CALL_REGISTER_DEVICE_F,
        SUPLA_DS_CALL_REGISTER_DEVICE_G,
    ):
        flags = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        manufacturer_id = struct.unpack_from("<h", data, offset)[0]
        offset += 2
        product_id = struct.unpack_from("<h", data, offset)[0]
        offset += 2

    channel_count = data[offset]
    offset += 1

    if call_id == SUPLA_DS_CALL_REGISTER_DEVICE_D:
        channels = _read_channels_b(data, offset, channel_count)
    elif call_id == SUPLA_DS_CALL_REGISTER_DEVICE_E:
        channels = _read_channels_c(data, offset, channel_count)
    elif call_id == SUPLA_DS_CALL_REGISTER_DEVICE_F:
        channels = _read_channels_d(data, offset, channel_count)
    else:
        channels = _read_channels_e(data, offset, channel_count)

    return RegisterDevice(
        call_id=call_id,
        guid=guid,
        name=name,
        soft_ver=soft_ver,
        channels=channels,
        email=email,
        auth_key=auth_key,
        server_name=server_name,
        flags=flags,
        manufacturer_id=manufacturer_id,
        product_id=product_id,
    )
