"""Persistable snapshots of the SUPLA device tree.

The registry holds live objects that are replaced wholesale every time a device
re-registers. These snapshots are the flat, comparable, JSON-round-trippable
description of *which entities should exist* — that is all the integration
persists, so nothing here depends on Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .server import channels
from .server.registry import ChannelState, ConnectedDevice


@dataclass(frozen=True, slots=True)
class SubDeviceSnapshot:
    """A module behind a gateway device, reported via SET_SUBDEVICE_DETAILS."""

    sub_device_id: int
    name: str = ""
    soft_ver: str = ""
    product_code: str = ""
    serial_number: str = ""

    @classmethod
    def from_details(cls, details: dict[str, Any]) -> SubDeviceSnapshot:
        return cls(
            sub_device_id=int(details.get("sub_device_id") or 0),
            name=str(details.get("name") or ""),
            soft_ver=str(details.get("soft_ver") or ""),
            product_code=str(details.get("product_code") or ""),
            serial_number=str(details.get("serial_number") or ""),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "sub_device_id": self.sub_device_id,
            "name": self.name,
            "soft_ver": self.soft_ver,
            "product_code": self.product_code,
            "serial_number": self.serial_number,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SubDeviceSnapshot:
        return cls.from_details(data)


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    """Everything needed to decide which entities a channel produces."""

    number: int
    type: int
    function: int
    func_list: int = 0
    flags: int = 0
    sub_device_id: int = 0
    #: Per-phase energy readings seen in an electricity meter's extended value.
    #: Only known once the device has reported one, hence persisted separately.
    em_phases: int = 0
    #: Impulse counters report a scaled reading in their extended value.
    ic_calculated: bool = False

    @property
    def kind(self) -> str:
        return channels.channel_kind(self.function, self.type)

    @classmethod
    def from_state(cls, state: ChannelState) -> ChannelSnapshot:
        extended = state.extended or {}
        forward = extended.get("total_forward_active_energy_kwh")
        return cls(
            number=state.number,
            type=state.type,
            function=state.function,
            func_list=state.func_list,
            flags=state.flags,
            sub_device_id=state.sub_device_id,
            em_phases=len(forward) if isinstance(forward, list) else 0,
            ic_calculated="calculated_value" in extended,
        )

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "number": self.number,
            "type": self.type,
            "function": self.function,
            "func_list": self.func_list,
            "flags": self.flags,
            "sub_device_id": self.sub_device_id,
        }
        if self.em_phases:
            data["em_phases"] = self.em_phases
        if self.ic_calculated:
            data["ic_calculated"] = True
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ChannelSnapshot:
        return cls(
            number=int(data["number"]),
            type=int(data.get("type") or 0),
            function=int(data.get("function") or 0),
            func_list=int(data.get("func_list") or 0),
            flags=int(data.get("flags") or 0),
            sub_device_id=int(data.get("sub_device_id") or 0),
            em_phases=int(data.get("em_phases") or 0),
            ic_calculated=bool(data.get("ic_calculated")),
        )


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """A device as Home Assistant should model it, online or not."""

    guid: str
    name: str = ""
    soft_ver: str = ""
    manufacturer_id: int = 0
    product_id: int = 0
    proto_version: int = 0
    channels: tuple[ChannelSnapshot, ...] = field(default_factory=tuple)
    sub_devices: tuple[SubDeviceSnapshot, ...] = field(default_factory=tuple)

    @classmethod
    def from_device(cls, device: ConnectedDevice) -> DeviceSnapshot:
        return cls(
            guid=device.guid_hex,
            name=device.name,
            soft_ver=device.soft_ver,
            manufacturer_id=device.manufacturer_id,
            product_id=device.product_id,
            proto_version=device.proto_version,
            channels=tuple(
                ChannelSnapshot.from_state(state)
                for state in sorted(device.channels.values(), key=lambda c: c.number)
            ),
            sub_devices=tuple(
                SubDeviceSnapshot.from_details(details)
                for details in sorted(
                    device.sub_devices.values(),
                    key=lambda d: int(d.get("sub_device_id") or 0),
                )
            ),
        )

    def merge(self, other: DeviceSnapshot) -> DeviceSnapshot:
        """Fold `other` (fresher) into this one without losing sticky facts.

        A re-registration carries the authoritative channel list but arrives
        before any extended value, so per-phase/calculated flags discovered
        earlier would otherwise be forgotten and their entities disappear.
        """
        previous = {channel.number: channel for channel in self.channels}
        merged = []
        for channel in other.channels:
            old = previous.get(channel.number)
            if old is not None and old.kind == channel.kind:
                channel = replace(
                    channel,
                    em_phases=max(channel.em_phases, old.em_phases),
                    ic_calculated=channel.ic_calculated or old.ic_calculated,
                )
            merged.append(channel)
        return replace(other, channels=tuple(merged))

    def to_json(self) -> dict[str, Any]:
        return {
            "guid": self.guid,
            "name": self.name,
            "soft_ver": self.soft_ver,
            "manufacturer_id": self.manufacturer_id,
            "product_id": self.product_id,
            "proto_version": self.proto_version,
            "channels": [channel.to_json() for channel in self.channels],
            "sub_devices": [sub.to_json() for sub in self.sub_devices],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DeviceSnapshot:
        return cls(
            guid=str(data["guid"]),
            name=str(data.get("name") or ""),
            soft_ver=str(data.get("soft_ver") or ""),
            manufacturer_id=int(data.get("manufacturer_id") or 0),
            product_id=int(data.get("product_id") or 0),
            proto_version=int(data.get("proto_version") or 0),
            channels=tuple(
                ChannelSnapshot.from_json(item) for item in data.get("channels") or ()
            ),
            sub_devices=tuple(
                SubDeviceSnapshot.from_json(item) for item in data.get("sub_devices") or ()
            ),
        )
