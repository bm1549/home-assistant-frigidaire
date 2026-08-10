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
- Extra state attributes: `check_filter`, `reported_fan_speed`, and `active_alerts`;
	the legacy `current_fan_speed` alias is retained for existing templates
- `hvac_action` reflects the mode the appliance reports it is *actually* running, so an
	Eco/Auto unit shows `cooling` vs `fan` as it cycles rather than the requested mode

### Dehumidifier

- Modes: Normal (Dry), Boost (Continuous), Auto, Sleep
- Target humidity control (35-85%, 5% steps)
- Fan speed control via the `frigidaire.set_fan_mode` service: `low`, `medium`, `high`
- Extra state attributes: `current_humidity`, `check_filter`, `fan_mode`, `bin_full`

### Automatic Entities

These are created automatically, but only for appliances that actually report the
underlying value — no extra API polling is involved, since all of it arrives in the same
cloud response the climate and dehumidifier entities already use.

| Entity | Type | Description |
|---|---|---|
| Humidity | Humidity sensor | Room relative humidity, on appliances with a humidity sensor (including some ACs) |
| PM2.5 | PM2.5 sensor | Particulate concentration in µg/m³, on appliances with an air-quality sensor |
| Wi-Fi Signal | Signal strength sensor | RSSI in dBm plus a `link_quality` attribute. Diagnostic and **disabled by default** — enable it from the device page when troubleshooting |
| Connectivity | Connectivity binary sensor | Whether the cloud can currently reach the appliance. Worth alerting on: a disconnected appliance keeps serving its last-known values, so every other entity looks healthy while its data silently goes stale |

`pm10` is deliberately **not** exposed. On the appliances observed so far it alternates
between a fixed placeholder value and a value identical to `pm25`, so it carries no
information `pm25` does not already provide.

### Optional Entities

During setup — or at any time via **Configure** — you can enable additional entities per device:

| Entity | Type | Description |
|---|---|---|
| Ionizer (Clean Air Mode) | Switch | Toggles the ionizer/clean air feature |
| Display Light | Switch | Toggles the unit's display panel light |
| Child Lock | Switch | Locks the physical controls on the unit |
| Check Filter | Problem binary sensor | On for `CLEAN`, `CHANGE`, or `BUY`; exposes `filter_state` for notification automations |
| Filter Runtime | Duration sensor | Cumulative filter runtime reported by the appliance in native seconds; Home Assistant handles display-unit conversion |

Each device is configured independently, so a home with both an AC and a dehumidifier can have different entities enabled for each.
Filter runtime and the raw diagnostic attributes reuse the appliance platform's normal cloud response and do not add API polling.

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

## Reconfiguring Optional Entities

Go to **Settings → Devices & Services → Frigidaire → Configure** to change which optional entities are enabled for each device.

## Upgrading from <=0.1.26

The 0.1.27 release introduces device grouping, per-device switch configuration, and sleep mode as a preset on AC entities. After upgrading:

1. Copy the new files and restart Home Assistant — your existing climate and dehumidifier entities will continue to work without any reconfiguration.
2. To enable the new switch entities, go to **Settings → Devices & Services → Frigidaire → Configure** and select the switches you want for each device.

## If something goes wrong

- **Integration doesn't show up in the list?** Restart HA one more time. Also double-check the folder path — it should be `/config/custom_components/frigidaire/`, not nested deeper.
- **Login keeps failing?** Make sure you're using the same email and password as the Frigidaire mobile app. No extra spaces.
- **No devices after a successful login?** Open the Frigidaire app and confirm your appliances are online there. If the app can't see them, HA won't either.

Found a bug or have an idea? Open an [issue](https://github.com/bm1549/home-assistant-frigidaire/issues). PRs are welcome too.
