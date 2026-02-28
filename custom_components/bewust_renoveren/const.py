"""Constants for the Bewust Renoveren integration."""

from __future__ import annotations

from typing import Any, Final

DOMAIN: Final = "bewust_renoveren"

# Defaults
DEFAULT_PUSH_INTERVAL: Final = 300  # 5 minutes in seconds
DEFAULT_ENDPOINT: Final = "https://ingest-e3prasv6sq-ew.a.run.app"

# Config keys
CONF_API_KEY: Final = "api_key"
CONF_ENDPOINT: Final = "endpoint"
CONF_PUSH_INTERVAL: Final = "push_interval"
CONF_ROOMS: Final = "rooms"
CONF_ROOM_NAME: Final = "name"
CONF_ROOM_ENTITIES: Final = "entities"

# Push interval options: value in seconds
PUSH_INTERVALS: Final[list[dict[str, int | str]]] = [
    {"value": 60, "label": "1 minute"},
    {"value": 120, "label": "2 minutes"},
    {"value": 300, "label": "5 minutes (recommended)"},
    {"value": 600, "label": "10 minutes"},
    {"value": 900, "label": "15 minutes"},
    {"value": 1800, "label": "30 minutes"},
]

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
        "unit": "µg/m³",
        "device_class": "pm25",
        "domain": "sensor",
        "name": "PM2.5",
    },
    "pm10": {
        "unit": "µg/m³",
        "device_class": "pm10",
        "domain": "sensor",
        "name": "PM10",
    },
    "tvoc": {
        "unit": "index",
        "device_class": "volatile_organic_compounds",
        "domain": "sensor",
        "name": "TVOC",
    },
    "window_door": {
        "unit": "boolean",
        "device_class": ["window", "door"],
        "domain": "binary_sensor",
        "name": "Window/Door",
    },
    "occupancy": {
        "unit": "boolean",
        "device_class": ["occupancy", "motion"],
        "domain": "binary_sensor",
        "name": "Occupancy",
    },
    "energy": {
        "unit": "kWh",
        "device_class": "energy",
        "domain": "sensor",
        "name": "Energy",
    },
}

# Required sensor types per room (must be mapped for a valid room)
REQUIRED_SENSOR_TYPES: Final[list[str]] = ["co2", "temperature", "humidity"]

# Optional sensor types per room
OPTIONAL_SENSOR_TYPES: Final[list[str]] = [
    "pressure",
    "pm25",
    "pm10",
    "tvoc",
    "window_door",
    "occupancy",
    "energy",
]

# Coordinator retry settings
MAX_RETRIES: Final = 3
BACKOFF_BASE: Final = 1  # seconds; exponential: 1s, 4s, 16s
OFFLINE_BUFFER_MAX: Final = 12  # max buffered batches (~1 hour at 5min interval)

# Sensor entity keys
STATUS_SENSOR_ID: Final = "status"
LAST_SYNC_SENSOR_ID: Final = "last_sync"
