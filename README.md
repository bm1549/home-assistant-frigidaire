# Home Assistant Custom Component for Frigidaire

[![Latest Release](https://img.shields.io/github/release/bm1549/home-assistant-frigidaire/all.svg?style=for-the-badge)](https://github.com/bm1549/home-assistant-frigidaire/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![License](https://img.shields.io/github/license/bm1549/home-assistant-frigidaire?style=for-the-badge)](LICENSE)
[![Maintainer](https://img.shields.io/badge/MAINTAINER-%40bm154969-red?style=for-the-badge)](https://github.com/bm1549)
[![Community Forum](https://img.shields.io/badge/COMMUNITY-FORUM-success?style=for-the-badge)](https://community.home-assistant.io)

A Home Assistant integration for Frigidaire WiFi-connected appliances, using the Frigidaire 2.0 (Electrolux) cloud API.

## Supported Devices

- **Air Conditioners** — window, portable, and inverter models
- **Dehumidifiers**

## Features

### Air Conditioner

- HVAC modes: Cool, Auto (Eco), Fan Only, Dry, Off
- Fan speed: Auto, Low, Medium, High
- Target temperature control (°F and °C)
- Preset modes: Sleep
- Swing modes: Vertical, Off
- ON/OFF timer control (30-minute increments, up to 24 hours)
- Extra state attributes: `check_filter`

### Dehumidifier

- Modes: Normal (Dry), Boost (Continuous), Auto, Sleep
- Target humidity control (35-85%, 5% steps)
- Fan speed control via the `frigidaire.set_fan_mode` service: `low`, `medium`, `high`
- Extra state attributes: `current_humidity`, `check_filter`, `fan_mode`, `bin_full`

### Optional Switch Entities

During setup — or at any time via **Configure** — you can enable additional switch entities per device:

| Switch | Description |
|---|---|
| Ionizer (Clean Air Mode) | Toggles the ionizer/clean air feature |
| Display Light | Toggles the unit's display panel light |
| Child Lock | Locks the physical controls on the unit |

Each device is configured independently, so a home with both an AC and a dehumidifier can have different switches enabled for each.

## Installing

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** and search for **Frigidaire**.
3. Click **Download** and restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **Frigidaire**.
5. Enter your Frigidaire account email and password.

### Manual

1. Clone or download this repo.
2. Copy the `custom_components/frigidaire/` folder into `/config/custom_components/frigidaire/` on your HA instance.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **Frigidaire**.
5. Enter your Frigidaire account email and password.

## Reconfiguring Switch Entities

Go to **Settings → Devices & Services → Frigidaire → Configure** to change which switch entities are enabled for each device.

## Upgrading from 0.1.x

The 0.2.0 release introduces device grouping, per-device switch configuration, and sleep mode as a preset on AC entities. After upgrading:

1. Copy the new files and restart Home Assistant — your existing climate and dehumidifier entities will continue to work without any reconfiguration.
2. To enable the new switch entities, go to **Settings → Devices & Services → Frigidaire → Configure** and select the switches you want for each device.

## If something goes wrong

- **Integration doesn't show up in the list?** Restart HA one more time. Also double-check the folder path — it should be `/config/custom_components/frigidaire/`, not nested deeper.
- **Login keeps failing?** Make sure you're using the same email and password as the Frigidaire mobile app. No extra spaces.
- **No devices after a successful login?** Open the Frigidaire app and confirm your appliances are online there. If the app can't see them, HA won't either.

Found a bug or have an idea? Open an [issue](https://github.com/bm1549/home-assistant-frigidaire/issues). PRs are welcome too.
