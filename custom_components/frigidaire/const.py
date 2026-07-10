"""Constants for the frigidaire integration."""

DOMAIN = "frigidaire"
PLATFORMS = ["binary_sensor", "climate", "humidifier", "number", "switch"]

# Keys must match SwitchDescription.key values in switch.py
SWITCH_OPTIONS: dict[str, str] = {
    "clean_air_mode": "Ionizer (Clean Air Mode)",
    "display_light": "Display Light",
    "ui_lock": "Child Lock",
}

# Keys must match binary sensor keys in binary_sensor.py
BINARY_SENSOR_OPTIONS: dict[str, str] = {
    "check_filter": "Check Filter",
}
