"""End-to-end tests through Home Assistant against the fake Schluter cloud.

The integration runs with its real API client, coordinator and platforms;
only HTTP is faked (tests/fixtures). These guard what users depend on:
entity IDs and unique IDs, states, and the climate services.
"""

from __future__ import annotations

import re
from typing import Any

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
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

from .conftest import DEVICE_ID, LOCATION_ID, MockSession, load_fixture

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
    "sensor.home_electricity_price": "location_245001_electricity_price",
    "switch.foyer_early_start": "a1b2c3d4e5f60718_early_start",
    "select.home_occupancy": "location_245001_occupancy",
    "binary_sensor.foyer_fault": "a1b2c3d4e5f60718_fault",
    "select.foyer_backlight": "a1b2c3d4e5f60718_backlight",
    "select.foyer_keypad": "a1b2c3d4e5f60718_keypad",
    "number.foyer_away_setpoint": "a1b2c3d4e5f60718_away_setpoint",
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
        """Test the thermostat and its location register as devices with their metadata."""
        devices = sorted(
            dr.async_entries_for_config_entry(dr.async_get(hass), init_integration.entry_id),
            key=lambda d: sorted(d.identifiers),
        )

        assert [d.identifiers for d in devices] == [
            {(DOMAIN, "a1b2c3d4e5f60718")},
            {(DOMAIN, "location_245001")},
        ]
        assert devices == snapshot


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
        price = hass.states.get("sensor.home_electricity_price")
        assert price.state == str(load_fixture("locations.json")[0]["kwhCost"])
        assert price.attributes["unit_of_measurement"] == f"{hass.config.currency}/kWh"

        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, "a1b2c3d4e5f60718"), init_integration.entry_id
        )
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
        ("occupancy", "mode", "preset", "writes"),
        [
            # From home and off (the recorded state)
            ("home", "off", "away", [{"occupancyMode": "away"}]),
            ("home", "off", "frost_protection", [{"setpointMode": "frostProtection"}]),
            ("home", "off", "none", []),
            # Leaving Away restores home without turning heating on
            ("away", "off", "none", [{"occupancyMode": "home"}]),
            (
                "away",
                "auto",
                "frost_protection",
                [{"occupancyMode": "home"}, {"setpointMode": "frostProtection"}],
            ),
            # Leaving Frost protection keeps the existing behavior (manual heat)
            ("home", "frostProtection", "none", [{"setpointMode": "manual"}]),
            ("home", "frostProtection", "away", [{"occupancyMode": "away"}]),
        ],
    )
    async def test_set_preset_mode(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        occupancy: str,
        mode: str,
        preset: str,
        writes: list[dict[str, str]],
    ) -> None:
        """Test each preset writes only what it must for the thermostat's current state."""
        coordinator = init_integration.runtime_data
        coordinator.data[DEVICE_ID].update(occupancy_mode=occupancy, mode=mode)

        await self._call(hass, SERVICE_SET_PRESET_MODE, **{ATTR_PRESET_MODE: preset})

        assert _writes(mock_cloud) == writes

    async def test_away_preset_reflects_occupancy(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test the preset shows Away whenever the thermostat reports away occupancy."""
        assert hass.states.get(CLIMATE).attributes["preset_mode"] == "none"
        coordinator = init_integration.runtime_data
        coordinator.data[DEVICE_ID]["occupancy_mode"] = "away"
        coordinator.async_update_listeners()

        assert hass.states.get(CLIMATE).attributes["preset_mode"] == "away"

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


class TestSettingSwitches:
    """Early start, written as the values the cloud accepts (earlyStartCfg on/off)."""

    @pytest.mark.parametrize(
        ("entity_id", "attribute", "on_value", "off_value"),
        [
            ("switch.foyer_early_start", "earlyStartCfg", "on", "off"),
        ],
    )
    async def test_turn_on_and_off(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        entity_id: str,
        attribute: str,
        on_value: str,
        off_value: str,
    ) -> None:
        """Test each switch reports the recorded state and writes its attribute."""
        assert hass.states.get(entity_id).state == "off"

        for service in (SERVICE_TURN_ON, SERVICE_TURN_OFF):
            await hass.services.async_call(
                SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
            )

        assert _writes(mock_cloud) == [{attribute: on_value}, {attribute: off_value}]

    async def test_write_error(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a rejected write raises a HomeAssistantError and leaves the switch off."""
        mock_cloud.fail_next("PUT", ATTRIBUTE_URL, status=500, body="server error")

        with pytest.raises(HomeAssistantError, match="Early start"):
            await hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: "switch.foyer_early_start"},
                blocking=True,
            )

        assert hass.states.get("switch.foyer_early_start").state == "off"


LOCATION_MODE_URL = re.compile(rf"{re.escape(API_BASE_URL)}/location/{LOCATION_ID}/mode$")


def _mode_posts(mock_cloud: MockSession) -> list[dict[str, Any]]:
    return [
        call.kwargs["json"]
        for (method, url), calls in mock_cloud.requests.items()
        if method == "POST" and LOCATION_MODE_URL.match(str(url))
        for call in calls
    ]


class TestLocationOccupancy:
    """Home/Away for the whole location, as in the Schluter app."""

    async def test_select_away_and_home(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test selecting Away posts the location mode and the thermostats follow."""
        assert hass.states.get("select.home_occupancy").state == "home"

        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: "select.home_occupancy", ATTR_OPTION: "away"},
            blocking=True,
        )

        assert _mode_posts(mock_cloud) == [{"mode": "away"}]
        # Shown immediately; the next poll (recorded "home") reconciles it
        assert hass.states.get(CLIMATE).attributes["preset_mode"] in ("away", "none")

    async def test_optimistic_state_before_refresh(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test the location and its thermostats show Away straight after selecting it."""
        coordinator = init_integration.runtime_data
        with patch.object(coordinator, "async_request_refresh", new=AsyncMock()):
            await hass.services.async_call(
                SELECT_DOMAIN,
                SERVICE_SELECT_OPTION,
                {ATTR_ENTITY_ID: "select.home_occupancy", ATTR_OPTION: "away"},
                blocking=True,
            )

        assert hass.states.get("select.home_occupancy").state == "away"
        assert hass.states.get(CLIMATE).attributes["preset_mode"] == "away"

    async def test_error(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a rejected change raises and leaves the location at home."""
        mock_cloud.fail_next("POST", LOCATION_MODE_URL, status=500, body="server error")

        with pytest.raises(HomeAssistantError, match="occupancy"):
            await hass.services.async_call(
                SELECT_DOMAIN,
                SERVICE_SELECT_OPTION,
                {ATTR_ENTITY_ID: "select.home_occupancy", ATTR_OPTION: "away"},
                blocking=True,
            )

        assert hass.states.get("select.home_occupancy").state == "home"


class TestFaultSensor:
    """The thermostat's fault code."""

    async def test_no_fault(self, hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
        """Test the recorded code 0 reads as no problem."""
        state = hass.states.get("binary_sensor.foyer_fault")
        assert state.state == "off"
        assert state.attributes["error_code"] == 0

    async def test_fault_reported(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test a non-zero code turns the problem sensor on and shows the code."""
        coordinator = init_integration.runtime_data
        coordinator.data[DEVICE_ID]["error_code"] = 4
        coordinator.async_update_listeners()

        state = hass.states.get("binary_sensor.foyer_fault")
        assert state.state == "on"
        assert state.attributes["error_code"] == 4


class TestBacklight:
    """The backlight, using the values an RS1 accepts (alwaysOn, bedroom, off)."""

    ENTITY = "select.foyer_backlight"

    async def test_state_and_options(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test the recorded alwaysOn reads as always_on, with the three accepted options."""
        state = hass.states.get(self.ENTITY)
        assert state.state == "always_on"
        assert state.attributes["options"] == ["always_on", "bedroom", "off"]

    @pytest.mark.parametrize(("option", "sent"), [("bedroom", "bedroom"), ("off", "off")])
    async def test_select(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        option: str,
        sent: str,
    ) -> None:
        """Test each option writes its backlightAutoDim value."""
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: self.ENTITY, ATTR_OPTION: option},
            blocking=True,
        )

        assert _writes(mock_cloud) == [{"backlightAutoDim": sent}]

    async def test_unknown_reported_value(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test a value outside the known set shows as unknown rather than failing."""
        coordinator = init_integration.runtime_data
        coordinator.data[DEVICE_ID]["backlight"] = "somethingNew"
        coordinator.async_update_listeners()

        assert hass.states.get(self.ENTITY).state == "unknown"


class TestAwaySetpoint:
    """The away setpoint (roomSetpointAway)."""

    ENTITY = "number.foyer_away_setpoint"

    async def test_state_and_range(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test the recorded 15 °C with the thermostat's 5-32 °C range."""
        state = hass.states.get(self.ENTITY)
        assert float(state.state) == 15
        assert state.attributes["min"] == 5
        assert state.attributes["max"] == 32
        assert state.attributes["step"] == 0.5

    async def test_set_value(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a new away setpoint is written in Celsius and shown straight away.

        The refresh is held because the fake cloud keeps serving the recorded
        15 °C; a real thermostat reads back the new value.
        """
        coordinator = init_integration.runtime_data
        with patch.object(coordinator, "async_request_refresh", new=AsyncMock()):
            await hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: self.ENTITY, ATTR_VALUE: 16.5},
                blocking=True,
            )

        assert _writes(mock_cloud) == [{"roomSetpointAway": 16.5}]
        assert float(hass.states.get(self.ENTITY).state) == 16.5

    async def test_below_range_rejected(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test Home Assistant refuses values the thermostat would reject (4.5 °C)."""
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: self.ENTITY, ATTR_VALUE: 4.5},
                blocking=True,
            )

        assert _writes(mock_cloud) == []

    async def test_write_error(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a rejected write raises and keeps the previous value."""
        mock_cloud.fail_next("PUT", ATTRIBUTE_URL, status=500, body="server error")

        with pytest.raises(HomeAssistantError, match="away setpoint"):
            await hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: self.ENTITY, ATTR_VALUE: 17},
                blocking=True,
            )

        assert float(hass.states.get(self.ENTITY).state) == 15


class TestKeypad:
    """The thermostat keypad lock, labelled as in the Schluter app (keyboardLock lock/unlock)."""

    ENTITY = "select.foyer_keypad"

    async def test_state_and_options(
        self, hass: HomeAssistant, init_integration: MockConfigEntry
    ) -> None:
        """Test the recorded unlock reads as unlocked, with both options."""
        state = hass.states.get(self.ENTITY)
        assert state.state == "unlocked"
        assert state.attributes["options"] == ["unlocked", "locked"]

    @pytest.mark.parametrize(("option", "sent"), [("locked", "lock"), ("unlocked", "unlock")])
    async def test_select(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
        mock_cloud: MockSession,
        option: str,
        sent: str,
    ) -> None:
        """Test each option writes its keyboardLock value."""
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: self.ENTITY, ATTR_OPTION: option},
            blocking=True,
        )

        assert _writes(mock_cloud) == [{"keyboardLock": sent}]

    async def test_write_error(
        self, hass: HomeAssistant, init_integration: MockConfigEntry, mock_cloud: MockSession
    ) -> None:
        """Test a rejected write raises with the entity's name and stays unlocked."""
        mock_cloud.fail_next("PUT", ATTRIBUTE_URL, status=500, body="server error")

        with pytest.raises(HomeAssistantError, match="Keypad"):
            await hass.services.async_call(
                SELECT_DOMAIN,
                SERVICE_SELECT_OPTION,
                {ATTR_ENTITY_ID: self.ENTITY, ATTR_OPTION: "locked"},
                blocking=True,
            )

        assert hass.states.get(self.ENTITY).state == "unlocked"
