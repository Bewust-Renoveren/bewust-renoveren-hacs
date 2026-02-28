"""Data update coordinator for Bewust Renoveren.

Periodically reads sensor states from mapped HA entities, builds payloads
per room, and POSTs them to the Bewust Renoveren cloud endpoint.

Features:
  - Exponential backoff retry (3 attempts: 1s, 4s, 16s)
  - Offline buffer (collections.deque, max 12 entries)
  - Tracks last_sync timestamp, status, error_count
"""

from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.slugify import slugify

from .const import (
    BACKOFF_BASE,
    CONF_API_KEY,
    CONF_ENDPOINT,
    CONF_PUSH_INTERVAL,
    CONF_ROOMS,
    CONF_ROOM_ENTITIES,
    CONF_ROOM_NAME,
    DOMAIN,
    MAX_RETRIES,
    OFFLINE_BUFFER_MAX,
    SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class BewustRenoverenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that pushes sensor data to the cloud backend."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api_key: str,
        endpoint: str,
        push_interval: int,
        rooms: list[dict[str, Any]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=push_interval),
        )
        self._api_key = api_key
        self._endpoint = endpoint
        self._rooms = rooms
        self._session = async_get_clientsession(hass)

        # State tracking
        self.last_sync: datetime | None = None
        self.status: str = "Disconnected"
        self.error_count: int = 0
        self.last_error: str | None = None

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
        rooms: list[dict[str, Any]],
    ) -> None:
        """Update configuration after options flow changes."""
        self._api_key = api_key
        self._endpoint = endpoint
        self._rooms = rooms
        self.update_interval = timedelta(seconds=push_interval)

    async def _async_update_data(self) -> dict[str, Any]:
        """Read mapped entities and push data to the cloud.

        Returns a dict with status info consumed by sensors.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build payloads for each room
        payloads: list[dict[str, Any]] = []
        for room in self._rooms:
            room_name = room[CONF_ROOM_NAME]
            entities = room[CONF_ROOM_ENTITIES]
            readings: list[dict[str, Any]] = []

            for sensor_type, entity_id in entities.items():
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                if state.state in ("unavailable", "unknown"):
                    continue

                sensor_info = SENSOR_TYPES.get(sensor_type)
                if sensor_info is None:
                    continue

                # Convert value based on domain
                if sensor_info["domain"] == "binary_sensor":
                    # binary_sensor: on/off -> True/False
                    value: Any = state.state == "on"
                else:
                    try:
                        value = float(state.state)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "Could not parse state '%s' for entity '%s' as number",
                            state.state,
                            entity_id,
                        )
                        continue

                readings.append(
                    {
                        "type": sensor_type,
                        "value": value,
                        "unit": sensor_info["unit"],
                        "timestamp": timestamp,
                    }
                )

            if readings:
                payloads.append(
                    {
                        "device_id": f"ha_{slugify(room_name)}",
                        "readings": readings,
                    }
                )

        if not payloads:
            _LOGGER.debug("No sensor data available to push")
            return self._build_result()

        # Try to flush any buffered payloads first, then send current
        all_payloads = list(self._buffer) + payloads
        self._buffer.clear()

        success = True
        for payload in all_payloads:
            try:
                await self._push_with_retry(payload)
            except PushError as err:
                # Push failed after retries; buffer for later
                _LOGGER.error(
                    "Failed to push data for %s: %s",
                    payload.get("device_id"),
                    err,
                )
                self._buffer.append(payload)
                success = False
                self.error_count += 1
                self.last_error = str(err)

        if success:
            self.last_sync = now
            self.status = "Connected"
            self.error_count = 0
            self.last_error = None
            _LOGGER.debug(
                "Successfully pushed data for %d room(s)", len(payloads)
            )
        else:
            if self._buffer:
                self.status = "Error"
            _LOGGER.warning(
                "Push partially failed; %d payloads buffered",
                len(self._buffer),
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
                        f"Authentication failed (401): check your API key"
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
                    "Retry %d/%d for %s in %ds",
                    attempt + 1,
                    MAX_RETRIES,
                    payload.get("device_id"),
                    delay,
                )
                await asyncio.sleep(delay)

        raise PushError(
            f"Failed after {MAX_RETRIES} retries: {last_exception}"
        )

    async def _push_to_cloud(self, payload: dict[str, Any]) -> None:
        """POST a single payload to the cloud endpoint."""
        timeout = aiohttp.ClientTimeout(total=30)
        async with self._session.post(
            self._endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise aiohttp.ClientResponseError(
                    request_info=resp.request_info,
                    history=resp.history,
                    status=resp.status,
                    message=text,
                )
            _LOGGER.debug(
                "Push OK for %s: %s",
                payload.get("device_id"),
                await resp.text(),
            )

    def _build_result(self) -> dict[str, Any]:
        """Build the result dict exposed to sensors."""
        return {
            "status": self.status,
            "last_sync": (
                self.last_sync.isoformat() if self.last_sync else None
            ),
            "error_count": self.error_count,
            "last_error": self.last_error,
            "buffered_count": len(self._buffer),
        }


class PushError(Exception):
    """Error raised when a data push fails."""
