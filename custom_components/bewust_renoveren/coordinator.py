"""Data update coordinator for Bewust Renoveren.

Auto-discovers sensor and binary_sensor entities by device_class, builds a
single payload with all discovered readings, and POSTs to the cloud endpoint.

Features:
  - Auto-discovery: scans hass.states for matching device_class
  - Single bulk POST per interval (not per room)
  - Exponential backoff retry (3 attempts: 1s, 4s, 16s)
  - Offline buffer (collections.deque, max 12 entries)
  - Tracks last_sync timestamp, status, error_count, discovered sensor count
"""

from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BACKOFF_BASE,
    DEVICE_CLASS_TO_TYPE,
    DOMAIN,
    MAX_RETRIES,
    OFFLINE_BUFFER_MAX,
    SENSOR_TYPES,
    SUPPORTED_DEVICE_CLASSES,
)

_LOGGER = logging.getLogger(__name__)

# Ingest endpoint path (appended to base endpoint)
_INGEST_PATH: str = "/api/v1/sensors/ingest"


class BewustRenoverenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that auto-discovers sensors and pushes data to the cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api_key: str,
        endpoint: str,
        push_interval: int,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            api_key: API key for authentication with the cloud endpoint.
            endpoint: Base URL of the cloud endpoint.
            push_interval: Seconds between data pushes.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=push_interval),
        )
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._session = async_get_clientsession(hass)

        # State tracking
        self.last_sync: datetime | None = None
        self.status: str = "Disconnected"
        self.error_count: int = 0
        self.last_error: str | None = None
        self.discovered_count: int = 0

        # Offline buffer: stores payloads that failed to send
        self._buffer: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=OFFLINE_BUFFER_MAX
        )

    def update_config(
        self,
        *,
        api_key: str,
        endpoint: str,
        push_interval: int,
    ) -> None:
        """Update configuration after options flow changes."""
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self.update_interval = timedelta(seconds=push_interval)

    def _discover_sensors(self) -> list[dict[str, Any]]:
        """Discover all sensor and binary_sensor entities with supported device classes.

        Returns a list of sensor dicts with entity_id, type, value, unit, etc.
        """
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sensors: list[dict[str, Any]] = []

        # Iterate all states in HA
        all_states: list[State] = self.hass.states.async_all()
        for state in all_states:
            entity_id: str = state.entity_id
            domain = entity_id.split(".")[0]

            # Only process sensor and binary_sensor domains
            if domain not in ("sensor", "binary_sensor"):
                continue

            # Check device_class
            device_class: str | None = state.attributes.get("device_class")
            if device_class is None or device_class not in SUPPORTED_DEVICE_CLASSES:
                continue

            # Skip unavailable/unknown states
            if state.state in ("unavailable", "unknown", "None", ""):
                continue

            # Map device_class to our canonical type
            sensor_type = DEVICE_CLASS_TO_TYPE.get(device_class)
            if sensor_type is None:
                continue

            # Get sensor metadata
            sensor_info = SENSOR_TYPES.get(sensor_type)
            if sensor_info is None:
                continue

            # Convert value based on domain
            if domain == "binary_sensor":
                value: Any = state.state == "on"
            else:
                try:
                    value = float(state.state)
                except (ValueError, TypeError):
                    _LOGGER.debug(
                        "Could not parse state '%s' for entity '%s' as number; skipping",
                        state.state,
                        entity_id,
                    )
                    continue

            # Get the unit from HA state attributes, fall back to our mapping
            unit = state.attributes.get(
                "unit_of_measurement", sensor_info["unit"]
            )

            sensors.append(
                {
                    "entity_id": entity_id,
                    "type": sensor_type,
                    "value": value,
                    "unit": unit,
                    "friendly_name": state.attributes.get(
                        "friendly_name", entity_id
                    ),
                    "device_class": device_class,
                    "timestamp": now_iso,
                }
            )

        return sensors

    async def _async_update_data(self) -> dict[str, Any]:
        """Discover sensors and push data to the cloud.

        Returns a dict with status info consumed by diagnostic sensors.
        """
        # Discover all matching sensors
        sensors = self._discover_sensors()
        self.discovered_count = len(sensors)

        if not sensors:
            _LOGGER.debug("No matching sensors discovered; nothing to push")
            return self._build_result()

        _LOGGER.debug(
            "Discovered %d sensor(s) for push", len(sensors)
        )

        # Build single payload with all sensors
        payload: dict[str, Any] = {
            "sensors": sensors,
        }

        # Try to flush any buffered payloads first, then send current
        all_payloads = list(self._buffer) + [payload]
        self._buffer.clear()

        success = True
        for p in all_payloads:
            try:
                await self._push_with_retry(p)
            except PushError as err:
                _LOGGER.error("Failed to push sensor data: %s", err)
                self._buffer.append(p)
                success = False
                self.error_count += 1
                self.last_error = str(err)

        if success:
            self.last_sync = datetime.now(timezone.utc)
            self.status = "Connected"
            self.error_count = 0
            self.last_error = None
            _LOGGER.debug(
                "Successfully pushed %d sensor reading(s)", len(sensors)
            )
        else:
            if self._buffer:
                self.status = "Error"
            _LOGGER.warning(
                "Push failed; %d payload(s) buffered", len(self._buffer)
            )

        return self._build_result()

    async def _push_with_retry(self, payload: dict[str, Any]) -> None:
        """POST payload to the endpoint with exponential backoff retry.

        Raises PushError if all retries are exhausted.
        """
        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                await self._push_to_cloud(payload)
                return  # success
            except aiohttp.ClientResponseError as err:
                if err.status == 401:
                    # Auth error - don't retry, fail immediately
                    self.status = "Error"
                    raise PushError(
                        "Authentication failed (401): check your API key"
                    ) from err
                if err.status == 400:
                    # Bad data - don't retry, fail immediately
                    raise PushError(
                        f"Bad request (400): {err.message}"
                    ) from err
                # 5xx or other - retry
                last_exception = err
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_exception = err

            # Exponential backoff: 1s, 4s, 16s
            if attempt < MAX_RETRIES - 1:
                delay = BACKOFF_BASE * (4**attempt)
                _LOGGER.debug(
                    "Retry %d/%d in %ds",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        raise PushError(
            f"Failed after {MAX_RETRIES} retries: {last_exception}"
        )

    async def _push_to_cloud(self, payload: dict[str, Any]) -> None:
        """POST a single payload to the cloud endpoint."""
        url = f"{self._endpoint}{_INGEST_PATH}"
        timeout = aiohttp.ClientTimeout(total=30)
        async with self._session.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        ) as resp:
            if resp.status not in (200, 201, 202):
                text = await resp.text()
                raise aiohttp.ClientResponseError(
                    request_info=resp.request_info,
                    history=resp.history,
                    status=resp.status,
                    message=text,
                )
            _LOGGER.debug(
                "Push OK (%d): %s", resp.status, await resp.text()
            )

    def _build_result(self) -> dict[str, Any]:
        """Build the result dict exposed to diagnostic sensors."""
        return {
            "status": self.status,
            "last_sync": (
                self.last_sync.isoformat() if self.last_sync else None
            ),
            "error_count": self.error_count,
            "last_error": self.last_error,
            "buffered_count": len(self._buffer),
            "discovered_count": self.discovered_count,
        }


class PushError(Exception):
    """Error raised when a data push fails."""
