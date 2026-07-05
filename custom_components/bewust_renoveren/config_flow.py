"""Config flow for Bewust Renoveren integration.

Step 1 is a menu choosing between two onboarding paths:
  A. "key"      -- enter an existing API key + endpoint (with live validation)
  B. "register" -- self-registration: installer code + customer details,
                   the server mints the API key via /api/v1/provision/register

Both paths converge on the push interval step.

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
    CONF_ADRES,
    CONF_API_KEY,
    CONF_EMAIL,
    CONF_ENDPOINT,
    CONF_INSTALLER_CODE,
    CONF_KLANT_ID,
    CONF_KLANT_NAAM,
    CONF_PUSH_INTERVAL,
    CONF_WONING_ID,
    CONF_WONING_LABEL,
    DEFAULT_ENDPOINT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    INGEST_PATH,
    PROVISION_PATH,
    PUSH_INTERVALS,
)

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """Raised when API key is rejected (HTTP 401)."""


class CannotConnect(Exception):
    """Raised when connection to the endpoint fails."""


class InvalidInstallerCode(Exception):
    """Raised when the installer code is rejected (HTTP 403)."""


class RateLimited(Exception):
    """Raised when registration is throttled (HTTP 429)."""


async def _validate_credentials(hass: Any, api_key: str, endpoint: str) -> None:
    """Test API key against the endpoint.

    Posts a minimal test payload. Any 2xx or 4xx response (except 401) means
    the endpoint is reachable and the API key is accepted.

    Raises:
        InvalidAuth: HTTP 401 received -- API key is wrong.
        CannotConnect: Network/connection error -- endpoint unreachable.
    """
    session = async_get_clientsession(hass)
    url = f"{endpoint.rstrip('/')}{INGEST_PATH}"
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


async def _register_customer(
    hass: Any,
    *,
    endpoint: str,
    installer_code: str,
    klant_naam: str,
    email: str,
    adres: str,
    woning_label: str | None,
) -> dict[str, str]:
    """Self-register a new customer via the installer-code provisioning endpoint.

    Returns the JSON body ({"api_key", "klant_id", "woning_id"}) on success.

    Raises:
        InvalidInstallerCode: HTTP 403 -- installer code rejected.
        RateLimited: HTTP 429 -- too many registration attempts.
        CannotConnect: Network error or unexpected response.
    """
    session = async_get_clientsession(hass)
    url = f"{endpoint.rstrip('/')}{PROVISION_PATH}"
    payload: dict[str, str] = {
        "installer_code": installer_code,
        "klant_naam": klant_naam,
        "email": email,
        "adres": adres,
    }
    if woning_label:
        payload["woning_label"] = woning_label

    try:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 201:
                return await resp.json()
            if resp.status == 403:
                raise InvalidInstallerCode("Invalid installer code")
            if resp.status == 429:
                raise RateLimited("Too many registration attempts")
            text = await resp.text()
            raise CannotConnect(f"Unexpected response ({resp.status}): {text}")
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

    Step 1: menu -- "key" (existing API key) or "register" (self-registration)
    Step 2 (path A): API key + endpoint URL
    Step 2 (path B): installer code + customer details -> registration call
    Step 3 (path B only): registration confirmation
    Step 4: push interval selection, then create entry
    """

    VERSION = 4

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str = ""
        self._endpoint: str = DEFAULT_ENDPOINT
        self._push_interval: int = DEFAULT_PUSH_INTERVAL
        self._klant_id: str = ""
        self._woning_id: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: choose between an existing key or self-registration."""
        # Prevent adding the integration twice
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_show_menu(
            step_id="user",
            menu_options=["key", "register"],
        )

    async def async_step_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Path A: API key and endpoint URL."""
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
            step_id="key",
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

    async def async_step_register(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Path B: installer code + customer details -> self-registration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            installer_code = user_input[CONF_INSTALLER_CODE].strip()
            klant_naam = user_input[CONF_KLANT_NAAM].strip()
            email = user_input[CONF_EMAIL].strip()
            adres = user_input[CONF_ADRES].strip()
            woning_label = user_input.get(CONF_WONING_LABEL, "").strip()

            if not installer_code:
                errors[CONF_INSTALLER_CODE] = "installer_code_required"
            elif not klant_naam:
                errors[CONF_KLANT_NAAM] = "klant_naam_required"
            elif not email:
                errors[CONF_EMAIL] = "email_required"
            elif not adres:
                errors[CONF_ADRES] = "adres_required"
            else:
                try:
                    result = await _register_customer(
                        self.hass,
                        endpoint=DEFAULT_ENDPOINT,
                        installer_code=installer_code,
                        klant_naam=klant_naam,
                        email=email,
                        adres=adres,
                        woning_label=woning_label or None,
                    )
                except InvalidInstallerCode:
                    errors["base"] = "invalid_installer_code"
                except RateLimited:
                    errors["base"] = "rate_limited"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    self._api_key = result["api_key"]
                    self._endpoint = DEFAULT_ENDPOINT
                    self._klant_id = result.get("klant_id", "")
                    self._woning_id = result.get("woning_id", "")
                    return await self.async_step_register_confirm()

        return self.async_show_form(
            step_id="register",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INSTALLER_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_KLANT_NAAM): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_EMAIL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    ),
                    vol.Required(CONF_ADRES): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_WONING_LABEL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_register_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the newly provisioned klant_id/woning_id, then continue."""
        if user_input is not None:
            return await self.async_step_interval()

        return self.async_show_form(
            step_id="register_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "klant_id": self._klant_id,
                "woning_id": self._woning_id,
            },
        )

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Final step: select push interval, then create entry."""
        if user_input is not None:
            self._push_interval = int(user_input[CONF_PUSH_INTERVAL])
            return self._create_entry()

        return self.async_show_form(
            step_id="interval",
            data_schema=_interval_schema(),
        )

    def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry."""
        data: dict[str, Any] = {
            CONF_API_KEY: self._api_key,
            CONF_ENDPOINT: self._endpoint,
            CONF_PUSH_INTERVAL: self._push_interval,
        }
        if self._klant_id:
            data[CONF_KLANT_ID] = self._klant_id
        if self._woning_id:
            data[CONF_WONING_ID] = self._woning_id
        return self.async_create_entry(
            title="Bewust Renoveren (auto-discovery)",
            data=data,
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
            **self.config_entry.data,
            CONF_API_KEY: self._api_key,
            CONF_ENDPOINT: self._endpoint,
            CONF_PUSH_INTERVAL: self._push_interval,
        }
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
        )
        return self.async_create_entry(title="", data={})
