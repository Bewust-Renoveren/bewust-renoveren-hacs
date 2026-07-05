"""Sensor platform for Bewust Renoveren.

Exposes three diagnostic sensors:
  - BewustRenoverenStatusSensor: "Connected" / "Disconnected" / "Error"
  - BewustRenoverenLastSyncSensor: ISO timestamp of last successful push
  - BewustRenoverenQueuedBatchesSensor: number of batches in the persistent
    offline queue, awaiting drain on the next successful push
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    LAST_SYNC_SENSOR_ID,
    QUEUED_SENSOR_ID,
    STATUS_SENSOR_ID,
)
from .coordinator import BewustRenoverenCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bewust Renoveren sensors from a config entry."""
    coordinator: BewustRenoverenCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        BewustRenoverenStatusSensor(coordinator, entry),
        BewustRenoverenLastSyncSensor(coordinator, entry),
        BewustRenoverenQueuedBatchesSensor(coordinator, entry),
    ]
    async_add_entities(entities)


class BewustRenoverenBaseSensor(
    CoordinatorEntity[BewustRenoverenCoordinator], SensorEntity
):
    """Base class for Bewust Renoveren sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BewustRenoverenCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Bewust Renoveren",
            manufacturer="Bewust Renoveren",
            model="Cloud Gateway",
            entry_type=DeviceEntryType.SERVICE,
        )


class BewustRenoverenStatusSensor(BewustRenoverenBaseSensor):
    """Sensor showing the connection status: Connected / Disconnected / Error."""

    def __init__(
        self,
        coordinator: BewustRenoverenCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key=STATUS_SENSOR_ID,
                name="Status",
                icon="mdi:cloud-check-outline",
                translation_key="status",
            ),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the current status."""
        return self.coordinator.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {
            "error_count": data.get("error_count", 0),
            "queued_batches": data.get("queued_batches", 0),
        }
        if data.get("last_error"):
            attrs["last_error"] = data["last_error"]
        return attrs

    @property
    def icon(self) -> str:
        """Return an icon reflecting current status."""
        status = self.coordinator.status
        if status == "Connected":
            return "mdi:cloud-check-outline"
        if status == "Error":
            return "mdi:cloud-alert"
        return "mdi:cloud-off-outline"


class BewustRenoverenLastSyncSensor(BewustRenoverenBaseSensor):
    """Sensor showing the timestamp of the last successful data push."""

    def __init__(
        self,
        coordinator: BewustRenoverenCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the last sync sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key=LAST_SYNC_SENSOR_ID,
                name="Last Sync",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:clock-check-outline",
                translation_key="last_sync",
            ),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return the datetime of last successful sync.

        HA's SensorDeviceClass.TIMESTAMP requires a datetime object.
        """
        if self.coordinator.last_sync is not None:
            return self.coordinator.last_sync
        return None


class BewustRenoverenQueuedBatchesSensor(BewustRenoverenBaseSensor):
    """Sensor showing the number of batches held in the persistent offline queue."""

    def __init__(
        self,
        coordinator: BewustRenoverenCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the queued batches sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key=QUEUED_SENSOR_ID,
                name="Queued Batches",
                icon="mdi:database-clock-outline",
                translation_key="queued_batches",
                native_unit_of_measurement="batches",
            ),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return the number of batches currently buffered on disk."""
        data = self.coordinator.data or {}
        return data.get("queued_batches", 0)
