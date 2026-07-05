"""Bewust Renoveren -- Home Assistant custom component.

Monitors indoor air quality and moisture levels, pushing sensor data
to the Bewust Renoveren cloud platform for analysis and early warnings.

Auto-discovers sensors by device_class -- no manual room mapping required.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    CONF_ENDPOINT,
    CONF_PUSH_INTERVAL,
    DEFAULT_ENDPOINT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
)
from .coordinator import BewustRenoverenCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Historical default endpoint (Firebase Hosting), superseded by the DGX
# tunnel endpoint in DEFAULT_ENDPOINT. Kept here only so the v3 -> v4
# migration can recognize and replace it.
_LEGACY_FIREBASE_ENDPOINT = "https://bewust-renoveren.web.app"


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to current version.

    Version 1 -> 3: Remove 'rooms' key, update old Cloud Run endpoint to
      the (then current) Firebase hosting URL.
    Version 3 -> 4: Update the Firebase hosting endpoint to the DGX tunnel
      endpoint (`app.bewustrenoveren.app`); the ingest path itself is
      appended at request time and does not need migrating.
    """
    new_data = dict(config_entry.data)
    version = config_entry.version

    if version < 3:
        _LOGGER.info(
            "Migrating Bewust Renoveren config entry from version %d to 3",
            version,
        )
        # v1: strip rooms
        if version == 1:
            new_data = {k: v for k, v in new_data.items() if k != "rooms"}

        # v1+v2: update old Cloud Run endpoint to the Firebase hosting URL
        old_endpoint = new_data.get(CONF_ENDPOINT, "")
        if "ingest-" in old_endpoint and ".a.run.app" in old_endpoint:
            new_data[CONF_ENDPOINT] = _LEGACY_FIREBASE_ENDPOINT
            _LOGGER.info(
                "Migrated endpoint from %s to %s",
                old_endpoint,
                _LEGACY_FIREBASE_ENDPOINT,
            )
        version = 3

    if version < 4:
        _LOGGER.info(
            "Migrating Bewust Renoveren config entry from version %d to 4",
            version,
        )
        # v3: update Firebase hosting endpoint to the DGX tunnel endpoint
        old_endpoint = new_data.get(CONF_ENDPOINT, "")
        if old_endpoint in ("", _LEGACY_FIREBASE_ENDPOINT):
            new_data[CONF_ENDPOINT] = DEFAULT_ENDPOINT
            _LOGGER.info(
                "Migrated endpoint from %s to %s", old_endpoint, DEFAULT_ENDPOINT
            )
        version = 4

    hass.config_entries.async_update_entry(
        config_entry, data=new_data, version=version
    )
    _LOGGER.info("Bewust Renoveren config entry migration complete (version %d)", version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bewust Renoveren from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = BewustRenoverenCoordinator(
        hass,
        entry_id=entry.entry_id,
        api_key=entry.data[CONF_API_KEY],
        endpoint=entry.data.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
        push_interval=entry.data.get(CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL),
    )

    # Do an initial data push
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Bewust Renoveren integration set up (auto-discovery mode, "
        "discovered %d sensor(s))",
        coordinator.discovered_count,
    )
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update -- reconfigure the coordinator."""
    coordinator: BewustRenoverenCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_config(
        api_key=entry.data[CONF_API_KEY],
        endpoint=entry.data.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
        push_interval=entry.data.get(CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL),
    )
    await coordinator.async_request_refresh()
    _LOGGER.info("Bewust Renoveren configuration updated")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Bewust Renoveren config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info("Bewust Renoveren integration unloaded")
    return unload_ok
