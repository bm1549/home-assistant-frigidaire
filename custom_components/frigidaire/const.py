"""Constants for the frigidaire integration."""

DOMAIN = "frigidaire"
PLATFORMS = ["binary_sensor", "climate", "humidifier", "number", "sensor", "switch"]

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

# Climate compressor-state estimation options. Set per air-conditioner appliance
# via the integration's Configure (options) flow and consumed by climate.py when
# inferring hvac_action.
CONF_COOL_HYSTERESIS = "cool_hysteresis"
CONF_COMPRESSOR_OFF_DELAY = "compressor_off_delay"

# Degrees (in the device's display unit) of deadband around the setpoint used
# when estimating compressor state. The compressor is reported cooling above
# target + hysteresis and idle below target - hysteresis; inside the band the
# last estimate is held. 0 disables the deadband.
DEFAULT_COOL_HYSTERESIS = 0.0

# Seconds the room must stay below the setpoint band before the compressor is
# reported off. Models compressor run-on and avoids flapping near the setpoint.
DEFAULT_COMPRESSOR_OFF_DELAY = 300

# Optional per-air-conditioner diagnostic entities exposed via the options flow:
# a binary sensor mirroring the estimated compressor (cooling) state and a sensor
# reporting the actual running fan speed.
CONF_COMPRESSOR_SENSOR = "compressor"
CONF_CURRENT_FAN_SPEED_SENSOR = "current_fan_speed"
