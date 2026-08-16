"""Climate platform: HVAC channels and legacy HEATPOL thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant

from . import SuplaConfigEntry
from .channel_map import CLIMATE, EntityKey, find_thermometer, hvac_modes
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot
from .server import channels as K
from .server import consts as C

PRESET_MANUAL = "manual"
PRESET_SCHEDULE = "schedule"

MIN_TEMP = 5.0
MAX_TEMP = 40.0

_MODE_BY_ID: dict[int, HVACMode] = {
    C.SUPLA_HVAC_MODE_OFF: HVACMode.OFF,
    C.SUPLA_HVAC_MODE_HEAT: HVACMode.HEAT,
    C.SUPLA_HVAC_MODE_COOL: HVACMode.COOL,
    C.SUPLA_HVAC_MODE_HEAT_COOL: HVACMode.HEAT_COOL,
    C.SUPLA_HVAC_MODE_FAN_ONLY: HVACMode.FAN_ONLY,
    C.SUPLA_HVAC_MODE_DRY: HVACMode.DRY,
}

_ACTION_BY_MODE: dict[HVACMode, str] = {
    HVACMode.OFF: "off",
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
    HVACMode.HEAT_COOL: "auto",
    # SUPLA has no dry/fan command; these channels only know on and off.
    HVACMode.DRY: "turn_on",
    HVACMode.FAN_ONLY: "turn_on",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, CLIMATE, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    if key.kind == K.KIND_THERMOSTAT_HEATPOL:
        return SuplaHeatpolThermostat(manager, device, channel, key)
    return SuplaHvacClimate(manager, device, channel, key)


class SuplaClimateBase(SuplaChannelEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 0.1
    # Opt out of the 2024.x turn_on/turn_off shim; both are declared explicitly.
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device, channel, key)
        self._thermometer_channel = find_thermometer(device, channel)


class SuplaHvacClimate(SuplaClimateBase):
    """A modern SUPLA HVAC channel.

    HVAC commands are instructions, not state: nothing is written optimistically
    and the entity waits for the device to report what it actually did.
    """

    def __init__(
        self,
        manager: SuplaManager,
        device: DeviceSnapshot,
        channel: ChannelSnapshot,
        key: EntityKey,
    ) -> None:
        super().__init__(manager, device, channel, key)
        self._base_modes = tuple(HVACMode(mode) for mode in hvac_modes(channel.function))

        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if HVACMode.HEAT_COOL in self._base_modes:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        self._attr_supported_features = features
        self._attr_preset_modes = [PRESET_MANUAL, PRESET_SCHEDULE]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        # A thermostat configured for cooling reports COOL even though its
        # function only promises heating, so whatever it reports is offered too.
        modes = list(self._base_modes)
        reported = _MODE_BY_ID.get(self._value.get("mode_id", -1))
        if reported is not None and reported not in modes:
            modes.append(reported)
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        value = self._value
        if not value:
            return None
        if not value.get("on"):
            return HVACMode.OFF
        return _MODE_BY_ID.get(value.get("mode_id", -1))

    @property
    def hvac_action(self) -> HVACAction | None:
        value = self._value
        if not value:
            return None
        if not value.get("on"):
            return HVACAction.OFF
        if value.get("heating"):
            return HVACAction.HEATING
        if value.get("cooling"):
            return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        temperature = self._sibling_value(self._thermometer_channel).get("temperature")
        if temperature is None or temperature <= -273:
            return None
        return temperature

    @property
    def target_temperature(self) -> float | None:
        value = self._value
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return None
        if self.hvac_mode == HVACMode.COOL:
            return value.get("setpoint_cool")
        return value.get("setpoint_heat")

    @property
    def target_temperature_low(self) -> float | None:
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._value.get("setpoint_heat")

    @property
    def target_temperature_high(self) -> float | None:
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._value.get("setpoint_cool")

    @property
    def preset_mode(self) -> str:
        return PRESET_SCHEDULE if self._value.get("weekly_schedule") else PRESET_MANUAL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # 0-100% modulation for channels that report a proportional output.
        return {"output_level": self._value.get("level")}

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._async_send({"action": _ACTION_BY_MODE[HVACMode(hvac_mode)]})

    async def async_turn_on(self) -> None:
        await self._async_send({"action": "turn_on"})

    async def async_turn_off(self) -> None:
        await self._async_send({"action": "off"})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        action = "weekly_schedule" if preset_mode == PRESET_SCHEDULE else "manual"
        await self._async_send({"action": action})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (mode := kwargs.get("hvac_mode")) is not None:
            await self.async_set_hvac_mode(HVACMode(mode))

        command: dict[str, Any] = {"action": "setpoint"}
        low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if low is not None or high is not None:
            if low is not None:
                command["setpoint_heat"] = float(low)
            if high is not None:
                command["setpoint_cool"] = float(high)
        elif (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            key = (
                "setpoint_cool"
                if self.hvac_mode == HVACMode.COOL
                else "setpoint_heat"
            )
            command[key] = float(temperature)
        else:
            return
        await self._async_send(command)


class SuplaHeatpolThermostat(SuplaClimateBase):
    """The older HEATPOL / Home+ thermostat channel: on, off and one setpoint."""

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.5

    @property
    def hvac_mode(self) -> HVACMode | None:
        on = self._value.get("on")
        if on is None:
            return None
        return HVACMode.HEAT if on else HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        measured = self._value.get("measured_temperature")
        if measured is None or measured <= -273:
            # Some units report nothing themselves but sit next to a probe.
            fallback = self._sibling_value(self._thermometer_channel).get("temperature")
            return None if fallback is None or fallback <= -273 else fallback
        return measured

    @property
    def target_temperature(self) -> float | None:
        return self._value.get("preset_temperature")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._async_send(
            {"action": "on" if HVACMode(hvac_mode) == HVACMode.HEAT else "off"}
        )

    async def async_turn_on(self) -> None:
        await self._async_send({"action": "on"})

    async def async_turn_off(self) -> None:
        await self._async_send({"action": "off"})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._async_send({"action": "setpoint", "setpoint": float(temperature)})
