"""Config flow for the Smart Oil Gauge integration.

This file handles:
- The initial config flow (username, password, scan interval)
- Live validation of credentials against the Smart Oil Gauge website
- The options flow for changing scan interval later

It is the only part of the integration that the user interacts with directly
via the Home Assistant UI.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import AuthError, ApiError, SmartOilClient
from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SmartOilGaugeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for Smart Oil Gauge."""

    VERSION = 1
    # This tells HA that we poll a cloud API periodically
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the first step initiated by the user.

        This step:
        - Shows a form asking for username, password, and scan interval.
        - Validates the credentials by actually logging in and fetching data.
        - Creates a config entry on success, or re-shows the form with errors.
        """
        self._errors = {}

        # If the user submitted the form, validate the input
        if user_input is not None:
            error = await self._async_validate_input(user_input)

            if error is None:
                # Use username as a unique identifier so the same account
                # can't be added twice by accident.
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()

                # Title is what shows in the UI under "Integrations"
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        # Store scan interval in data initially; options flow can override
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )

            # If we got an error, attach it to the base of the form
            self._errors["base"] = error

        # First time through, or error case: show the form again
        return self._show_user_form(user_input)

    def _show_user_form(self, user_input: dict[str, Any] | None) -> FlowResult:
        """Render the configuration form for the user step."""
        # Provide defaults if user_input is None or missing keys
        username_default = ""
        scan_interval_default = DEFAULT_SCAN_INTERVAL

        if user_input is not None:
            username_default = user_input.get(CONF_USERNAME, "")
            # Don't prefill password; HA usually leaves that blank on error
            scan_interval_default = user_input.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=username_default): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=scan_interval_default): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=self._errors,
        )

    async def _async_validate_input(self, user_input: dict[str, Any]) -> str | None:
        """Validate the user input by talking to the Smart Oil Gauge API.

        Returns:
            None if validation passed.
            A Home Assistant error code string if validation failed, e.g.:
                - "auth"           → invalid username/password
                - "cannot_connect" → network / HTTP issues
                - "unknown"        → unexpected exception

        These error codes correspond to keys in translations, if you add them.
        """
        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]

        # Create a temporary HTTP session just for this flow; HA manages it.
        session = async_create_clientsession(self.hass)
        client = SmartOilClient(session)

        try:
            # First, try to log in
            await client.login(username, password)

            # Optionally, also fetch the tank list to ensure the login
            # actually resulted in a valid, working session.
            await client.get_tanks_list()

            _LOGGER.debug(
                "SmartOilGauge config flow: successfully validated credentials for user=%s",
                username,
            )
            return None

        except AuthError:
            # Credentials are bad, or session is not authorized.
            _LOGGER.warning(
                "SmartOilGauge config flow: authentication failed for user=%s",
                username,
            )
            return "auth"

        except ApiError as err:
            # Network / API-related issue (timeouts, bad responses, etc.).
            _LOGGER.warning(
                "SmartOilGauge config flow: API error while validating credentials: %s",
                err,
            )
            return "cannot_connect"

        except Exception:  # noqa: BLE001
            # Unexpected error; log full traceback for debugging.
            _LOGGER.exception(
                "SmartOilGauge config flow: unexpected exception during validation"
            )
            return "unknown"

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for this config entry."""
        return SmartOilGaugeOptionsFlow(config_entry)


class SmartOilGaugeOptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for Smart Oil Gauge.

    Currently supports:
    - Updating the scan interval after the integration is already set up.
    """

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step of the options flow.

        Home Assistant will always start here for options, and we delegate
        to the user step to actually render the form.
        """
        if user_input is not None:
            # User submitted options form; save the new options.
            return self.async_create_entry(title="", data=user_input)

        # Build the options form, pre-populating scan interval.
        current_scan_interval = self.entry.options.get(
            CONF_SCAN_INTERVAL,
            self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current_scan_interval,
                ): int
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
