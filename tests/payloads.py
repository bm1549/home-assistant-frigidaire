"""Raw appliance records shaped like the Frigidaire /appliance/api/v2/appliances response.

Each record is what the cloud returns for one appliance. Only `properties.reported` reaches
the entities (via the coordinator), but the full record is kept so the stub client mirrors
the real library's data flow.

LEGACY_AC uses the uppercase enum spelling older window units report; TELICA_AC is trimmed
from a real GHPH142AA1 response (bm1549/frigidaire#76) and uses the lowercase spelling newer
firmware reports. Entities normalise both.
"""

from __future__ import annotations

import copy

LEGACY_AC: dict = {
    "applianceId": "AC-LEGACY-1",
    "applianceData": {"modelName": "AC", "applianceName": "Bedroom AC"},
    "properties": {
        "reported": {
            "applianceState": "RUNNING",
            "mode": "COOL",
            "fanSpeedSetting": "AUTO",
            "fanSpeedState": "LOW",
            "filterState": "GOOD",
            "sleepMode": "OFF",
            "verticalSwing": "OFF",
            "uiLockMode": False,
            "ambientTemperatureF": 75,
            "targetTemperatureF": 72,
            "temperatureRepresentation": "FAHRENHEIT",
            "startTime": 0,
            "stopTime": 0,
            "alerts": [],
        }
    },
    "status": "enabled",
    "connectionState": "Connected",
}

TELICA_AC: dict = {
    "applianceId": "AC-TELICA-1",
    "applianceData": {"modelName": "Telica", "applianceName": "Office AC"},
    "properties": {
        "reported": {
            "applianceState": "running",
            "mode": "fanOnly",
            "modeState": "fanOnly",
            "fanSpeedSetting": "auto",
            "fanSpeedState": "high",
            "filterState": "good",
            "sleepMode": "off",
            "uiLockMode": False,
            "ambientTemperatureF": 72,
            "targetTemperatureF": 60,
            "temperatureRepresentation": "fahrenheit",
            "sensorHumidity": 86,
            "pm25": 2,
            "pm10": 199,
            "networkInterface": {"linkQualityIndicator": "EXCELLENT", "rssi": -41},
            "alerts": [],
        }
    },
    "status": "enabled",
    "connectionState": "Connected",
}

DEHUMIDIFIER: dict = {
    "applianceId": "DH-1",
    "applianceData": {"modelName": "DH", "applianceName": "Basement Dehumidifier"},
    "properties": {
        "reported": {
            "applianceState": "RUNNING",
            "mode": "DRY",
            "fanSpeedSetting": "LOW",
            "filterState": "GOOD",
            "sensorHumidity": 55,
            "targetHumidity": 45,
            "waterBucketLevel": 0,
            "displayLight": "ON",
            "cleanAirMode": "OFF",
            "uiLockMode": False,
            "alerts": [],
        }
    },
    "status": "enabled",
    "connectionState": "Connected",
}


def with_reported(record: dict, **changes) -> dict:
    """Return a deep copy of ``record`` with ``properties.reported`` keys replaced by ``changes``."""
    updated = copy.deepcopy(record)
    updated["properties"]["reported"].update(changes)
    return updated
