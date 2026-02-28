"""Bewust Renoveren -- Home Assistant custom component.

Monitors indoor air quality and moisture levels, pushing sensor data
to the Bewust Renoveren cloud platform for analysis and early warnings.
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
    CONF_ROOMS,
    DEFAULT_ENDPOINT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
)
from .coordinator import BewustRenoverenCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bewust Renoveren from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = BewustRenoverenCoordinator(
        hass,
        api_key=entry.data[CONF_API_KEY],
        endpoint=entry.data.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
        push_interval=entry.data.get(CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL),
        rooms=entry.data.get(CONF_ROOMS, []),
    )

    # Do an initial data push
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Bewust Renoveren integration set up with %d room(s)",
        len(entry.data.get(CONF_ROOMS, [])),
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
        rooms=entry.data.get(CONF_ROOMS, []),
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
