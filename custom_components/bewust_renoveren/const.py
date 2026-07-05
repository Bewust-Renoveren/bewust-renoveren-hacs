"""Constants for the Bewust Renoveren integration."""

from __future__ import annotations

from typing import Any, Final

DOMAIN: Final = "bewust_renoveren"

# Defaults
DEFAULT_PUSH_INTERVAL: Final = 900  # 15 minutes in seconds
DEFAULT_ENDPOINT: Final = "https://app.bewustrenoveren.app"

# Ingest/provisioning API paths (appended to the configured endpoint)
INGEST_PATH: Final = "/api/v1/sensors/ingest"
PROVISION_PATH: Final = "/api/v1/provision/register"

# Config keys (stored on the config entry)
CONF_API_KEY: Final = "api_key"
CONF_ENDPOINT: Final = "endpoint"
CONF_PUSH_INTERVAL: Final = "push_interval"
CONF_KLANT_ID: Final = "klant_id"
CONF_WONING_ID: Final = "woning_id"

# Registration form keys (used only during the config flow, not persisted)
CONF_INSTALLER_CODE: Final = "installer_code"
CONF_KLANT_NAAM: Final = "klant_naam"
CONF_EMAIL: Final = "email"
CONF_ADRES: Final = "adres"
CONF_WONING_LABEL: Final = "woning_label"


# Push interval options: value in seconds
PUSH_INTERVALS: Final[list[dict[str, int | str]]] = [
    {"value": 60, "label": "1 minute"},
    {"value": 120, "label": "2 minutes"},
    {"value": 300, "label": "5 minutes"},
    {"value": 600, "label": "10 minutes"},
    {"value": 900, "label": "15 minutes (recommended)"},
    {"value": 1800, "label": "30 minutes"},
]

# Supported device classes for auto-discovery
SUPPORTED_DEVICE_CLASSES: Final[set[str]] = {
    "temperature",
    "humidity",
    "carbon_dioxide",
    "atmospheric_pressure",
    "pm25",
    "pm10",
    "volatile_organic_compounds",
    "energy",
    "power",
    "window",
    "door",
    "occupancy",
    "motion",
}

# Mapping from HA device_class to our canonical sensor type name
DEVICE_CLASS_TO_TYPE: Final[dict[str, str]] = {
    "temperature": "temperature",
    "humidity": "humidity",
    "carbon_dioxide": "co2",
    "atmospheric_pressure": "pressure",
    "pm25": "pm25",
    "pm10": "pm10",
    "volatile_organic_compounds": "voc",
    "energy": "energy",
    "power": "power",
    "window": "window",
    "door": "door",
    "occupancy": "occupancy",
    "motion": "motion",
}

# Sensor type definitions
# Each entry: key -> {unit, device_class, domain, name}
# domain is the HA entity domain (sensor or binary_sensor)
SENSOR_TYPES: Final[dict[str, dict[str, Any]]] = {
    "co2": {
        "unit": "ppm",
        "device_class": "carbon_dioxide",
        "domain": "sensor",
        "name": "CO2",
    },
    "temperature": {
        "unit": "celsius",
        "device_class": "temperature",
        "domain": "sensor",
        "name": "Temperature",
    },
    "humidity": {
        "unit": "percent",
        "device_class": "humidity",
        "domain": "sensor",
        "name": "Humidity",
    },
    "pressure": {
        "unit": "hPa",
        "device_class": "atmospheric_pressure",
        "domain": "sensor",
        "name": "Pressure",
    },
    "pm25": {
        "unit": "ug/m3",
        "device_class": "pm25",
        "domain": "sensor",
        "name": "PM2.5",
    },
    "pm10": {
        "unit": "ug/m3",
        "device_class": "pm10",
        "domain": "sensor",
        "name": "PM10",
    },
    "voc": {
        "unit": "index",
        "device_class": "volatile_organic_compounds",
        "domain": "sensor",
        "name": "VOC",
    },
    "energy": {
        "unit": "kWh",
        "device_class": "energy",
        "domain": "sensor",
        "name": "Energy",
    },
    "power": {
        "unit": "W",
        "device_class": "power",
        "domain": "sensor",
        "name": "Power",
    },
    "window": {
        "unit": "boolean",
        "device_class": "window",
        "domain": "binary_sensor",
        "name": "Window",
    },
    "door": {
        "unit": "boolean",
        "device_class": "door",
        "domain": "binary_sensor",
        "name": "Door",
    },
    "occupancy": {
        "unit": "boolean",
        "device_class": "occupancy",
        "domain": "binary_sensor",
        "name": "Occupancy",
    },
    "motion": {
        "unit": "boolean",
        "device_class": "motion",
        "domain": "binary_sensor",
        "name": "Motion",
    },
}

# Coordinator retry settings
MAX_RETRIES: Final = 3
BACKOFF_BASE: Final = 1  # seconds; exponential: 1s, 4s, 16s
OFFLINE_BUFFER_MAX: Final = 672  # ~7 days of buffered batches at the 15min interval

# Persistent offline queue (homeassistant.helpers.storage.Store)
STORAGE_VERSION: Final = 1

# Sensor entity keys
STATUS_SENSOR_ID: Final = "status"
LAST_SYNC_SENSOR_ID: Final = "last_sync"
QUEUED_SENSOR_ID: Final = "queued_batches"
