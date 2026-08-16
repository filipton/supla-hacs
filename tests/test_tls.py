"""TLS listener smoke tests."""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path

from supla_server.consts import (
    SUPLA_DCS_CALL_GETVERSION,
    SUPLA_SDC_CALL_GETVERSION_RESULT,
)
from supla_server.protocol import SuplaPacket, encode_packet, try_decode_packet
from supla_server.registry import DeviceRegistry
from supla_server.tcp_server import SuplaTcpServer
from supla_server.tls import ensure_certificate, load_or_create_ssl_context


async def test_tls_getversion_roundtrip(tmp_path: Path) -> None:
    ssl_ctx = load_or_create_ssl_context(cert_dir=tmp_path)
    registry = DeviceRegistry()
    server = SuplaTcpServer(
        registry,
        host="127.0.0.1",
        port=0,
        tls_port=0,  # placeholder, replaced after bind trick below
        ssl_context=ssl_ctx,
    )
    # Bind plain+tls with ephemeral ports via start_server internals:
    # use explicit ports chosen free by OS through port=0 on both.
    server.tls_port = 0
    await server.start()
    assert len(server._servers) == 2
    plain_port = server._servers[0].sockets[0].getsockname()[1]
    tls_port = server._servers[1].sockets[0].getsockname()[1]
    assert plain_port != tls_port

    client_ctx = ssl.create_default_context()
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE

    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        tls_port,
        ssl=client_ctx,
        server_hostname="localhost",
    )
    try:
        req = SuplaPacket(version=12, rr_id=1, call_id=SUPLA_DCS_CALL_GETVERSION, data=b"")
        writer.write(encode_packet(req))
        await writer.drain()

        buf = bytearray()
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=2)
            assert chunk, "server closed before response"
            buf.extend(chunk)
            packet, consumed = try_decode_packet(buf)
            if packet is not None:
                del buf[:consumed]
                break

        assert packet.call_id == SUPLA_SDC_CALL_GETVERSION_RESULT
        assert packet.rr_id == 1
        assert len(packet.data) >= 2
    finally:
        writer.close()
        await writer.wait_closed()
        await server.stop()


async def test_tls_11_static_rsa_getversion_roundtrip(tmp_path: Path) -> None:
    """Legacy commercial devices can connect with their restricted TLS stack."""
    ssl_ctx = load_or_create_ssl_context(cert_dir=tmp_path)
    registry = DeviceRegistry()
    server = SuplaTcpServer(
        registry,
        host="127.0.0.1",
        port=0,
        tls_port=0,
        ssl_context=ssl_ctx,
    )
    await server.start()
    tls_port = server._servers[1].sockets[0].getsockname()[1]

    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE
    client_ctx.minimum_version = ssl.TLSVersion.TLSv1_1
    client_ctx.maximum_version = ssl.TLSVersion.TLSv1_1
    client_ctx.set_ciphers("AES128-SHA:@SECLEVEL=0")

    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        tls_port,
        ssl=client_ctx,
        server_hostname="localhost",
    )
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        assert ssl_object.version() == "TLSv1.1"
        assert ssl_object.cipher()[0] == "AES128-SHA"

        req = SuplaPacket(version=12, rr_id=1, call_id=SUPLA_DCS_CALL_GETVERSION, data=b"")
        writer.write(encode_packet(req))
        await writer.drain()

        buf = bytearray(await asyncio.wait_for(reader.read(4096), timeout=2))
        packet, _ = try_decode_packet(buf)
        assert packet is not None
        assert packet.call_id == SUPLA_SDC_CALL_GETVERSION_RESULT
    finally:
        writer.close()
        await writer.wait_closed()
        await server.stop()


def test_ensure_certificate_persists(tmp_path: Path) -> None:
    cert1, key1 = ensure_certificate(tmp_path)
    assert cert1.is_file()
    assert key1.is_file()
    text1 = cert1.read_text()
    cert2, key2 = ensure_certificate(tmp_path)
    assert cert1 == cert2
    assert key1 == key2
    assert cert2.read_text() == text1
