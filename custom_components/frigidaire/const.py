"""Constants for the frigidaire integration."""

DOMAIN = "frigidaire"
PLATFORMS = ["binary_sensor", "climate", "humidifier", "number", "sensor", "switch"]

# Keys must match SwitchDescription.key values in switch.py
SWITCH_OPTIONS: dict[str, str] = {
    "clean_air_mode": "Ionizer (Clean Air Mode)",
    "display_light": "Display Light",
    "ui_lock": "Child Lock",
}

# Keys must match diagnostic entity keys.
CONF_ACTIVE_ALERTS_SENSOR = "active_alerts"
CONF_CHECK_FILTER_SENSOR = "check_filter"
CONF_FILTER_RUNTIME_SENSOR = "filter_runtime"

BINARY_SENSOR_OPTIONS: dict[str, str] = {
    CONF_ACTIVE_ALERTS_SENSOR: "Active Alerts",
    CONF_CHECK_FILTER_SENSOR: "Check Filter",
}

SENSOR_OPTIONS: dict[str, str] = {
    CONF_FILTER_RUNTIME_SENSOR: "Filter Runtime",
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

# Optional air-conditioner diagnostics. The fan option exposes a reported state,
# not proof of physical fan motion.
CONF_COMPRESSOR_SENSOR = "compressor"
CONF_CURRENT_FAN_SPEED_SENSOR = "current_fan_speed"
