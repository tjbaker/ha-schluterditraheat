"""Select platform for Schluter DITRA-HEAT locations."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .api import SchluterApiError
from .const import BACKLIGHT_OPTIONS, OCCUPANCY_AWAY, OCCUPANCY_HOME
from .entity import SchluterEntity, SchluterLocationEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up location Home/Away and per-thermostat backlight selects."""
    coordinator = entry.runtime_data
    locations = {
        thermostat["location_id"]
        for thermostat in coordinator.data.values()
        if thermostat.get("location_mode") is not None
    }
    entities: list[SelectEntity] = [
        SchluterLocationModeSelect(coordinator, location_id) for location_id in sorted(locations)
    ]
    entities.extend(
        SchluterBacklightSelect(coordinator, device_id)
        for device_id, thermostat in coordinator.data.items()
        if thermostat.get("backlight") is not None
    )
    async_add_entities(entities)


class SchluterLocationModeSelect(SchluterLocationEntity, SelectEntity):
    """Home or Away for every thermostat at a location, like the Schluter app's mode."""

    _attr_icon = "mdi:home-account"
    _attr_options = [OCCUPANCY_HOME, OCCUPANCY_AWAY]
    _attr_translation_key = "occupancy"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, location_id: int) -> None:
        """Initialize the select for one location."""
        super().__init__(coordinator, location_id)
        self._attr_unique_id = f"location_{location_id}_occupancy"

    @property
    def current_option(self) -> str | None:
        """Return the location's current mode."""
        mode = self._location.get("location_mode")
        return mode if mode in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Switch every thermostat at the location to home or away."""
        try:
            await self.coordinator.api.set_location_mode(self._location_id, option)
        except SchluterApiError as err:
            raise HomeAssistantError(f"Failed to set occupancy to {option}: {err}") from err

        # Optimistic update — the location and each of its thermostats change
        for device_id in self._thermostat_ids:
            self.coordinator.data[device_id]["location_mode"] = option
            self.coordinator.data[device_id]["occupancy_mode"] = option
        self.coordinator.async_update_listeners()

        await self.coordinator.async_request_refresh()


class SchluterBacklightSelect(SchluterEntity, SelectEntity):
    """The thermostat display's backlight behavior."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:brightness-6"
    _attr_options = list(BACKLIGHT_OPTIONS)
    _attr_translation_key = "backlight"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the backlight select."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_backlight"

    @property
    def current_option(self) -> str | None:
        """Return the option for the reported value, or None if it's not one we know."""
        reported = self._thermostat.get("backlight")
        return next((opt for opt, value in BACKLIGHT_OPTIONS.items() if value == reported), None)

    async def async_select_option(self, option: str) -> None:
        """Change the backlight behavior."""
        try:
            await self.coordinator.api.set_device_attribute(
                self._device_id, "backlightAutoDim", BACKLIGHT_OPTIONS[option]
            )
        except SchluterApiError as err:
            raise HomeAssistantError(f"Failed to set the display backlight: {err}") from err

        if self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["backlight"] = BACKLIGHT_OPTIONS[option]
            self.async_write_ha_state()

        await self.coordinator.async_request_refresh()
