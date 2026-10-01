"""Number platform for Schluter DITRA-HEAT thermostat settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .api import SchluterApiError
from .const import AWAY_TEMPERATURE_STEP, MAX_TEMP_C, MIN_TEMP_C
from .entity import SchluterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the away temperature for thermostats that report one."""
    coordinator = entry.runtime_data
    async_add_entities(
        SchluterAwayTemperatureNumber(coordinator, device_id)
        for device_id, thermostat in coordinator.data.items()
        if thermostat.get("away_temperature") is not None
    )


class SchluterAwayTemperatureNumber(SchluterEntity, NumberEntity):
    """The setpoint the thermostat uses while Away (roomSetpointAway).

    The thermostat accepts values within its own setpoint range and rejects
    anything outside it, so the limits follow roomSetpointMin/Max.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = AWAY_TEMPERATURE_STEP
    _attr_translation_key = "away_setpoint"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the away temperature."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_away_setpoint"

    @property
    def native_value(self) -> float | None:
        """Return the away setpoint."""
        return self._thermostat.get("away_temperature")

    @property
    def native_min_value(self) -> float:
        """Return the thermostat's minimum setpoint."""
        value = self._thermostat.get("min_temp")
        return MIN_TEMP_C if value is None else value

    @property
    def native_max_value(self) -> float:
        """Return the thermostat's maximum setpoint."""
        value = self._thermostat.get("max_temp")
        return MAX_TEMP_C if value is None else value

    async def async_set_native_value(self, value: float) -> None:
        """Change the away setpoint."""
        try:
            await self.coordinator.api.set_device_attribute(
                self._device_id, "roomSetpointAway", value
            )
        except SchluterApiError as err:
            raise HomeAssistantError(f"Failed to set the away setpoint: {err}") from err

        if self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["away_temperature"] = value
            self.async_write_ha_state()

        await self.coordinator.async_request_refresh()
