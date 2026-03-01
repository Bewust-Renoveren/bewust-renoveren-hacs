"""Config flow for Bewust Renoveren integration.

Two-step setup wizard:
  1. API key + endpoint URL (with live validation)
  2. Push interval selection

Sensors are auto-discovered -- no manual room mapping required.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_API_KEY,
    CONF_ENDPOINT,
    CONF_PUSH_INTERVAL,
    DEFAULT_ENDPOINT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    PUSH_INTERVALS,
)

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """Raised when API key is rejected (HTTP 401)."""


class CannotConnect(Exception):
    """Raised when connection to the endpoint fails."""


async def _validate_credentials(hass: Any, api_key: str, endpoint: str) -> None:
    """Test API key against the endpoint.

    Posts a minimal test payload. Any 2xx or 4xx response (except 401) means
    the endpoint is reachable and the API key is accepted.

    Raises:
        InvalidAuth: HTTP 401 received -- API key is wrong.
        CannotConnect: Network/connection error -- endpoint unreachable.
    """
    session = async_get_clientsession(hass)
    url = f"{endpoint.rstrip('/')}/api/v1/sensors/ingest"
    try:
        async with session.post(
            url,
            json={"sensors": []},
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                raise InvalidAuth("Invalid API key")
            # Any other status (200, 400, 422, etc.) means reachable + key accepted
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect(str(err)) from err


def _interval_schema(default: int = DEFAULT_PUSH_INTERVAL) -> vol.Schema:
    """Build the push interval selection schema."""
    return vol.Schema(
        {
            vol.Required(CONF_PUSH_INTERVAL, default=str(default)): SelectSelector(
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
    """Handle a config flow for Bewust Renoveren.

    Two steps:
      1. API key + endpoint URL
      2. Push interval selection
    """

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str = ""
        self._endpoint: str = DEFAULT_ENDPOINT
        self._push_interval: int = DEFAULT_PUSH_INTERVAL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: API key and endpoint URL."""
        # Prevent adding the integration twice
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            endpoint = user_input[CONF_ENDPOINT].strip()

            if not api_key:
                errors[CONF_API_KEY] = "api_key_required"
            elif not endpoint.startswith("https://"):
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            else:
                # Validate the API key against the live endpoint
                try:
                    await _validate_credentials(self.hass, api_key, endpoint)
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    self._api_key = api_key
                    self._endpoint = endpoint
                    return await self.async_step_interval()

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

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Select push interval, then create entry."""
        if user_input is not None:
            self._push_interval = int(user_input[CONF_PUSH_INTERVAL])
            return self._create_entry()

        return self.async_show_form(
            step_id="interval",
            data_schema=_interval_schema(),
        )

    def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title="Bewust Renoveren (auto-discovery)",
            data={
                CONF_API_KEY: self._api_key,
                CONF_ENDPOINT: self._endpoint,
                CONF_PUSH_INTERVAL: self._push_interval,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BewustRenoverenOptionsFlow:
        """Get the options flow handler."""
        return BewustRenoverenOptionsFlow()


class BewustRenoverenOptionsFlow(OptionsFlow):
    """Handle options flow for reconfiguration.

    Allows changing API key, endpoint, and push interval.
    No room management -- sensors are auto-discovered.
    """

    _api_key: str
    _endpoint: str
    _push_interval: int

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Main options menu: choose credentials or interval."""
        if not hasattr(self, "_initialized"):
            self._api_key = self.config_entry.data.get(CONF_API_KEY, "")
            self._endpoint = self.config_entry.data.get(
                CONF_ENDPOINT, DEFAULT_ENDPOINT
            )
            self._push_interval = self.config_entry.data.get(
                CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL
            )
            self._initialized = True

        if user_input is not None:
            action = user_input.get("next_step")
            if action == "credentials":
                return await self.async_step_credentials()
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
    ) -> ConfigFlowResult:
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
                try:
                    await _validate_credentials(self.hass, api_key, endpoint)
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
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

    async def async_step_options_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change push interval in options flow."""
        if user_input is not None:
            self._push_interval = int(user_input[CONF_PUSH_INTERVAL])
            return self._save_options()

        return self.async_show_form(
            step_id="options_interval",
            data_schema=_interval_schema(default=self._push_interval),
        )

    def _save_options(self) -> ConfigFlowResult:
        """Save all options and update the config entry."""
        new_data = {
            CONF_API_KEY: self._api_key,
            CONF_ENDPOINT: self._endpoint,
            CONF_PUSH_INTERVAL: self._push_interval,
        }
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
        )
        return self.async_create_entry(title="", data={})
