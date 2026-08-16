# Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.supla_local: debug
```

The integration's **Download diagnostics** button dumps the full device tree,
what each channel decoded to, and which entities were derived from it.

## Registration is open, on purpose

The server accepts **every** device that connects, whatever GUID, email or
AuthKey it presents. That is what makes setup a one-liner on the device side,
and it means any SUPLA device on your LAN that is pointed at Home Assistant will
appear. Keep the ports off the public internet.
