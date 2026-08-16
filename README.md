# SUPLA Local

A Home Assistant integration that **is** a SUPLA server. Your SUPLA devices
connect straight to Home Assistant over their own TCP link, so state arrives as
a push the moment it changes — no cloud account, no MQTT broker, no polling.

Devices appear on the **Settings → Devices** page by themselves as soon as they
dial in, the same way Zigbee or Z-Wave devices show up under their hub.

- **Local push.** The device's own connection is the transport.
- **No storage of your own to configure.** Home Assistant's device and entity
  registries remember names, areas and entity IDs; the integration keeps a small
  file of its own so entities exist again right after a restart, before any
  device has reconnected.
- **Stable entity IDs** across restarts, re-registrations and firmware changes.

## Installation

### HACS (custom repository)

HACS is not aware of this repository yet, so add it once by hand:

1. **HACS** → **⋮** (top right) → **Custom repositories**
2. Repository: `https://github.com/filipton/supla-hacs`
   Type: **Integration** → **Add**
3. Search HACS for **SUPLA Local** → **Download**
4. **Restart Home Assistant**
5. **Settings → Devices & services → + Add integration → SUPLA Local**

HACS installs the newest GitHub release, or the default branch if the repository
has none. To publish one from a checkout:

```sh
git tag v0.1.0 && git push origin v0.1.0
gh release create v0.1.0 --title v0.1.0 --notes "First release"
```

Bump `"version"` in `custom_components/supla_local/manifest.json` to match, or
HACS will keep offering the same update.

### Manual install (no HACS)

Run this on the Home Assistant host, from the directory holding
`configuration.yaml` (`/config` on Home Assistant OS, reachable through the
**Terminal & SSH** add-on or a Samba share):

```sh
mkdir -p custom_components
git clone --depth 1 https://github.com/filipton/supla-hacs /tmp/supla-hacs
cp -r /tmp/supla-hacs/custom_components/supla_local custom_components/
rm -rf /tmp/supla-hacs
```

Restart Home Assistant, then add the integration from
**Settings → Devices & services**. Re-run the same three lines to update; only
`custom_components/supla_local/` matters, nothing else in this repository is
installed.

## Setup

The config flow asks for three things:

| Option | Default | Notes |
| --- | --- | --- |
| Plain TCP port | `2015` | Devices with SSL turned off |
| Accept TLS connections | on | Generates a self-signed certificate on first start |
| TLS port | `2016` | Devices with SSL turned on |

Both ports are test-bound during setup, so a clash (for example with the
standalone `supla-server` in this repo) is reported instead of failing silently
later. Ports can be changed afterwards from the integration's **Configure**
button; the listener restarts in place.

The TLS key pair lives in `config/supla_local/`. Delete it to force a new one.

### Point your devices at Home Assistant

In each device's web configuration:

1. **Server** — the Home Assistant host's IP address (the config flow shows it).
2. **Email / Location ID / AuthKey** — anything. Registration is open, see below.
3. **SSL** — either turn it off (port 2015) or leave it on and set the security
   level to **skip CA check**, because the certificate is self-signed.

Devices do not probe for ports; they connect exactly where they are configured
to.

### Networking

Ports 2015 and 2016 must be reachable on the Home Assistant host.

- **Home Assistant OS / Supervised** — works out of the box.
- **Docker / Container** — publish the ports (`-p 2015:2015 -p 2016:2016`), or
  run the container with `--network host`.

### Testing against a server on another machine

Devices connect exactly where they are configured to and reconfiguring a wall
switch to try something out is tedious. `tools/supla_proxy.py` forwards the two
ports from the machine the devices already point at to wherever the real server
is now running:

```sh
# on the PC the devices are configured for
python3 tools/supla_proxy.py 192.168.1.10        # 2015 and 2016 -> 192.168.1.10
```

```
14:02:11 INFO    listening on 0.0.0.0:2015 -> 192.168.1.10:2015
14:02:11 INFO    listening on 0.0.0.0:2016 -> 192.168.1.10:2016
14:02:11 INFO    forwarding to 192.168.1.10, press Ctrl+C to stop
14:02:18 INFO    #1 192.168.1.50:49722 connected via :2015 -> 192.168.1.10:2015
14:02:41 INFO    #1 192.168.1.50:49722 closed, 1.2 kB up / 380 B down
```

It relays raw TCP, so port 2016 needs no certificate here: the TLS session is
negotiated end to end between the device and the real server, and the proxy
never sees the plaintext.

| | |
| --- | --- |
| `-p, --port PORT[:TARGET]` | forward one port, repeatable; defaults to 2015 and 2016 |
| `-l, --listen ADDR` | bind address, default all interfaces |
| `-v, --verbose` | log every relay detail |

```sh
python3 tools/supla_proxy.py 192.168.1.10 --port 2015          # plain only
python3 tools/supla_proxy.py ha.local --port 2015:12015        # different port there
```

Standard library only, so any Python 3.9+ runs it — no virtualenv needed.

### Registration is open, on purpose

The server accepts **every** device that connects, whatever GUID, email or
AuthKey it presents. That is what makes setup a one-liner on the device side,
and it means any SUPLA device on your LAN that is pointed at Home Assistant will
appear. Keep the ports off the public internet.

## What you get

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
| Editable settings (see below) | `number`, `switch`, `select`, all diagnostic/config |

Every device also gets a diagnostic **Connection** binary sensor, which stays
readable while the rest of its entities are unavailable.

An RGBW controller is split into two light entities on purpose: SUPLA drives the
colour channels and the white channel with independent brightness commands and
has no master dimmer, so a single entity would have to invent one.

### Changing device settings

Settings that would normally live in the SUPLA app or cloud are editable from
Home Assistant, as **configuration** entities on each device page. In SUPLA the
server owns configuration: the device asks for it after registering and applies
whatever it is given, so these are real settings on the hardware, not something
Home Assistant simulates on top.

| Where | Setting |
| --- | --- |
| Roller shutters, awnings, curtains, screens, roller garage doors | opening time, closing time, motor direction reversed, buttons reversed |
| Facade and vertical blinds | the above plus tilting time, tilt 0/100 angle, tilt behaviour |
| Staircase timers | timer duration |
| Power and light switches | overcurrent threshold, when the hardware supports it |
| Binary sensors | inverted logic, input filtering time, reset timeout |
| Thermometers and humidity sensors | temperature offset, humidity offset |
| The device itself | status LED, power status LED, screen brightness and auto-brightness, button volume, local controls lock, automatic time sync, home screen content and off delay |

**Only what a device offers is shown.** A channel gets settings once it either
advertises `SUPLA_CHANNEL_FLAG_RUNTIME_CHANNEL_CONFIG_UPDATE` or has told the
server what it is running; device-level settings come from the availability
bitmap the device reports. A device that offers nothing gets no configuration
entities, rather than a page of controls that would fail.

A setting the device has never reported reads as unknown rather than as a
made-up zero, and a change the device refuses surfaces its reason (for example
"local configuration disabled" when the setting is locked on the device's own
web page).

**Writes are edits, not rewrites.** A change takes the exact bytes the device
last reported, overwrites the one field, and sends them back, so reserved
regions and any setting this integration does not model survive untouched.

Weekly schedules are deliberately not exposed: Home Assistant automations do
that job better, and the schedule struct is 336 bytes of state worth not
duplicating.

If something is missing, **Download diagnostics** lists every configuration
struct your devices reported, the decoded values and which settings were
derived from them — that is the quickest way to see what your hardware
actually supports.

### Buttons

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
- **Devices you retire can be removed** from their Home Assistant device page,
  once they are actually disconnected.
- **Covers report positions the Home Assistant way.** SUPLA counts 0 as fully
  open, Home Assistant counts 0 as closed; the integration inverts both position
  and tilt in each direction. A calibrating drive reports no position at all.
- **Device names come from the device** and are often generic ("GUI Generic").
  Rename them in Home Assistant; the integration will not overwrite that.
- **Devices are told your Home Assistant time zone**, so staircase timers and
  weekly schedules run at the right local time.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.supla_local: debug
```

The integration's **Download diagnostics** button dumps the full device tree,
what each channel decoded to, and which entities were derived from it.

## This repository

| Path | What it is |
| --- | --- |
| `custom_components/supla_local/` | The Home Assistant integration |
| `custom_components/supla_local/server/` | Vendored copy of the server package |
| `supla_server/` | The standalone server, with a REST API and a test web panel |
| `tools/supla_proxy.py` | TCP port forwarder for testing against another host |
| `tests/` | Server tests, plus Home Assistant integration tests |

`custom_components/supla_local/server/` is a byte-identical copy of
`supla_server/` minus `http_api.py`, `app.py`, `__main__.py` and `web/`, so the
two stay in sync. Nothing outside the Python standard library and `cryptography`
is needed, and both ship with Home Assistant.

### Running the tests

```sh
uv venv --python 3.13 .venv
uv pip install -r requirements_test.txt
.venv/bin/python -m pytest tests
```
