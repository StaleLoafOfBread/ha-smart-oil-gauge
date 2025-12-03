"""Sensor platform for Smart Oil Gauge."""

from __future__ import annotations

import logging
from typing import Any, Iterable, List

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import SmartOilTankEntity, _safe_float, _tanks_from

_LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# async_setup_entry
# -----------------------------------------------------------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Oil Gauge sensor entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Track tank IDs we've already created entities for, so that we can add
    # new entities only when new tanks appear in future coordinator updates.
    created_tank_ids: set[str] = set()

    # Helper to build all sensor entities for a single tank
    def build_entities_for_tank(tank: dict[str, Any]) -> Iterable[Entity]:
        tank_id = str(tank.get("tank_id", "unknown"))
        return (
            TankNameSensor(coordinator, entry, tank_id),
            TankIdSensor(coordinator, entry, tank_id),
            GallonsSensor(coordinator, entry, tank_id),
            SensorUsgSensor(coordinator, entry, tank_id),
            PercentFullSensor(coordinator, entry, tank_id),
            LastReadSensor(coordinator, entry, tank_id),
            BatteryStatusSensor(coordinator, entry, tank_id),
            StatusSensor(coordinator, entry, tank_id),
            NominalCapacitySensor(coordinator, entry, tank_id),
            FillableCapacitySensor(coordinator, entry, tank_id),
            LowLevelSensor(coordinator, entry, tank_id),
            ZipSensor(coordinator, entry, tank_id),
        )

    # Always include the account-level sensor so the account appears as a device
    entities: List[Entity] = [AccountSensor(coordinator, entry)]

    tanks = _tanks_from(coordinator.data)

    # Initial entities for existing tanks
    for tank in tanks:
        tank_id = str(tank.get("tank_id", "unknown"))
        if tank_id not in created_tank_ids:
            created_tank_ids.add(tank_id)
            entities.extend(build_entities_for_tank(tank))

    if entities:
        async_add_entities(entities)

    # Listener to dynamically create entities when new tanks appear
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
                "Smart Oil Gauge (sensor): discovered %d new tank(s); adding entities",
                len(new_entities),
            )
            async_add_entities(new_entities)

    coordinator.async_add_listener(_coordinator_updated)


# -----------------------------------------------------------------------------
# Base classes
# -----------------------------------------------------------------------------
class BaseTankSensor(SmartOilTankEntity, SensorEntity):
    """Base class for all per-tank sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        SmartOilTankEntity.__init__(self, coordinator, entry, tank_id)
        SensorEntity.__init__(self)


class AccountSensor(CoordinatorEntity, SensorEntity):
    """Integration-level sensor that reports the number of tanks on the account."""

    _attr_name = "Number of Tanks"
    _attr_icon = "mdi:barrel"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_tank_count"

    @property
    def device_info(self) -> dict[str, Any]:
        """Account-level device for all tanks."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Smart Oil Gauge",
            "manufacturer": "Connected Consumer Fuel",
            "model": "Smart Oil Gauge Account",
            "configuration_url": "https://app.smartoilgauge.com/",
        }

    @property
    def native_value(self) -> int:
        """Return number of tanks associated with this account."""
        tanks = _tanks_from(self.coordinator.data)
        return len(tanks)


# -----------------------------------------------------------------------------
# Per-tank diagnostic/config sensors
# -----------------------------------------------------------------------------
class TankNameSensor(BaseTankSensor):
    """Tank name reported by the API."""

    _attr_name = "Tank Name"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_name"

    @property
    def native_value(self) -> str | None:
        t = self._tank()
        return t.get("tank_name") if t else None


class TankIdSensor(BaseTankSensor):
    """Tank ID as seen by the Smart Oil Gauge API."""

    _attr_name = "Tank ID"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_tank_id"

    @property
    def native_value(self) -> Any:
        t = self._tank()
        return t.get("tank_id") if t else None


class ZipSensor(BaseTankSensor):
    """ZIP code associated with this tank."""

    _attr_name = "ZIP Code"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_zip"

    @property
    def native_value(self) -> str | None:
        t = self._tank()
        return t.get("zip_code") if t else None


# -----------------------------------------------------------------------------
# Capacity & volume sensors
# -----------------------------------------------------------------------------
class GallonsSensor(BaseTankSensor):
    """Current gallons remaining in the tank."""

    _attr_name = "Gallons"
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0  # Show whole gallons by default

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_gallons"

    @property
    def native_value(self) -> float | None:
        t = self._tank()
        return _safe_float(t.get("sensor_gallons")) if t else None


class NominalCapacitySensor(BaseTankSensor):
    """Configured nominal tank capacity in gallons."""

    _attr_name = "Nominal Capacity"
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_nominal"

    @property
    def native_value(self) -> float | None:
        t = self._tank()
        if not t:
            return None
        return _safe_float(t.get("nominal"))


class FillableCapacitySensor(BaseTankSensor):
    """Configured fillable capacity in gallons (usually less than nominal)."""

    _attr_name = "Fillable Capacity"
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_suggested_display_precision = 0  # API returns whole gallons
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_fillable"

    @property
    def native_value(self) -> float | None:
        tank = self._tank()
        if not tank:
            return None
        return _safe_float(tank.get("fillable"))


# -----------------------------------------------------------------------------
# Usage / flow-rate sensor
# -----------------------------------------------------------------------------
class SensorUsgSensor(BaseTankSensor):
    """Average oil usage in gallons per day, as reported by the API."""

    _attr_name = "Oil Usage"
    # The underlying API field ("sensor_usg") is gal/day.
    # We use a custom unit string for now.
    _attr_native_unit_of_measurement = "gal/d"
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_sensor_usg"

    @property
    def native_value(self) -> float | None:
        t = self._tank()
        raw = t.get("sensor_usg") if t else None

        if raw in (None, ""):
            return None

        return _safe_float(raw)


# -----------------------------------------------------------------------------
# Percentage and status sensors
# -----------------------------------------------------------------------------
class PercentFullSensor(BaseTankSensor):
    """Tank percent full, computed from gallons and nominal capacity."""

    _attr_name = "Percent Full"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_device_class = SensorDeviceClass.BATTERY  # conceptually "fullness"

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_percent"

    @property
    def native_value(self) -> float | None:
        t = self._tank()
        if not t:
            return None

        gallons = _safe_float(t.get("sensor_gallons")) or 0.0
        capacity = _safe_float(t.get("nominal")) or 0.0

        if capacity <= 0:
            return 0.0

        return round(gallons / capacity * 100.0, 2)


class LowLevelSensor(BaseTankSensor):
    """Configured low-level threshold as a percentage of nominal capacity."""

    _attr_name = "Low Level Threshold"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:gauge-low"

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_low_level"

    @property
    def native_value(self) -> float | None:
        t = self._tank()
        if not t:
            return None

        fraction = _safe_float(t.get("low_level"))
        if fraction is None:
            return None

        return fraction * 100.0


class BatteryStatusSensor(BaseTankSensor):
    """Battery status text as reported by the Smart Oil Gauge device."""

    _attr_name = "Battery Status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_battery_status"

    @property
    def native_value(self) -> str | None:
        t = self._tank()
        return t.get("battery") if t else None

    @property
    def icon(self) -> str:
        val = (self.native_value or "").lower()
        # The only documented value is "excellent" – treat others as a warning.
        return "mdi:battery" if val == "excellent" else "mdi:battery-alert"


class StatusSensor(BaseTankSensor):
    """Sensor health / status string as reported by the API."""

    _attr_name = "Sensor Status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_sensor_status"

    @property
    def native_value(self) -> str | None:
        t = self._tank()
        return t.get("sensor_status") if t else None


class LastReadSensor(BaseTankSensor):
    """Timestamp when the tank was last read by the device."""

    _attr_name = "Last Read"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, tank_id: str) -> None:
        super().__init__(coordinator, entry, tank_id)
        self._attr_unique_id = f"{entry.entry_id}_{tank_id}_last_read"

    @property
    def native_value(self):
        """Return the last-read timestamp as an aware datetime in local time."""
        t = self._tank()
        if not t:
            return None

        try:
            epoch = int(t.get("last_read"))
        except (ValueError, TypeError):
            return None

        return dt_util.as_local(dt_util.utc_from_timestamp(epoch))
