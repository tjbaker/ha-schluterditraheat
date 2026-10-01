"""Shared entity base for Schluter DITRA-HEAT."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SchluterDataUpdateCoordinator
from .const import DEFAULT_MANUFACTURER, DEFAULT_MODEL, DOMAIN


def resolve_model(thermostat: dict[str, Any]) -> str:
    """Best available model string for a thermostat.

    The API returns a literal "?" for sku on these thermostats, so a plain
    dict.get() default never fires. Fall back to the model code from the
    device's signature, then to the product name.
    """
    sku = thermostat.get("sku")
    if sku and sku != "?":
        return str(sku)
    return thermostat.get("signature_model") or DEFAULT_MODEL


class SchluterEntity(CoordinatorEntity[SchluterDataUpdateCoordinator]):
    """Base for every entity backed by a Schluter thermostat.

    Owns the device registry entry so the platforms cannot drift apart: they
    all call async_get_or_create with whatever they declare here, and the last
    one to set up would otherwise win.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, device_id: int) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id

        # Captured once: the device's identity must not change even if it
        # drops out of coordinator data, or we would register a second,
        # bogus device the next time device_info is read.
        self._identifier: str = coordinator.data[device_id]["identifier"]

    @property
    def _thermostat(self) -> dict[str, Any]:
        """This entity's slice of coordinator data, or {} once it's gone."""
        return (self.coordinator.data or {}).get(self._device_id) or {}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._device_id in (self.coordinator.data or {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device registry entry.

        Home Assistant reads this when the entity is added, so a firmware
        version picked up by a later poll lands on the next restart. That is
        fine for a value that changes about once a year, and far cheaper than
        pushing registry updates from every entity on every poll.
        """
        thermostat = self._thermostat

        info = DeviceInfo(
            identifiers={(DOMAIN, self._identifier)},
            name=thermostat.get("group_name") or thermostat.get("name"),
            manufacturer=thermostat.get("vendor") or DEFAULT_MANUFACTURER,
            model=resolve_model(thermostat),
            serial_number=self._identifier,
        )

        # Omit rather than blank: an absent key is hidden in the UI, an empty
        # one renders as a stray blank row.
        for key in ("sw_version", "hw_version"):
            if value := thermostat.get(key):
                info[key] = value

        return info


class SchluterLocationEntity(CoordinatorEntity[SchluterDataUpdateCoordinator]):
    """Base for entities that belong to a Schluter location (a home), not a thermostat.

    Every location entity registers the same service device, so the platforms
    cannot drift apart.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SchluterDataUpdateCoordinator, location_id: int) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._location_id = location_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=self._location.get("location_name") or "Schluter location",
            manufacturer=DEFAULT_MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _location(self) -> dict[str, Any]:
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
    def _thermostat_ids(self) -> list[int]:
        """Device ids of the thermostats at this location."""
        return [
            device_id
            for device_id, thermostat in (self.coordinator.data or {}).items()
            if thermostat.get("location_id") == self._location_id
        ]

    @property
    def available(self) -> bool:
        """Return True while a thermostat at this location is reporting."""
        return super().available and bool(self._location)
