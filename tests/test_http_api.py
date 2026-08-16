"""HTTP API and registry smoke tests."""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from supla_server.http_api import create_app
from supla_server.protocol import DeviceChannel, RegisterDevice
from supla_server.registry import DeviceRegistry


class _FakeSession:
    is_connected = True

    async def send_channel_value(self, channel_number: int, value: bytes) -> None:
        self.last = (channel_number, value)

    async def close(self) -> None:
        self.is_connected = False


async def test_list_and_set_channel() -> None:
    registry = DeviceRegistry()
    session = _FakeSession()
    guid = bytes(range(16))
    reg = RegisterDevice(
        call_id=69,
        guid=guid,
        name="Lamp",
        soft_ver="1.0",
        channels=[
            DeviceChannel(number=0, type=2900, default=140, value=bytes(8)),
        ],
        email="a@b.c",
    )
    device = await registry.register(reg, session, proto_version=12)  # type: ignore[arg-type]
    assert device.online

    app = create_app(registry)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        assert await resp.json() == {"status": "ok"}

        resp = await client.get("/api/devices")
        body = await resp.json()
        assert len(body["devices"]) == 1
        assert body["devices"][0]["name"] == "Lamp"

        guid_hex = body["devices"][0]["guid"]
        resp = await client.post(
            f"/api/devices/{guid_hex}/channels/0",
            json={"on": True},
        )
        assert resp.status == 200
        result = await resp.json()
        assert result["ok"] is True
        assert result["channel"]["value"]["on"] is True
        assert session.last[0] == 0
        assert session.last[1][0] == 1
