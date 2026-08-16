"""Per-connection SUPLA device session handler."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import TYPE_CHECKING

from .channels import decode_extended_value
from .consts import (
    CHANNEL_VALUE_CHANGED_CALLS,
    DEFAULT_ACTIVITY_TIMEOUT,
    HTTP_SENDER_ID,
    REGISTER_DEVICE_CALLS,
    SUPLA_CHANNELFNC_ACTIONTRIGGER,
    SUPLA_CONFIG_RESULT_TRUE,
    SUPLA_DCS_CALL_GETVERSION,
    SUPLA_DCS_CALL_GET_REGISTRATION_ENABLED,
    SUPLA_DCS_CALL_GET_USER_LOCALTIME,
    SUPLA_DCS_CALL_GET_USER_LOCALTIME_RESULT,
    SUPLA_DCS_CALL_PING_SERVER,
    SUPLA_DCS_CALL_SET_ACTIVITY_TIMEOUT,
    SUPLA_DS_CALL_ACTIONTRIGGER,
    SUPLA_DS_CALL_CHANNEL_SET_VALUE_RESULT,
    SUPLA_DS_CALL_DEVICE_CHANNEL_EXTENDEDVALUE_CHANGED,
    SUPLA_DS_CALL_GET_CHANNEL_CONFIG,
    SUPLA_DS_CALL_GET_CHANNEL_FUNCTIONS,
    SUPLA_DS_CALL_SET_CHANNEL_CONFIG,
    SUPLA_DS_CALL_SET_DEVICE_CONFIG,
    SUPLA_DS_CALL_SET_SUBDEVICE_DETAILS,
    SUPLA_PROTO_VERSION,
    SUPLA_PROTO_VERSION_MIN,
    SUPLA_SDC_CALL_GETVERSION_RESULT,
    SUPLA_SDC_CALL_GET_REGISTRATION_ENABLED_RESULT,
    SUPLA_SDC_CALL_PING_SERVER_RESULT,
    SUPLA_SDC_CALL_SET_ACTIVITY_TIMEOUT_RESULT,
    SUPLA_SDC_CALL_VERSIONERROR,
    SUPLA_SD_CALL_CHANNEL_SET_VALUE,
    SUPLA_SD_CALL_GET_CHANNEL_CONFIG_RESULT,
    SUPLA_SD_CALL_GET_CHANNEL_FUNCTIONS_RESULT,
    SUPLA_SD_CALL_REGISTER_DEVICE_RESULT,
    SUPLA_SD_CALL_SET_CHANNEL_CONFIG_RESULT,
    SUPLA_SD_CALL_SET_DEVICE_CONFIG_RESULT,
)
from .protocol import (
    ProtocolError,
    SuplaPacket,
    decode_action_trigger,
    decode_channel_extended_value,
    decode_channel_set_value_result,
    decode_channel_value_changed,
    decode_get_channel_config_request,
    decode_register_device,
    decode_set_activity_timeout,
    decode_subdevice_details,
    encode_channel_config,
    encode_channel_functions,
    encode_channel_new_value,
    encode_get_version_result,
    encode_packet,
    encode_ping_result,
    encode_register_device_result,
    encode_registration_enabled_result,
    encode_set_activity_timeout_result,
    encode_set_channel_config_result,
    encode_set_device_config_result,
    encode_user_local_time_result,
    encode_version_error,
    guid_to_hex,
    iter_packets,
    make_response,
)

if TYPE_CHECKING:
    from .registry import DeviceRegistry, ConnectedDevice

logger = logging.getLogger(__name__)


class DeviceSession:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        registry: DeviceRegistry,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._registry = registry
        self._buffer = bytearray()
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._proto_version = SUPLA_PROTO_VERSION_MIN
        self._rr_counter = 1
        self.guid: bytes | None = None
        self.device: ConnectedDevice | None = None
        peer = writer.get_extra_info("peername")
        self.peer = peer

    @property
    def is_connected(self) -> bool:
        return not self._closed and not self._writer.is_closing()

    async def run(self) -> None:
        logger.info("device connected from %s", self.peer)
        try:
            while not self._closed:
                chunk = await self._reader.read(4096)
                if not chunk:
                    break
                self._buffer.extend(chunk)
                try:
                    for packet in iter_packets(self._buffer):
                        await self._handle_packet(packet)
                except ProtocolError as exc:
                    logger.warning("protocol error from %s: %s", self.peer, exc)
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session error from %s", self.peer)
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._registry.unregister_session(self)
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass
        logger.info("device disconnected %s", guid_to_hex(self.guid) if self.guid else self.peer)

    async def _send(self, packet: SuplaPacket) -> None:
        raw = encode_packet(packet)
        async with self._write_lock:
            if self._closed:
                return
            self._writer.write(raw)
            await self._writer.drain()

    def _next_rr_id(self) -> int:
        self._rr_counter = (self._rr_counter + 1) & 0xFFFFFFFF
        if self._rr_counter == 0:
            self._rr_counter = 1
        return self._rr_counter

    async def send_channel_value(self, channel_number: int, value: bytes) -> None:
        data = encode_channel_new_value(
            channel_number=channel_number,
            value=value,
            sender_id=HTTP_SENDER_ID,
        )
        packet = SuplaPacket(
            version=self._proto_version,
            rr_id=self._next_rr_id(),
            call_id=SUPLA_SD_CALL_CHANNEL_SET_VALUE,
            data=data,
        )
        await self._send(packet)
        logger.info(
            "set channel %s on %s value=%s",
            channel_number,
            guid_to_hex(self.guid) if self.guid else "?",
            value.hex(),
        )

    async def _handle_packet(self, packet: SuplaPacket) -> None:
        self._proto_version = min(packet.version, SUPLA_PROTO_VERSION)
        call_id = packet.call_id

        if call_id == SUPLA_DCS_CALL_GETVERSION:
            await self._send(
                make_response(
                    packet,
                    SUPLA_SDC_CALL_GETVERSION_RESULT,
                    encode_get_version_result(version=SUPLA_PROTO_VERSION),
                    version=self._proto_version,
                )
            )
            return

        if call_id == SUPLA_DCS_CALL_PING_SERVER:
            await self._send(
                make_response(
                    packet,
                    SUPLA_SDC_CALL_PING_SERVER_RESULT,
                    encode_ping_result(packet.data),
                )
            )
            return

        if call_id == SUPLA_DCS_CALL_SET_ACTIVITY_TIMEOUT:
            requested = decode_set_activity_timeout(packet.data)
            timeout = max(10, min(240, requested or DEFAULT_ACTIVITY_TIMEOUT))
            await self._send(
                make_response(
                    packet,
                    SUPLA_SDC_CALL_SET_ACTIVITY_TIMEOUT_RESULT,
                    encode_set_activity_timeout_result(timeout),
                )
            )
            return

        if call_id == SUPLA_DCS_CALL_GET_REGISTRATION_ENABLED:
            await self._send(
                make_response(
                    packet,
                    SUPLA_SDC_CALL_GET_REGISTRATION_ENABLED_RESULT,
                    encode_registration_enabled_result(),
                )
            )
            return

        if call_id == SUPLA_DCS_CALL_GET_USER_LOCALTIME:
            await self._send(
                make_response(
                    packet,
                    SUPLA_DCS_CALL_GET_USER_LOCALTIME_RESULT,
                    encode_user_local_time_result(),
                )
            )
            return

        if call_id in REGISTER_DEVICE_CALLS:
            await self._handle_register(packet)
            return

        if call_id in CHANNEL_VALUE_CHANGED_CALLS:
            if self.guid is None:
                logger.debug("value change before register from %s", self.peer)
                return
            number, value, offline = decode_channel_value_changed(call_id, packet.data)
            await self._registry.update_channel_value(self.guid, number, value, offline)
            logger.debug(
                "channel %s value changed on %s: %s offline=%s",
                number,
                guid_to_hex(self.guid),
                value.hex(),
                offline,
            )
            return

        if call_id == SUPLA_DS_CALL_DEVICE_CHANNEL_EXTENDEDVALUE_CHANGED:
            if self.guid is None:
                return
            number, ev_type, payload = decode_channel_extended_value(packet.data)
            extended = decode_extended_value(ev_type, payload)
            await self._registry.update_extended_value(self.guid, number, extended)
            logger.debug("channel %s extended value type=%s", number, ev_type)
            return

        if call_id == SUPLA_DS_CALL_ACTIONTRIGGER:
            number, actions = decode_action_trigger(packet.data)
            logger.info("action trigger channel=%s actions=0x%x", number, actions)
            if self.guid is not None:
                await self._registry.trigger_action(self.guid, number, actions)
            return

        if call_id == SUPLA_DS_CALL_SET_SUBDEVICE_DETAILS:
            details = decode_subdevice_details(packet.data)
            logger.info("subdevice %s: %s", details["sub_device_id"], details["name"])
            if self.guid is not None:
                await self._registry.add_sub_device(self.guid, details)
            return

        if call_id == SUPLA_DS_CALL_GET_CHANNEL_CONFIG:
            await self._handle_get_channel_config(packet)
            return

        if call_id == SUPLA_DS_CALL_SET_CHANNEL_CONFIG:
            channel_number = packet.data[0] if packet.data else 0
            config_type = packet.data[5] if len(packet.data) > 5 else 0
            logger.debug("device set channel config channel=%s type=%s", channel_number, config_type)
            await self._send(
                make_response(
                    packet,
                    SUPLA_SD_CALL_SET_CHANNEL_CONFIG_RESULT,
                    encode_set_channel_config_result(
                        channel_number=channel_number,
                        config_type=config_type,
                        result=SUPLA_CONFIG_RESULT_TRUE,
                    ),
                )
            )
            return

        if call_id == SUPLA_DS_CALL_SET_DEVICE_CONFIG:
            logger.debug("device sent its config (%d bytes)", len(packet.data))
            await self._send(
                make_response(
                    packet,
                    SUPLA_SD_CALL_SET_DEVICE_CONFIG_RESULT,
                    encode_set_device_config_result(SUPLA_CONFIG_RESULT_TRUE),
                )
            )
            return

        if call_id == SUPLA_DS_CALL_CHANNEL_SET_VALUE_RESULT:
            number, sender_id, success = decode_channel_set_value_result(packet.data)
            logger.info(
                "set-value result channel=%s sender=%s success=%s device=%s",
                number,
                sender_id,
                success,
                guid_to_hex(self.guid) if self.guid else "?",
            )
            return

        if call_id == SUPLA_DS_CALL_GET_CHANNEL_FUNCTIONS:
            functions: list[int] = []
            if self.device is not None:
                max_num = max(self.device.channels.keys(), default=-1)
                functions = [
                    self.device.channels[i].function if i in self.device.channels else 0
                    for i in range(max_num + 1)
                ]
            await self._send(
                make_response(
                    packet,
                    SUPLA_SD_CALL_GET_CHANNEL_FUNCTIONS_RESULT,
                    encode_channel_functions(functions),
                )
            )
            return

        if packet.version < SUPLA_PROTO_VERSION_MIN or packet.version > SUPLA_PROTO_VERSION:
            await self._send(
                make_response(
                    packet,
                    SUPLA_SDC_CALL_VERSIONERROR,
                    encode_version_error(),
                    version=SUPLA_PROTO_VERSION,
                )
            )
            return

        logger.debug("ignored call_id=%s from %s (%d bytes)", call_id, self.peer, len(packet.data))

    async def _handle_get_channel_config(self, packet: SuplaPacket) -> None:
        channel_number, config_type, _flags = decode_get_channel_config_request(packet.data)
        channel = None
        if self.device is not None:
            channel = self.device.channels.get(channel_number)
        function = channel.function if channel is not None else 0

        config = b""
        if function == SUPLA_CHANNELFNC_ACTIONTRIGGER:
            # Enable every action the button reports so triggers reach the server.
            active_actions = channel.func_list if channel is not None else 0xFFFFFFFF
            config = struct.pack("<I", active_actions & 0xFFFFFFFF)

        await self._send(
            make_response(
                packet,
                SUPLA_SD_CALL_GET_CHANNEL_CONFIG_RESULT,
                encode_channel_config(
                    channel_number=channel_number,
                    function=function,
                    config_type=config_type,
                    config=config,
                ),
            )
        )
        logger.debug(
            "sent channel config for #%s (function=%s, %d config bytes)",
            channel_number,
            function,
            len(config),
        )

    async def _handle_register(self, packet: SuplaPacket) -> None:
        reg = decode_register_device(packet.call_id, packet.data)
        self.guid = reg.guid
        negotiated = min(packet.version, SUPLA_PROTO_VERSION)
        self._proto_version = negotiated

        # Open auth: always accept.
        await self._send(
            make_response(
                packet,
                SUPLA_SD_CALL_REGISTER_DEVICE_RESULT,
                encode_register_device_result(
                    activity_timeout=DEFAULT_ACTIVITY_TIMEOUT,
                    version=negotiated,
                    version_min=SUPLA_PROTO_VERSION_MIN,
                ),
                version=negotiated,
            )
        )
        self.device = await self._registry.register(reg, self, negotiated)
