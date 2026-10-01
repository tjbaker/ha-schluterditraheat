"""Switch platform for Schluter DITRA-HEAT thermostat settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .api import SchluterApiError
from .entity import SchluterEntity


@dataclass(frozen=True, kw_only=True)
class SchluterSwitchDescription(SwitchEntityDescription):
    """A thermostat setting written as one attribute with two values."""

    data_key: str
    attribute: str
    on_value: str
    off_value: str


SWITCHES: tuple[SchluterSwitchDescription, ...] = (
    SchluterSwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        icon="mdi:lock",
        entity_category=EntityCategory.CONFIG,
        data_key="child_lock",
        attribute="keyboardLock",
        on_value="lock",
        off_value="unlock",
    ),
    SchluterSwitchDescription(
        key="early_start",
        translation_key="early_start",
        icon="mdi:clock-start",
        entity_category=EntityCategory.CONFIG,
        data_key="early_start",
        attribute="earlyStartCfg",
        on_value="on",
        off_value="off",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for the settings each thermostat reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        SchluterSettingSwitch(coordinator, device_id, description)
        for device_id, thermostat in coordinator.data.items()
        for description in SWITCHES
        if thermostat.get(description.data_key) is not None
    )


class SchluterSettingSwitch(SchluterEntity, SwitchEntity):
    """An on/off thermostat setting (child lock, early start)."""

    entity_description: SchluterSwitchDescription

    def __init__(
        self,
        coordinator: SchluterDataUpdateCoordinator,
        device_id: int,
        description: SchluterSwitchDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._identifier}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the setting's current state."""
        return self._thermostat.get(self.entity_description.data_key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_write(False)

    async def _async_write(self, on: bool) -> None:
        description = self.entity_description
        value = description.on_value if on else description.off_value
        try:
            await self.coordinator.api.set_device_attribute(
                self._device_id, description.attribute, value
            )
        except SchluterApiError as err:
            raise HomeAssistantError(f"Failed to change {self.name}: {err}") from err

        # Optimistic update — show the new state now, confirm on the next poll
        if self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id][description.data_key] = on
            self.async_write_ha_state()

        await self.coordinator.async_request_refresh()
