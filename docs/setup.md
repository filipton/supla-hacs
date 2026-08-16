# Setup

The setup screen leads with the address to type into your devices, and asks
only what usually matters:

| Option | Default | Notes |
| --- | --- | --- |
| Accept TLS connections | on | Generates a self-signed certificate on first start |
| Consider a device offline after | `30` s | How quickly a device that lost power is noticed |
| Use custom ports | off | Only if 2015 or 2016 is already taken on this machine |

SUPLA devices look for **2015** and **2016**, so those are used unless you tick
**Use custom ports**, which opens a second screen for them. The TLS port is
only asked for when TLS is on. Everything is reachable again later from the
integration's **Configure** button; the listener restarts in place.

## Point your devices at Home Assistant

In each device's web configuration:

1. **Server** — the Home Assistant host's IP address (the config flow shows it).
2. **Email / Location ID / AuthKey** — anything. [Registration is open](troubleshooting.md#registration-is-open-on-purpose).
3. **SSL** — either turn it off (port 2015) or leave it on and set the security
   level to **skip CA check**, because the certificate is self-signed.

Devices do not probe for ports; they connect exactly where they are configured
to.

## Networking

Ports 2015 and 2016 must be reachable on the Home Assistant host.

- **Home Assistant OS / Supervised** — works out of the box.
- **Docker / Container** — publish the ports (`-p 2015:2015 -p 2016:2016`), or
  run the container with `--network host`.

## How a dead device is noticed

A device that loses power never closes its TCP connection — no FIN is ever
sent, so the socket sits half open and reading from it would block forever.
SUPLA handles this with a check-in interval: the device proposes one, the
server answers with the value it wants, and the device adopts that. Silence
past the interval means the device is gone.

The **offline after** setting is that budget. The interval devices are given is
this value minus a 10 second grace, kept inside the protocol's 10–240 second
range, so 30 seconds of silence is one missed check-in plus slack. Twenty
seconds is the floor the protocol allows; lower is not possible, and lower
values mean slightly more chatter. Battery devices that advertise sleep mode
are exempt and keep whatever interval they asked for.

For comparison, upstream `supla-server` disconnects at exactly the interval
with no grace at all.

## Testing against a server on another machine

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
