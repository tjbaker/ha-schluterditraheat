"""Sensor platform for Schluter DITRA-HEAT."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .const import DEFAULT_MANUFACTURER, DOMAIN
from .entity import SchluterEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Schluter sensor entities from a config entry."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for device_id, thermostat in coordinator.data.items():
        entities.append(SchluterHeatingOutputSensor(coordinator, device_id))
        entities.append(SchluterPowerSensor(coordinator, device_id))

        # Only create the Wi-Fi sensor for devices that actually report a
        # signal, rather than leaving everyone else with a permanently unknown
        # diagnostic entity.
        if "rssi" in thermostat:
            entities.append(SchluterWifiSignalSensor(coordinator, device_id))
        else:
            _LOGGER.debug("Device %s reported no Wi-Fi signal; skipping the sensor", device_id)

    # One price per Schluter location, shared by its thermostats. Skipped when
    # no price is set in the app, rather than reporting a misleading 0.
    priced_locations = {
        thermostat["location_id"]
        for thermostat in coordinator.data.values()
        if thermostat.get("electricity_price")
    }
    entities.extend(
        SchluterElectricityPriceSensor(coordinator, location_id)
        for location_id in sorted(priced_locations)
    )

    async_add_entities(entities)


class SchluterHeatingOutputSensor(SchluterEntity, SensorEntity):
    """Sensor for heating output percentage on a Schluter thermostat."""

    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_name = "Heating Output"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the heating output sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_heating_output"

    @property
    def native_value(self) -> int:
        """Return the current heating output percentage."""
        return self._thermostat.get("heating_percent", 0)


class SchluterWifiSignalSensor(SchluterEntity, SensorEntity):
    """Wi-Fi signal strength reported by a Schluter thermostat.

    The web app buckets this into a five-level scale (amazing, very good,
    okay, weak, very weak); the API itself returns the raw dBm value, which is
    what we expose.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Wi-Fi Signal"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the Wi-Fi signal sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_wifi_signal"

    @property
    def native_value(self) -> int | None:
        """Return the Wi-Fi signal strength in dBm."""
        return self._thermostat.get("rssi")


class SchluterPowerSensor(SchluterEntity, SensorEntity):
    """Instantaneous power draw of a Schluter thermostat's heating load.

    The heating cable is resistive: it switches fully on or fully off, it does
    not modulate. So the instantaneous draw is the whole connected load whenever
    the thermostat is calling for heat, and zero otherwise -- not the load scaled
    by the output percentage.

    ``outputPercentDisplay`` is the duty cycle *target* for the current PWM
    window, not a live power level: it reads 0 through the off phase of each
    cycle and the target percentage while the cable conducts. Multiplying the
    load by it therefore understates the real draw (validated against the cloud's
    hourly consumption: on/off matched to ~2%, load x percent was off by ~60%).
    The cloud consumption import, not a time-integral of this sensor, is the
    authoritative energy figure for the Energy dashboard.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_name = "Power"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the power sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_power"

    @property
    def native_value(self) -> float | None:
        """Return the current power draw in watts (full load when heating, else 0)."""
        thermostat = self._thermostat
        if not thermostat:
            return None
        load_watt = thermostat.get("load_watt") or 0
        heating_percent = thermostat.get("heating_percent") or 0
        return float(load_watt) if heating_percent > 0 else 0.0


class SchluterElectricityPriceSensor(
    CoordinatorEntity[SchluterDataUpdateCoordinator], SensorEntity
):
    """Electricity price set for a location in the Schluter app.

    Select it under Settings → Dashboards → Energy ("Use an entity with
    current price") to show the cost of the imported consumption.
    """

    _attr_has_entity_name = True
    _attr_name = "Electricity price"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, location_id: int) -> None:
        """Initialize the price sensor for one location."""
        super().__init__(coordinator)
        self._location_id = location_id
        self._attr_unique_id = f"location_{location_id}_electricity_price"
        self._attr_native_unit_of_measurement = (
            f"{coordinator.hass.config.currency}/{UnitOfEnergy.KILO_WATT_HOUR}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=self._location.get("location_name") or "Schluter location",
            manufacturer=DEFAULT_MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _location(self) -> dict:
        """Data of any thermostat at this location (location fields are shared)."""
        return next(
            (
                thermostat
                for thermostat in (self.coordinator.data or {}).values()
                if thermostat.get("location_id") == self._location_id
            ),
            {},
        )

    @property
    def available(self) -> bool:
        """Return True while a thermostat at this location is reporting."""
        return super().available and bool(self._location)

    @property
    def native_value(self) -> float | None:
        """Return the price per kWh."""
        return self._location.get("electricity_price")
