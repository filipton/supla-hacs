<p align="center">
  <img src="https://raw.githubusercontent.com/filipton/supla-hacs/master/custom_components/supla_local/brand/icon.png" width="128" alt="SUPLA Local" />
</p>

<h1 align="center">SUPLA Local</h1>

<p align="center">
  <a href="https://github.com/filipton/supla-hacs/releases"><img src="https://img.shields.io/github/v/release/filipton/supla-hacs?style=flat-square" alt="GitHub Release" /></a>
  <a href="https://github.com/filipton/supla-hacs/releases"><img src="https://img.shields.io/github/release-date/filipton/supla-hacs?style=flat-square" alt="GitHub Release Date" /></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square" alt="HACS Custom" /></a>
</p>

A Home Assistant integration that **is** a SUPLA server.

Your SUPLA devices connect straight to Home Assistant over their own TCP link.
No cloud account, no MQTT broker, no polling — devices show up on the Devices
page by themselves, the way Zigbee or Z-Wave devices appear under their hub.

## Setup

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=filipton&repository=supla-hacs&category=integration)

Add this repository to HACS as a custom repository, download **SUPLA Local**,
then restart Home Assistant.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=supla_local)

In each device's web configuration, set the **server address** to your Home
Assistant host. Any email, Location ID and AuthKey is accepted. With SSL on,
set the device's security level to **skip CA check**.

## Docs

- [Setup](docs/setup.md) — ports, TLS, networking, offline detection
- [Entities](docs/entities.md) — what each SUPLA channel becomes
- [Device settings](docs/settings.md) — change hardware settings from Home Assistant
- [Troubleshooting](docs/troubleshooting.md)
- [Development](docs/development.md)

## Worth knowing

- Ports **2015** and **2016** must be reachable on the Home Assistant host. On
  Docker, publish them.
- The server accepts **every** device that connects. Keep the ports off the
  public internet.
