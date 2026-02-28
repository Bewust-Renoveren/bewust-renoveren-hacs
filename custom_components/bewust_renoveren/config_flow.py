"""Config flow for Bewust Renoveren integration.

Multi-step setup wizard:
  1. API key + endpoint URL
  2. Add rooms (menu-driven, one at a time)
  3. Per room: name + entity selectors (CO2/temp/humidity required, rest optional)
  4. Push interval selection
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util.slugify import slugify

from .const import (
    CONF_API_KEY,
    CONF_ENDPOINT,
    CONF_PUSH_INTERVAL,
    CONF_ROOMS,
    CONF_ROOM_ENTITIES,
    CONF_ROOM_NAME,
    DEFAULT_ENDPOINT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    OPTIONAL_SENSOR_TYPES,
    PUSH_INTERVALS,
    REQUIRED_SENSOR_TYPES,
    SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


def _entity_selector(sensor_type: str) -> EntitySelector:
    """Build an entity selector filtered by device_class for a sensor type."""
    info = SENSOR_TYPES[sensor_type]
    return EntitySelector(
        EntitySelectorConfig(
            domain=info["domain"],
            device_class=info["device_class"],
            multiple=False,
        )
    )


def _room_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the schema for configuring one room's sensors."""
    defaults = defaults or {}

    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_ROOM_NAME,
            default=defaults.get(CONF_ROOM_NAME, ""),
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
    }

    # Required sensors
    for stype in REQUIRED_SENSOR_TYPES:
        info = SENSOR_TYPES[stype]
        schema[
            vol.Required(stype, default=defaults.get(stype, vol.UNDEFINED))
        ] = _entity_selector(stype)

    # Optional sensors
    for stype in OPTIONAL_SENSOR_TYPES:
        info = SENSOR_TYPES[stype]
        schema[
            vol.Optional(stype, default=defaults.get(stype, vol.UNDEFINED))
        ] = _entity_selector(stype)

    return vol.Schema(schema)


def _interval_schema(default: int = DEFAULT_PUSH_INTERVAL) -> vol.Schema:
    """Build the push interval selection schema."""
    return vol.Schema(
        {
            vol.Required(CONF_PUSH_INTERVAL, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=str(item["value"]),
                            label=str(item["label"]),
                        )
                        for item in PUSH_INTERVALS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class BewustRenoverenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bewust Renoveren."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str = ""
        self._endpoint: str = DEFAULT_ENDPOINT
        self._rooms: list[dict[str, Any]] = []
        self._push_interval: int = DEFAULT_PUSH_INTERVAL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: API key and endpoint URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            endpoint = user_input[CONF_ENDPOINT].strip()

            if not api_key:
                errors[CONF_API_KEY] = "api_key_required"
            elif not endpoint.startswith("https://"):
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            else:
                self._api_key = api_key
                self._endpoint = endpoint
                return await self.async_step_room_menu()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_ENDPOINT, default=DEFAULT_ENDPOINT
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_room_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Menu: add another room or finish."""
        if user_input is not None:
            action = user_input.get("next_step")
            if action == "add_room":
                return await self.async_step_add_room()
            if action == "finish":
                return await self.async_step_interval()

        # Build description based on current rooms
        room_count = len(self._rooms)
        room_names = ", ".join(r[CONF_ROOM_NAME] for r in self._rooms) if self._rooms else ""

        options = [
            SelectOptionDict(value="add_room", label="Add a room"),
        ]
        if room_count > 0:
            options.append(
                SelectOptionDict(value="finish", label="Done adding rooms"),
            )

        return self.async_show_form(
            step_id="room_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("next_step", default="add_room"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "room_count": str(room_count),
                "room_names": room_names or "-",
            },
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a single room with entity mappings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()

            if not room_name:
                errors[CONF_ROOM_NAME] = "room_name_required"
            else:
                # Check for duplicate room names
                existing_slugs = [slugify(r[CONF_ROOM_NAME]) for r in self._rooms]
                if slugify(room_name) in existing_slugs:
                    errors[CONF_ROOM_NAME] = "room_name_duplicate"

            # Check required sensors are provided
            for stype in REQUIRED_SENSOR_TYPES:
                if not user_input.get(stype):
                    errors[stype] = "sensor_required"

            if not errors:
                # Check for duplicate entity assignments across all rooms
                all_entities: set[str] = set()
                for room in self._rooms:
                    for eid in room[CONF_ROOM_ENTITIES].values():
                        all_entities.add(eid)

                new_entities: dict[str, str] = {}
                for stype in REQUIRED_SENSOR_TYPES + OPTIONAL_SENSOR_TYPES:
                    entity_id = user_input.get(stype)
                    if entity_id:
                        if entity_id in all_entities:
                            errors[stype] = "entity_already_mapped"
                        else:
                            new_entities[stype] = entity_id
                            all_entities.add(entity_id)

            if not errors:
                self._rooms.append(
                    {
                        CONF_ROOM_NAME: room_name,
                        CONF_ROOM_ENTITIES: new_entities,
                    }
                )
                return await self.async_step_room_menu()

        return self.async_show_form(
            step_id="add_room",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step: Select push interval, then create entry."""
        if user_input is not None:
            self._push_interval = int(user_input[CONF_PUSH_INTERVAL])
            return self._create_entry()

        return self.async_show_form(
            step_id="interval",
            data_schema=_interval_schema(),
        )

    def _create_entry(self) -> FlowResult:
        """Create the config entry."""
        title = f"Bewust Renoveren ({len(self._rooms)} rooms)"
        return self.async_create_entry(
            title=title,
            data={
                CONF_API_KEY: self._api_key,
                CONF_ENDPOINT: self._endpoint,
                CONF_PUSH_INTERVAL: self._push_interval,
                CONF_ROOMS: self._rooms,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BewustRenoverenOptionsFlow:
        """Get the options flow handler."""
        return BewustRenoverenOptionsFlow(config_entry)


class BewustRenoverenOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options flow for reconfiguration.

    Allows changing API key, endpoint, rooms, and push interval.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)
        self._api_key: str = config_entry.data.get(CONF_API_KEY, "")
        self._endpoint: str = config_entry.data.get(CONF_ENDPOINT, DEFAULT_ENDPOINT)
        self._rooms: list[dict[str, Any]] = list(
            config_entry.data.get(CONF_ROOMS, [])
        )
        self._push_interval: int = config_entry.data.get(
            CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Main options menu."""
        if user_input is not None:
            action = user_input.get("next_step")
            if action == "credentials":
                return await self.async_step_credentials()
            if action == "rooms":
                return await self.async_step_options_room_menu()
            if action == "interval":
                return await self.async_step_options_interval()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("next_step"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value="credentials",
                                    label="Change API key / endpoint",
                                ),
                                SelectOptionDict(
                                    value="rooms",
                                    label="Manage rooms",
                                ),
                                SelectOptionDict(
                                    value="interval",
                                    label="Change push interval",
                                ),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change API key and endpoint."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            endpoint = user_input[CONF_ENDPOINT].strip()

            if not api_key:
                errors[CONF_API_KEY] = "api_key_required"
            elif not endpoint.startswith("https://"):
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            else:
                self._api_key = api_key
                self._endpoint = endpoint
                return self._save_options()

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_KEY, default=self._api_key
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_ENDPOINT, default=self._endpoint
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_options_room_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Room management menu in options flow."""
        if user_input is not None:
            action = user_input.get("next_step")
            if action == "add_room":
                return await self.async_step_options_add_room()
            if action == "remove_room":
                return await self.async_step_remove_room()
            if action == "done":
                return self._save_options()

        room_count = len(self._rooms)
        room_names = ", ".join(r[CONF_ROOM_NAME] for r in self._rooms) if self._rooms else "-"

        options = [
            SelectOptionDict(value="add_room", label="Add a room"),
        ]
        if room_count > 0:
            options.append(
                SelectOptionDict(value="remove_room", label="Remove a room"),
            )
        options.append(
            SelectOptionDict(value="done", label="Done"),
        )

        return self.async_show_form(
            step_id="options_room_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("next_step", default="add_room"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "room_count": str(room_count),
                "room_names": room_names,
            },
        )

    async def async_step_options_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a room in options flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()

            if not room_name:
                errors[CONF_ROOM_NAME] = "room_name_required"
            else:
                existing_slugs = [slugify(r[CONF_ROOM_NAME]) for r in self._rooms]
                if slugify(room_name) in existing_slugs:
                    errors[CONF_ROOM_NAME] = "room_name_duplicate"

            for stype in REQUIRED_SENSOR_TYPES:
                if not user_input.get(stype):
                    errors[stype] = "sensor_required"

            if not errors:
                all_entities: set[str] = set()
                for room in self._rooms:
                    for eid in room[CONF_ROOM_ENTITIES].values():
                        all_entities.add(eid)

                new_entities: dict[str, str] = {}
                for stype in REQUIRED_SENSOR_TYPES + OPTIONAL_SENSOR_TYPES:
                    entity_id = user_input.get(stype)
                    if entity_id:
                        if entity_id in all_entities:
                            errors[stype] = "entity_already_mapped"
                        else:
                            new_entities[stype] = entity_id
                            all_entities.add(entity_id)

            if not errors:
                self._rooms.append(
                    {
                        CONF_ROOM_NAME: room_name,
                        CONF_ROOM_ENTITIES: new_entities,
                    }
                )
                return await self.async_step_options_room_menu()

        return self.async_show_form(
            step_id="options_add_room",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove a room."""
        if user_input is not None:
            room_slug = user_input.get("room_to_remove")
            self._rooms = [
                r for r in self._rooms if slugify(r[CONF_ROOM_NAME]) != room_slug
            ]
            return await self.async_step_options_room_menu()

        if not self._rooms:
            return await self.async_step_options_room_menu()

        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {
                    vol.Required("room_to_remove"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=slugify(r[CONF_ROOM_NAME]),
                                    label=r[CONF_ROOM_NAME],
                                )
                                for r in self._rooms
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_options_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change push interval in options flow."""
        if user_input is not None:
            self._push_interval = int(user_input[CONF_PUSH_INTERVAL])
            return self._save_options()

        return self.async_show_form(
            step_id="options_interval",
            data_schema=_interval_schema(default=self._push_interval),
        )

    def _save_options(self) -> FlowResult:
        """Save all options and update the config entry."""
        new_data = {
            CONF_API_KEY: self._api_key,
            CONF_ENDPOINT: self._endpoint,
            CONF_PUSH_INTERVAL: self._push_interval,
            CONF_ROOMS: self._rooms,
        }
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
        )
        return self.async_create_entry(title="", data={})
