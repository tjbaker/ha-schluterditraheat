"""Select platform for Schluter DITRA-HEAT locations."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .api import SchluterApiError
from .const import BACKLIGHT_OPTIONS, KEYPAD_OPTIONS, OCCUPANCY_AWAY, OCCUPANCY_HOME
from .entity import SchluterEntity, SchluterLocationEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up location Home/Away and per-thermostat setting selects."""
    coordinator = entry.runtime_data
    # Created for every location, even if its mode couldn't be read at
    # startup; the state is unknown until a poll reads it.
    locations = {
        thermostat["location_id"]
        for thermostat in coordinator.data.values()
        if "location_id" in thermostat
    }
    entities: list[SelectEntity] = [
        SchluterLocationModeSelect(coordinator, location_id) for location_id in sorted(locations)
    ]
    entities.extend(
        SchluterSettingSelect(coordinator, device_id, description)
        for device_id, thermostat in coordinator.data.items()
        for description in SETTING_SELECTS
        if thermostat.get(description.data_key) is not None
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


@dataclass(frozen=True, kw_only=True)
class SchluterSettingSelectDescription(SelectEntityDescription):
    """A thermostat setting written as one attribute, with option -> API value."""

    data_key: str
    attribute: str
    values: dict[str, str]


SETTING_SELECTS: tuple[SchluterSettingSelectDescription, ...] = (
    SchluterSettingSelectDescription(
        key="backlight",
        translation_key="backlight",
        icon="mdi:brightness-6",
        entity_category=EntityCategory.CONFIG,
        data_key="backlight",
        attribute="backlightAutoDim",
        values=BACKLIGHT_OPTIONS,
    ),
    SchluterSettingSelectDescription(
        key="keypad",
        translation_key="keypad",
        icon="mdi:dialpad",
        entity_category=EntityCategory.CONFIG,
        data_key="keypad",
        attribute="keyboardLock",
        values=KEYPAD_OPTIONS,
    ),
)


class SchluterSettingSelect(SchluterEntity, SelectEntity):
    """A multiple-choice thermostat setting (backlight, keypad)."""

    entity_description: SchluterSettingSelectDescription

    def __init__(
        self,
        coordinator: SchluterDataUpdateCoordinator,
        device_id: int,
        description: SchluterSettingSelectDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._identifier}_{description.key}"
        self._attr_options = list(description.values)

    @property
    def current_option(self) -> str | None:
        """Return the option for the reported value, or None if it's not one we know."""
        reported = self._thermostat.get(self.entity_description.data_key)
        return next(
            (opt for opt, value in self.entity_description.values.items() if value == reported),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        description = self.entity_description
        value = description.values[option]
        try:
            await self.coordinator.api.set_device_attribute(
                self._device_id, description.attribute, value
            )
        except SchluterApiError as err:
            raise HomeAssistantError(f"Failed to change {self.name}: {err}") from err

        if self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id][description.data_key] = value
            self.async_write_ha_state()

        await self.coordinator.async_request_refresh()
