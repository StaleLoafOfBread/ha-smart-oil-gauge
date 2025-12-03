"""
Custom integration to integrate Smart Oil Gauge with Home Assistant.

This file handles:
- Initializing the integration
- Creating the API client
- Creating the DataUpdateCoordinator (the heart of the integration)
- Forwarding setup/unload to platforms (sensor, etc.)
- Handling re-authentication and dynamic scan intervals

Almost every Home Assistant integration follows this same pattern.
"""

# Future Annotations allows modern, clean type hints
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core_config import Config
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Our local library code
from .api import ApiError, AuthError, SmartOilClient

# Shared constants
from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)

# Create a logger for this integration
# The logger name becomes "custom_components.smart_oil_gauge"
_LOGGER: logging.Logger = logging.getLogger(__package__)


# --------------------------------------------------------------------------------------
# 1. async_setup
# --------------------------------------------------------------------------------------
async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """
    Called by Home Assistant when setting up components from YAML.

    Our integration *does not support YAML*, only UI config flows,
    so this function does almost nothing except return True.

    Returning True tells Home Assistant:
        "Nothing to do here; please continue startup normally."
    """
    return True


# --------------------------------------------------------------------------------------
# 2. Data Update Coordinator (the heart of the integration)
# --------------------------------------------------------------------------------------
class SmartOilGaugeDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    This class manages:
    - Periodically fetching data from the Smart Oil Gauge API
    - Handling authentication errors
    - Handling API failures
    - Making the latest data available to all platform entities (sensors)

    Home Assistant strongly recommends using DataUpdateCoordinator because:
    - It prevents multiple entities from individually querying the API
    - It schedules refreshes efficiently
    - It centralizes error-handling logic
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartOilClient,
        username: str,
        password: str,
        scan_interval: int,
    ) -> None:
        """
        Create the coordinator.

        Arguments:
        - hass: Home Assistant instance
        - client: our API client used to perform HTTP requests
        - username/password: stored so we can attempt automatic re-authentication
        - scan_interval: user-configurable polling interval in seconds
        """
        self._client = client
        self._username = username
        self._password = password

        # Call superclass constructor
        # update_interval defines how often HA will call _async_update_data()
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,  # name shown in logs
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        This is called by Home Assistant based on update_interval OR when manually refreshed.

        You *must* raise UpdateFailed(...) for recoverable issues,
        and ConfigEntryAuthFailed for authentication failures so that HA
        launches the re-authentication UI automatically.
        """
        try:
            # Attempt normal API fetch
            return await self._client.get_tanks_list()

        except AuthError:
            # This is expected when session tokens expire
            _LOGGER.debug("Authentication error; attempting re-login")

            try:
                # Try re-authenticating using stored credentials
                await self._client.login(self._username, self._password)

                # If login succeeds, retry the original request
                return await self._client.get_tanks_list()

            except AuthError as err:
                # Login attempt failed -> trigger Home Assistant reauth flow
                raise ConfigEntryAuthFailed from err

            except Exception as err:
                # Something else went wrong while trying to reauthenticate
                # This still counts as a recoverable failure
                raise UpdateFailed(f"Re-login failed: {err}") from err

        except ApiError as err:
            # Any API-specific error that is not authentication related
            raise UpdateFailed(str(err)) from err

        except Exception as err:
            # Unexpected error  still recoverable
            raise UpdateFailed(f"Unexpected error: {err}") from err


# --------------------------------------------------------------------------------------
# 3. async_setup_entry
# --------------------------------------------------------------------------------------
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Called when a config entry is created or reloaded.

    Responsibilities:
    - Create the API client
    - Create the DataUpdateCoordinator
    - Fetch initial data
    - Forward setup to each platform (sensor.py, etc.)
    - Register listeners for option changes
    """

    # Create storage bucket for this integration if not already created.
    #
    # Structure:
    #     hass.data[DOMAIN] = {
    #         entry_id_1: coordinator,
    #         entry_id_2: coordinator,
    #     }
    #
    hass.data.setdefault(DOMAIN, {})

    # Extract credentials from the config entry
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]

    # Pull user-configured scan interval from options, or fallback
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    _LOGGER.debug(
        "Setting up Smart Oil Gauge for user %s (scan interval = %d seconds)",
        username,
        scan_interval,
    )

    # Get the shared aiohttp session from HA
    session = async_get_clientsession(hass)

    # Create our API client using the shared session
    client = SmartOilClient(session)

    # Create the coordinator which will manage data fetching
    coordinator = SmartOilGaugeDataUpdateCoordinator(
        hass=hass,
        client=client,
        username=username,
        password=password,
        scan_interval=scan_interval,
    )

    # Perform first refresh before setup completes.
    # This ensures:
    # - Valid credentials
    # - API is reachable
    # - Initial data is available for entities
    #
    # If this fails:
    # - ConfigEntryAuthFailed → triggers reauth UI
    # - ConfigEntryNotReady → HA retries setup automatically later
    #
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise  # Let HA handle reauth
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(str(err)) from err

    # Store coordinator so platforms can access it
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to all platforms listed in PLATFORMS
    # (e.g. sensor.py will receive async_setup_entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register callback to reload entry when options change
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


# --------------------------------------------------------------------------------------
# 4. async_unload_entry
# --------------------------------------------------------------------------------------
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Called when the user removes the integration or disables the entry.

    Responsibilities:
    - Unload all platforms (sensor.py, etc.)
    - Remove coordinator from hass.data
    """

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove the coordinator for this entry
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


# --------------------------------------------------------------------------------------
# 5. async_reload_entry
# --------------------------------------------------------------------------------------
async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Called when integration options change.

    Home Assistant handles reload by:
    - Unloading entry
    - Re-running async_setup_entry
    """
    await hass.config_entries.async_reload(entry.entry_id)
