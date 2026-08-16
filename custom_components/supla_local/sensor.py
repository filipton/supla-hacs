"""Sensor platform: thermometers, meters, measurements and tank levels."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import (
    ROLE_CALCULATED,
    ROLE_HUMIDITY,
    ROLE_PHASE,
    ROLE_TEMPERATURE,
    SENSOR,
    EntityKey,
    impulse_counter_meta,
    measurement_meta,
)
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K

#: SUPLA reports an out-of-range temperature when the probe is not connected.
INVALID_TEMPERATURE = -273.0

ENERGY_KEY = "total_forward_active_energy_kwh"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, SENSOR, async_add_entities, _build)


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
