"""Binary sensor platform for Schluter DITRA-HEAT."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .entity import SchluterEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Schluter binary sensor entities from a config entry."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        SchluterGfciBinarySensor(coordinator, device_id) for device_id in coordinator.data
    ]
    entities.extend(
        SchluterFaultBinarySensor(coordinator, device_id)
        for device_id, thermostat in coordinator.data.items()
        if thermostat.get("error_code") is not None
    )
    async_add_entities(entities)


class SchluterGfciBinarySensor(SchluterEntity, BinarySensorEntity):
    """Binary sensor for GFCI fault detection on a Schluter thermostat."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "GFCI Status"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the GFCI binary sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_gfci"

    @property
    def is_on(self) -> bool | None:
        """Return True if GFCI fault detected."""
        gfci_status = self._thermostat.get("gfci_status")
        if gfci_status is None:
            return None
        return gfci_status != "ok"


class SchluterFaultBinarySensor(SchluterEntity, BinarySensorEntity):
    """On when the thermostat reports a fault code.

    The cloud only exposes the raw code (errorCodeSet1); Schluter doesn't
    document what each code means, so it is shown as an attribute for the
    user to look up or report.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Fault"

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the fault sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{self._identifier}_fault"

    @property
    def is_on(self) -> bool | None:
        """Return True if the thermostat reports a non-zero fault code."""
        code = self._thermostat.get("error_code")
        return None if code is None else code != 0

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        """Return the raw fault code."""
        return {"error_code": self._thermostat.get("error_code")}
