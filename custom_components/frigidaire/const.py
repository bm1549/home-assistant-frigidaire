"""Constants for the frigidaire integration."""

DOMAIN = "frigidaire"
PLATFORMS = ["climate", "humidifier", "switch"]

# Keys must match SwitchDescription.key values in switch.py
SWITCH_OPTIONS: dict[str, str] = {
    "vertical_swing": "Vertical Swing",
    "clean_air_mode": "Ionizer (Clean Air Mode)",
    "display_light": "Display Light",
    "ui_lock": "Child Lock",
}
