"""Constants for the frigidaire integration."""

DOMAIN = "frigidaire"
PLATFORMS = ["climate", "humidifier", "number", "switch"]

# Keys must match SwitchDescription.key values in switch.py
SWITCH_OPTIONS: dict[str, str] = {
    "clean_air_mode": "Ionizer (Clean Air Mode)",
    "display_light": "Display Light",
    "ui_lock": "Child Lock",
}
