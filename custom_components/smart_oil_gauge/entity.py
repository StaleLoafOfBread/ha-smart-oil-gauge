"""
Shared base entities and helpers for the Smart Oil Gauge integration.

This module centralizes:
- Common helper functions (e.g. _safe_float, _tanks_from)
- Shared base entity classes for tank-based entities

Both sensor.py and binary_sensor.py import from here to avoid duplication.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------
def _safe_float(x: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _tanks_from(data: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    """Extract the 'tanks' list from the coordinator data.

    Expected shape:
        {
            "tanks": [
                { "tank_id": 123, "tank_name": "...", ... },
                ...
            ]
        }

    Returns [] if the data is missing or malformed.
    """
    if data is None:
        _LOGGER.debug("Smart Oil Gauge: coordinator.data is None")
        return []

    if not isinstance(data, dict):
        _LOGGER.debug(
            "Smart Oil Gauge: coordinator.data is not a dict (type=%s)", type(data)
        )
        return []

    tanks = data.get("tanks")
    if isinstance(tanks, list):
        return tanks

    _LOGGER.debug("Smart Oil Gauge: 'tanks' key missing or invalid in data")
    return []


# -----------------------------------------------------------------------------
# Base entity classes
# -----------------------------------------------------------------------------
class SmartOilBaseEntity(CoordinatorEntity):
    """Base class for all Smart Oil Gauge entities.

    Holds a reference to the ConfigEntry so we can use it in unique_ids,
    device_info, etc.
    """

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def entry(self) -> ConfigEntry:
        """Return the config entry for this entity."""
        return self._entry


class SmartOilTankEntity(SmartOilBaseEntity):
    """Base class for entities that are associated with a specific tank.

    This class:
    - Stores the tank_id
    - Provides a _tank() helper to pull the current tank dict
    - Provides device_info so all tank entities are grouped together
      under a single "tank" device, which itself is under the
      account-level device via via_device.
    """

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry)
        self._tank_id = tank_id

    def _tank(self) -> Dict[str, Any] | None:
        """Return the tank dict for this entity's tank_id, or None if missing."""
        for t in _tanks_from(self.coordinator.data):
            if str(t.get("tank_id")) == self._tank_id:
                return t
        return None

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information for this tank."""
        t = self._tank() or {}
        name = t.get("tank_name") or f"Tank {self._tank_id}"

        return {
            "identifiers": {(DOMAIN, f"tank_{self._tank_id}")},
            "via_device": (DOMAIN, self._entry.entry_id),
            "name": name,
            "manufacturer": "Connected Consumer Fuel",
            "model": "SmartOilGauge",
            "configuration_url": "https://app.smartoilgauge.com/",
        }
