# Entities

## Channels

| SUPLA channel | Home Assistant |
| --- | --- |
| Light switch relay | `light` (on/off) |
| Power switch, staircase timer, pump, heat source, ring, alarm, notification | `switch` |
| Gate, garage door relay | `cover` (pulse; state from the paired opening sensor) |
| Door lock, gateway lock relay | `lock` (supports **open**, the buzz-the-door action) |
| Roller shutter, roof window, awning, curtain, projector screen, roller garage door | `cover` with position |
| Facade blind, vertical blind | `cover` with position and tilt |
| Dimmer | `light` with brightness |
| RGB lighting | `light` with colour |
| Dimmer + RGB | **two** lights: the colour half and the white dimmer |
| Opening, flood, motion, mail, hotel card sensors | `binary_sensor` |
| Thermometer, humidity, thermometer+humidity | `sensor` (two entities for the combined channel) |
| Depth, distance, wind, pressure, rain, weight, general purpose | `sensor` |
| Electricity meter | `sensor` in kWh, plus one per phase once the meter reports them |
| Impulse counter | `sensor` for the raw count, plus the scaled reading when available |
| Container, septic tank, water tank | `sensor` in % |
| HVAC thermostat | `climate` |
| HEATPOL / Home+ thermostat | `climate` |
| Open/close valve | `valve` |
| Percentage valve | `valve` with position |
| Digiglass | `switch` |
| Engine speed | `number` |
| Action trigger (buttons) | `event` + a `supla_local_action_trigger` bus event |
| [Editable settings](settings.md) | `number`, `switch`, `select`, all in the config category |

Every device also gets [diagnostic entities](#device-diagnostics) of its own.

An RGBW controller is split into two light entities on purpose: SUPLA drives the
colour channels and the white channel with independent brightness commands and
has no master dimmer, so a single entity would have to invent one.

## Device diagnostics

Devices report about themselves through SUPLA's `TDSC_ChannelState`, which the
integration asks for when a device connects and every five minutes after that.
It also picks up the same report when a device volunteers it unasked. As with
settings, a sensor only appears once the device has actually reported that
reading:

| Sensor | Notes |
| --- | --- |
| **Connection** | On while the device holds a connection. Stays readable when everything else is unavailable, and carries the source address, whether the link is encrypted, the negotiated check-in interval, protocol version and last-seen time |
| **IP address** | The address the device reports for itself |
| **Wi-Fi signal** | dBm |
| **Wi-Fi signal strength** | Percent, for devices that report it that way |
| **Up since** | When the device last booted |
| **Connected since** | When this connection began |
| **Last disconnect reason** | The device's own verdict: activity timeout, Wi-Fi lost, server lost, or unknown |
| **Battery**, **Battery health** | Battery devices only |

"Up since" and "Connected since" are timestamps rather than counters, so they
sit still instead of ticking, and they are only moved when they have really
drifted rather than on every report.

A device's **MAC address** goes onto the Home Assistant device page itself
rather than becoming a sensor.

A device that does not implement the state report simply gets none of these,
and is never asked again beyond the usual refresh.

## Buttons

Action triggers arrive as `event` entities and as a bus event you can use
directly in automations:

```yaml
automation:
  - trigger:
      - trigger: event
        event_type: supla_local_action_trigger
        event_data:
          actions: ["hold"]
    action:
      - action: light.turn_off
        target:
          entity_id: all
```

Recognised actions: `turn_on`, `turn_off`, `toggle_x1`…`toggle_x5`, `hold`,
`press_x1`…`press_x5`. The event data also carries `guid`, `channel` and the raw
`mask`.

## Behaviour worth knowing

- **A device that goes offline is not deleted.** Its entities go unavailable and
  come back, unchanged, when it reconnects.
- **A device that changes its channels is followed.** New channels get entities;
  channels that disappear take their entities with them; a channel whose
  function changes moves to the right platform instead of being duplicated.
- **Only the shape is stored.** Values are never persisted, so a restored entity
  is unavailable until its device reports rather than showing a stale reading.
- **Devices you retire can be removed** from their device page: **Settings →
  Devices & services → SUPLA Local → the device → ⋮ → Delete**. That hangs up on
  it and forgets its settings. Registration is open, so a device that is still
  plugged in and pointed here registers again within seconds and comes back —
  unplug it or point it elsewhere first. To remove everything, delete the
  integration entry, which also deletes `.storage/supla_local`.
- **Covers report positions the Home Assistant way.** SUPLA counts 0 as fully
  open, Home Assistant counts 0 as closed; the integration inverts both position
  and tilt in each direction. A calibrating drive reports no position at all.
- **Device names come from the device** and are often generic ("GUI Generic").
  Rename them in Home Assistant; the integration will not overwrite that.
- **Devices are told your Home Assistant time zone**, so staircase timers and
  weekly schedules run at the right local time.
