"""
Diagnostics support for the Smart Oil Gauge integration.

This allows users to download sanitized diagnostic information from the UI:
Settings -> Devices & Services -> Smart Oil Gauge -> ⋮ -> Download diagnostics

Diagnostics files help with debugging but MUST NOT contain sensitive data.
"""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Fields that must always be removed from any diagnostic output.
# These should include:
# - Authentication tokens
# - Session cookies
# - Passwords
# - Usernames
TO_REDACT = {
    "PHPSESSID",
    "ccf_tok",
    "username",
    "password",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    """Return diagnostics for a config entry.

    This includes:
    - The last known API state in coordinator.data
    - Sensitive fields properly redacted
    """

    # In our integration, hass.data[DOMAIN][entry_id] stores the coordinator directly.
    coordinator = hass.data[DOMAIN].get(entry.entry_id)

    if coordinator is None:
        return {"error": "Coordinator not found"}

    raw_data = coordinator.data or {}

    # async_redact_data deeply removes keys in TO_REDACT from nested structures.
    return async_redact_data(raw_data, TO_REDACT)
