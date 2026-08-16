"""Sensor platform: thermometers, meters, measurements and tank levels."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import SuplaConfigEntry, state_map
from .channel_map import (
    ROLE_CALCULATED,
    ROLE_HUMIDITY,
    ROLE_PHASE,
    ROLE_TEMPERATURE,
    SENSOR,
    EntityKey,
    impulse_counter_meta,
    measurement_meta,
    unique_id,
)
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    SuplaEntity,
    async_setup_channel_platform,
    channel_device_info,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K

#: SUPLA reports an out-of-range temperature when the probe is not connected.
INVALID_TEMPERATURE = -273.0

ENERGY_KEY = "total_forward_active_energy_kwh"

#: How far a derived "since" instant may move before it is worth updating.
UPTIME_DRIFT = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, SENSOR, async_add_entities, _build)
    async_setup_device_state_platform(entry, async_add_entities)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    args = (manager, device, channel, key)
    kind = key.kind

    if kind == K.KIND_THERMOMETER or key.role == ROLE_TEMPERATURE:
        return SuplaTemperatureSensor(*args, value_key="temperature")

    if kind == K.KIND_HUMIDITY or key.role == ROLE_HUMIDITY:
        return SuplaHumiditySensor(*args, value_key="humidity")

    if kind == K.KIND_MEASUREMENT:
        device_class, unit = measurement_meta(channel.function)
        return SuplaValueSensor(
            *args,
            value_key="value",
            device_class=device_class,
            unit=unit,
            state_class=SensorStateClass.MEASUREMENT,
        )

    if kind == K.KIND_CONTAINER:
        return SuplaContainerSensor(*args, value_key="level")

    if kind == K.KIND_ELECTRICITY_METER:
        if key.role == ROLE_PHASE:
            return SuplaEnergyPhaseSensor(*args)
        return SuplaValueSensor(
            *args,
            value_key=ENERGY_KEY,
            device_class=SensorDeviceClass.ENERGY,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
            precision=2,
        )

    if kind == K.KIND_IMPULSE_COUNTER:
        if key.role == ROLE_CALCULATED:
            device_class, unit = impulse_counter_meta(channel.function)
            return SuplaCalculatedCounterSensor(
                *args,
                device_class=device_class,
                unit=unit,
                state_class=SensorStateClass.TOTAL_INCREASING,
            )
        return SuplaValueSensor(
            *args,
            value_key="counter",
            state_class=SensorStateClass.TOTAL_INCREASING,
        )

    return None


class SuplaValueSensor(SuplaChannelEntity, SensorEntity):
    """Reads one named field out of the decoded channel value."""

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
        *,
        value_key: str = "",
        device_class: str | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        precision: int | None = None,
    ) -> None:
        super().__init__(manager, device, channel, key)
        self._value_key = value_key
        # Assign only what was actually passed: subclasses declare their own
        # defaults as class attributes and None would blank them out.
        if device_class is not None:
            self._attr_device_class = SensorDeviceClass(device_class)
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class
        if precision is not None:
            self._attr_suggested_display_precision = precision

    @property
    def native_value(self) -> Any:
        return self._value.get(self._value_key)


class SuplaTemperatureSensor(SuplaValueSensor):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        value = self._value.get(self._value_key)
        if value is None or value <= INVALID_TEMPERATURE:
            return None
        return value


class SuplaHumiditySensor(SuplaValueSensor):
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        value = self._value.get(self._value_key)
        if value is None or value < 0:
            return None
        return value


class SuplaContainerSensor(SuplaValueSensor):
    """Fill level of a tank; SUPLA reports no level when it cannot measure."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"flags": self._value.get("flags")}


class SuplaExtendedSensor(SuplaValueSensor):
    """Backed by an extended value, which only arrives once the device sends one."""

    @property
    def _extended(self) -> dict[str, Any]:
        channel = self._channel
        if channel is None:
            return {}
        return channel.extended or {}


class SuplaEnergyPhaseSensor(SuplaExtendedSensor):
    """Forward active energy of one phase of a three-phase meter."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        phases = self._extended.get(ENERGY_KEY)
        if not isinstance(phases, list) or len(phases) < self._key.index:
            return None
        return phases[self._key.index - 1]


class SuplaCalculatedCounterSensor(SuplaExtendedSensor):
    """An impulse counter's reading scaled into real units by the device."""

    @property
    def native_value(self) -> float | None:
        return self._extended.get("calculated_value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        extended = self._extended
        return {
            "price_per_unit": extended.get("price_per_unit"),
            "total_cost": extended.get("total_cost"),
        }


class SuplaDeviceStateSensor(SuplaEntity, SensorEntity):
    """One reading out of a device's own diagnostics report."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        sensor: state_map.StateSensor,
    ) -> None:
        super().__init__(manager, device)
        self._sensor = sensor
        self._attr_unique_id = unique_id(device.guid, sensor.role)
        self._attr_name = sensor.label
        self._attr_icon = sensor.icon
        self._attr_device_info = channel_device_info(device, None)
        self._attr_native_unit_of_measurement = sensor.unit
        if sensor.device_class is not None:
            self._attr_device_class = SensorDeviceClass(sensor.device_class)
        if sensor.state_class is not None:
            self._attr_state_class = SensorStateClass(sensor.state_class)
        if sensor.options:
            self._attr_options = list(sensor.options)
        #: Held so a re-read does not nudge the answer by a second each time.
        self._instant: datetime | None = None

    @property
    def _state(self) -> dict[str, Any]:
        device = self._device
        return device.state if device is not None else {}

    @property
    def available(self) -> bool:
        device = self._device
        return bool(
            self._manager.running
            and device is not None
            and device.online
            and self._sensor.key in device.state
        )

    @property
    def native_value(self) -> Any:
        state = self._state
        value = state.get(self._sensor.key)
        if value is None:
            return None
        if not self._sensor.age_in_seconds:
            return value

        # An age is turned into the instant it counts from, and only moved when
        # it has really drifted, so the sensor does not change on every report.
        reported_at = state.get("received")
        if reported_at is None:
            return self._instant
        instant = dt_util.utc_from_timestamp(reported_at - value)
        if self._instant is None or abs(instant - self._instant) > UPTIME_DRIFT:
            self._instant = instant
        return self._instant


def async_setup_device_state_platform(
    entry: SuplaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add diagnostics sensors, now and as devices report new ones."""
    manager = entry.runtime_data

    def _async_add(device: DeviceSnapshot) -> None:
        new = [
            SuplaDeviceStateSensor(manager, device, sensor)
            for sensor in state_map.device_state_sensors(device)
            if manager.async_claim(unique_id(device.guid, sensor.role), SENSOR)
        ]
        if new:
            async_add_entities(new)

    for device in list(manager.devices.values()):
        _async_add(device)
    entry.async_on_unload(manager.async_add_device_listener(_async_add))
