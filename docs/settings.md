# Device settings

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
