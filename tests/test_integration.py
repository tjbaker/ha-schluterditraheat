"""End-to-end tests through Home Assistant against the fake Schluter cloud.

The integration runs with its real API client, coordinator and platforms;
only HTTP is faked (tests/fixtures). These guard what users depend on:
entity IDs and unique IDs, states, and the climate services.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.schluterditraheat.const import API_BASE_URL, DOMAIN

from .conftest import DEVICE_ID, MockSession, load_fixture

CLIMATE = "climate.foyer_floor_heat"
ATTRIBUTE_URL = re.compile(rf"{re.escape(API_BASE_URL)}/device/{DEVICE_ID}/attribute$")

# The contract with users switching from the upstream integration: these
# unique IDs (and the entity IDs derived from them) must never change.
# Upstream 1.1.0 created the first three; the rest were added in 2.0.0.
EXPECTED_ENTITIES = {
    "climate.foyer_floor_heat": "a1b2c3d4e5f60718",
    "sensor.foyer_heating_output": "a1b2c3d4e5f60718_heating_output",
    "binary_sensor.foyer_gfci_status": "a1b2c3d4e5f60718_gfci",
    "sensor.foyer_power": "a1b2c3d4e5f60718_power",
    "sensor.foyer_wi_fi_signal": "a1b2c3d4e5f60718_wifi_signal",
    "button.foyer_refresh": "a1b2c3d4e5f60718_refresh",
}


def _writes(mock_cloud: MockSession) -> list[dict[str, Any]]:
    """JSON bodies of every attribute write the integration sent, in order."""
    return [
        call.kwargs["json"]
        for (method, url), calls in mock_cloud.requests.items()
        if method == "PUT" and ATTRIBUTE_URL.match(str(url))
        for call in calls
    ]


class TestRegistry:
    """Entities and the device as Home Assistant registers them."""

    async def test_entity_ids_and_unique_ids_are_stable(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test every entity keeps the entity ID and unique ID existing installs rely on."""
        entries = er.async_entries_for_config_entry(er.async_get(hass), init_integration.entry_id)

        assert {e.entity_id: e.unique_id for e in entries} == EXPECTED_ENTITIES

    async def test_entities_and_states_snapshot(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Test each entity's registry entry and state against the stored snapshot."""
        registry = er.async_get(hass)
        for entry in sorted(
            er.async_entries_for_config_entry(registry, init_integration.entry_id),
            key=lambda e: e.entity_id,
        ):
            assert entry == snapshot(name=f"{entry.entity_id}-entry")
            assert hass.states.get(entry.entity_id) == snapshot(name=f"{entry.entity_id}-state")

    async def test_device_snapshot(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Test the thermostat registers as one device with its metadata."""
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), init_integration.entry_id)

        assert len(devices) == 1
        assert devices[0].identifiers == {(DOMAIN, "a1b2c3d4e5f60718")}
        assert devices[0] == snapshot


class TestRecordedPayload:
    """The recorded RS1 attribute payload, as the entities present it."""

    async def test_states(self, hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
        """Test readings from a real thermostat response reach the entities intact."""
        climate = hass.states.get(CLIMATE)
        assert climate.state == HVACMode.OFF
        assert climate.attributes["current_temperature"] == 19.4
        assert climate.attributes["temperature"] == 21.1
        assert climate.attributes["min_temp"] == 5
        assert climate.attributes["max_temp"] == 32
        recorded = load_fixture("attributes_rs1.json")
        assert hass.states.get("sensor.foyer_wi_fi_signal").state == str(recorded["wifiRssi"])
        assert hass.states.get("sensor.foyer_heating_output").state == "0"
        assert hass.states.get("binary_sensor.foyer_gfci_status").state == "off"

        (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), init_integration.entry_id)
        assert device.model == "DITRA-HEAT-E-RS1"
        assert device.sw_version == "3.7.10"
        assert device.hw_version == "1"


class TestClimateServices:
    """Thermostat control through Home Assistant's climate services."""

    async def _call(self, hass: HomeAssistant, service: str, **data: Any) -> None:
        await hass.services.async_call(
            CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: CLIMATE, **data}, blocking=True
        )

    async def test_set_temperature(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a setpoint inside the thermostat's range is sent as roomSetpoint."""
        await self._call(hass, SERVICE_SET_TEMPERATURE, **{ATTR_TEMPERATURE: 30})

        assert _writes(mock_cloud) == [{"roomSetpoint": 30}]

    @pytest.mark.parametrize("temperature", [4, 33])
    async def test_set_temperature_outside_device_range(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        temperature: float,
    ) -> None:
        """Test Home Assistant rejects setpoints outside the reported 5-32 °C range."""
        with pytest.raises(ServiceValidationError):
            await self._call(hass, SERVICE_SET_TEMPERATURE, **{ATTR_TEMPERATURE: temperature})

        assert _writes(mock_cloud) == []

    @pytest.mark.parametrize(
        ("hvac_mode", "sent"),
        [(HVACMode.HEAT, "manual"), (HVACMode.AUTO, "auto"), (HVACMode.OFF, "off")],
    )
    async def test_set_hvac_mode(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        hvac_mode: HVACMode,
        sent: str,
    ) -> None:
        """Test each HVAC mode sends the setpointMode the cloud accepts.

        Heat must send "manual": "autoBypass" is ignored from off (upstream #2, #8).
        """
        await self._call(hass, SERVICE_SET_HVAC_MODE, **{ATTR_HVAC_MODE: hvac_mode})

        assert _writes(mock_cloud) == [{"setpointMode": sent}]

    async def test_turn_on_and_off(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test the card's power button turns the floor on in manual and back off."""
        await self._call(hass, SERVICE_TURN_ON)
        await self._call(hass, SERVICE_TURN_OFF)

        assert _writes(mock_cloud) == [{"setpointMode": "manual"}, {"setpointMode": "off"}]

    @pytest.mark.parametrize(
        ("preset", "sent"), [("frost_protection", "frostProtection"), ("none", "manual")]
    )
    async def test_set_preset_mode(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        preset: str,
        sent: str,
    ) -> None:
        """Test presets map to their setpointMode values."""
        await self._call(hass, SERVICE_SET_PRESET_MODE, **{ATTR_PRESET_MODE: preset})

        assert _writes(mock_cloud) == [{"setpointMode": sent}]

    @pytest.mark.parametrize(
        ("service", "data"),
        [
            (SERVICE_SET_TEMPERATURE, {ATTR_TEMPERATURE: 25}),
            (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.HEAT}),
            (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: "frost_protection"}),
        ],
    )
    async def test_cloud_error_is_reported_cleanly(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        service: str,
        data: dict[str, Any],
    ) -> None:
        """Test a rejected write surfaces as a HomeAssistantError and changes no state."""
        before = hass.states.get(CLIMATE)
        mock_cloud.fail_next("PUT", ATTRIBUTE_URL, status=500, body="server error")

        with pytest.raises(HomeAssistantError):
            await self._call(hass, service, **data)

        after = hass.states.get(CLIMATE)
        assert after.state == before.state
        assert after.attributes == before.attributes


async def test_refresh_button_polls_now(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
) -> None:
    """Test pressing Refresh fetches thermostat state immediately."""

    def attribute_reads() -> int:
        return sum(
            len(calls)
            for (method, url), calls in mock_cloud.requests.items()
            if method == "GET" and f"/device/{DEVICE_ID}/attribute?" in str(url)
        )

    before = attribute_reads()
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: "button.foyer_refresh"}, blocking=True
    )
    await hass.async_block_till_done()

    assert attribute_reads() == before + 1
