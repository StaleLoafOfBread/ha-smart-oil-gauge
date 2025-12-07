"""Binary sensor platform for Smart Oil Gauge.

Defines binary_sensor entities for the integration:

- One LowOilSensor per tank:
    - ON when the current gallons are at or below the configured low-level threshold.
"""
from __future__ import annotations

import logging
from typing import Any
from typing import Iterable
from typing import List

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import _safe_float
from .entity import _tanks_from
from .entity import SmartOilTankEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Oil Gauge binary_sensor entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    created_tank_ids: set[str] = set()

    def build_entities_for_tank(tank: dict[str, Any]) -> Iterable[Entity]:
        tank_id = str(tank.get("tank_id", "unknown"))
        return (LowOilSensor(coordinator, entry, tank_id),)

    entities: List[Entity] = []

    tanks = _tanks_from(coordinator.data)

    # Optional debug log of a sample tank
    try:
        if tanks:
            first = tanks[0]
            _LOGGER.debug(
                "Smart Oil Gauge (binary): first tank sample id=%s name=%s keys=%s",
                first.get("tank_id"),
                first.get("tank_name"),
                list(first.keys()),
            )
        else:
            _LOGGER.debug(
                "Smart Oil Gauge (binary): no tanks found in coordinator.data"
            )
    except Exception:
        _LOGGER.exception(
            "Smart Oil Gauge (binary): error while logging first tank sample"
        )

    for tank in tanks:
        tank_id = str(tank.get("tank_id", "unknown"))
        if tank_id not in created_tank_ids:
            created_tank_ids.add(tank_id)
            entities.extend(build_entities_for_tank(tank))

    if entities:
        async_add_entities(entities)

    @callback
    def _coordinator_updated() -> None:
        new_entities: List[Entity] = []

        for tank in _tanks_from(coordinator.data):
            tank_id = str(tank.get("tank_id", "unknown"))
            if tank_id not in created_tank_ids:
                created_tank_ids.add(tank_id)
                new_entities.extend(build_entities_for_tank(tank))

        if new_entities:
            _LOGGER.debug(
                "Smart Oil Gauge (binary): discovered %d new tank(s); adding entities",
                len(new_entities),
            )
            async_add_entities(new_entities)

    coordinator.async_add_listener(_coordinator_updated)


class BaseTankBinarySensor(SmartOilTankEntity, BinarySensorEntity):
    """Base class for all per-tank binary sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        SmartOilTankEntity.__init__(self, coordinator, entry, tank_id)
        BinarySensorEntity.__init__(self)


class LowOilSensor(BaseTankBinarySensor):
    """Binary sensor: ON when tank oil level is at or below the configured low threshold."""

    _attr_name = "Low Oil"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_low_oil"

    @property
    def is_on(self) -> bool | None:
        """Return True if oil is at/below low-level threshold, False otherwise.

        Returns None if we cannot determine the state (e.g., missing data).
        """
        tank = self._tank()
        if not tank:
            return None

        gallons = _safe_float(tank.get("sensor_gallons"))
        low_fraction = _safe_float(tank.get("low_level"))
        capacity = _safe_float(tank.get("nominal"))

        if gallons is None or capacity is None or low_fraction is None:
            return None

        low_threshold_gallons = capacity * low_fraction
        return gallons <= low_threshold_gallons
