"""Event platform: SUPLA action triggers, i.e. wall-switch button presses."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import SuplaConfigEntry
from .channel_map import EVENT, EntityKey
from .const import ACTION_TRIGGER_EVENT_TYPES, SIGNAL_ACTION_TRIGGER
from .entity import (
    AddConfigEntryEntitiesCallback,
    SuplaChannelEntity,
    async_setup_channel_platform,
)
from .manager import SuplaManager
from .models import ChannelSnapshot, DeviceSnapshot


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuplaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_channel_platform(entry, EVENT, async_add_entities, _build)


def _build(
    manager: SuplaManager,
    device: DeviceSnapshot,
    channel: ChannelSnapshot,
    key: EntityKey,
) -> SuplaChannelEntity | None:
    return SuplaActionTriggerEvent(manager, device, channel, key)


class SuplaActionTriggerEvent(SuplaChannelEntity, EventEntity):
    """Fires on every press the device reports for this button.

    The device only sends the actions the server enabled during channel
    config; the session enables everything the button advertises.
    """

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(ACTION_TRIGGER_EVENT_TYPES)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ACTION_TRIGGER.format(self._guid, self._channel_number),
                self._async_handle_action,
            )
        )

    @callback
    def _async_handle_update(self) -> None:
        # The regular device update carries the last bitmask, which is state,
        # not a press. Only availability can change here.
        self.async_write_ha_state()

    @callback
    def _async_handle_action(self, actions: list[str]) -> None:
        if not actions:
            return
        # A press sets a single capability bit; the rest is kept for the record.
        self._trigger_event(actions[0], {"actions": actions})
        self.async_write_ha_state()
