"""aiohttp REST API and web panel for listing and controlling connected devices."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from .channels import UnsupportedCommand
from .registry import DeviceRegistry

logger = logging.getLogger(__name__)

REGISTRY_KEY = web.AppKey("registry", DeviceRegistry)
WEB_DIR = Path(__file__).parent / "web"


def create_app(registry: DeviceRegistry) -> web.Application:
    app = web.Application()
    app[REGISTRY_KEY] = registry
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/devices", handle_list_devices)
    app.router.add_get("/api/devices/{guid}", handle_get_device)
    app.router.add_post("/api/devices/{guid}/channels/{number}", handle_set_channel)
    app.router.add_static("/static", WEB_DIR)
    return app


async def handle_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def handle_health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_list_devices(request: web.Request) -> web.Response:
    registry = request.app[REGISTRY_KEY]
    devices = [d.to_dict() for d in registry.list_devices()]
    return web.json_response({"devices": devices})


async def handle_get_device(request: web.Request) -> web.Response:
    registry = request.app[REGISTRY_KEY]
    guid = request.match_info["guid"]
    device = registry.get(guid)
    if device is None:
        raise web.HTTPNotFound(text=f"device {guid} not found")
    return web.json_response(device.to_dict())


async def handle_set_channel(request: web.Request) -> web.Response:
    registry = request.app[REGISTRY_KEY]
    guid = request.match_info["guid"]
    try:
        number = int(request.match_info["number"])
    except ValueError as exc:
        raise web.HTTPBadRequest(text="channel number must be an integer") from exc

    device = registry.get(guid)
    if device is None:
        raise web.HTTPNotFound(text=f"device {guid} not found")
    if number not in device.channels:
        raise web.HTTPNotFound(text=f"channel {number} not found")

    try:
        body: dict[str, Any] = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")

    try:
        channel = await device.execute(number, body)
    except RuntimeError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
    except (UnsupportedCommand, KeyError, TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc

    return web.json_response(
        {
            "ok": True,
            "guid": device.guid_hex,
            "channel": channel.to_dict(),
        }
    )
