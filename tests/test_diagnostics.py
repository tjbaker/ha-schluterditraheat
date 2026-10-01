"""Tests for the diagnostics platform and its runtime counters."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schluterditraheat import SchluterDataUpdateCoordinator
from custom_components.schluterditraheat.api import (
    RateLimit,
    SchluterConnectionError,
    SchluterSessionLimitError,
)
from custom_components.schluterditraheat.const import DOMAIN
from custom_components.schluterditraheat.diagnostics import async_get_config_entry_diagnostics
from custom_components.schluterditraheat.stats import ApiStats, PollStats

THERMOSTAT: dict[str, Any] = {
    "device_id": 40001,
    "identifier": "aa11bb22cc33dd44",
    "name": "DITRA-HEAT-E-RS1",
    "location_id": 30001,
    "location_name": "12 Elm Street",
    "group_name": "Master Bath",
    "current_temperature": 23.3,
    "target_temperature": 24.0,
    "mode": "auto",
    "heating_percent": 40,
    "gfci_status": "ok",
    "rssi": -58,
}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Config entry holding real-looking credentials."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="owner@example.com",
        unique_id="owner@example.com",
        data={"username": "owner@example.com", "password": "hunter2"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def coordinator(hass: HomeAssistant, entry: MockConfigEntry) -> SchluterDataUpdateCoordinator:
    """A coordinator with one healthy thermostat, registered for the entry."""
    api = MagicMock()
    api.is_authenticated = True
    api.temperature_unit = "f"
    api.rate_limit = RateLimit(limit=120, remaining=100, reset=5, captured_at=0)
    api.stats = ApiStats(requests=12, logins=1)
    coord = SchluterDataUpdateCoordinator(hass, api)
    coord.data = {40001: dict(THERMOSTAT)}
    coord._static_data = {40001: {}}
    coord.last_update_success = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    return coord


async def test_healthy_snapshot_is_redacted(
    hass: HomeAssistant, entry: MockConfigEntry, coordinator: SchluterDataUpdateCoordinator
) -> None:
    """Test a healthy install reports no issues and leaks no credentials."""
    diag = await async_get_config_entry_diagnostics(hass, entry)

    dumped = json.dumps(diag, default=str)
    for secret in ("owner@example.com", "hunter2", "aa11bb22cc33dd44", "12 Elm Street"):
        assert secret not in dumped

    assert diag["analysis"] == {"health": "healthy", "issues": [], "recommendations": []}
    assert diag["api"]["rate_limit"]["remaining"] == 100
    assert diag["api"]["requests"] == 12
    assert diag["coordinator"]["update_interval_seconds"] == 300
    device = diag["devices"]["40001"]
    assert device["identifier"] == "aa11…"
    assert device["group_name"] == "Master Bath"
    assert device["rssi"] == -58


async def test_not_loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Test diagnostics still work when setup never produced a coordinator."""
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["analysis"]["health"] == "not_loaded"
    assert "coordinator" not in diag


async def test_device_problems_are_flagged(
    hass: HomeAssistant, entry: MockConfigEntry, coordinator: SchluterDataUpdateCoordinator
) -> None:
    """Test weak Wi-Fi, a GFCI trip and a missing device each produce an issue."""
    coordinator.data[40001].update(rssi=-88, gfci_status="tripped")
    coordinator.poll_stats.devices_missing_last_poll = [40002]

    analysis = (await async_get_config_entry_diagnostics(hass, entry))["analysis"]

    assert analysis["health"] == "degraded"
    issues = " ".join(analysis["issues"])
    assert "very weak (-88 dBm)" in issues
    assert "GFCI reports 'tripped'" in issues
    assert "40002" in issues
    assert len(analysis["recommendations"]) == 3


async def test_limits_and_failures_are_flagged(
    hass: HomeAssistant, entry: MockConfigEntry, coordinator: SchluterDataUpdateCoordinator
) -> None:
    """Test the daily cap, a drained budget and repeated session-limit failures."""
    coordinator.daily_limit_reached = True
    coordinator.api.rate_limit = RateLimit(limit=120, remaining=0, reset=5, captured_at=0)
    coordinator.last_update_success = False
    for _ in range(3):
        coordinator.poll_stats.note_failure(10.0, SchluterSessionLimitError("too many"))

    analysis = (await async_get_config_entry_diagnostics(hass, entry))["analysis"]

    assert analysis["health"] == "failing"
    issues = " ".join(analysis["issues"])
    assert "daily API request cap" in issues
    assert "remaining=0" in issues
    assert "last 3 polls failed (SchluterSessionLimitError)" in issues
    assert "too many active sessions" in issues
    assert any("Log out" in rec for rec in analysis["recommendations"])


async def test_backoff_reported(
    hass: HomeAssistant, entry: MockConfigEntry, coordinator: SchluterDataUpdateCoordinator
) -> None:
    """Test an active rate-limit backoff is surfaced with its interval."""
    coordinator._backoff_interval = timedelta(minutes=4)

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["coordinator"]["backoff_interval_seconds"] == 240
    assert "backed off to 0:04:00" in " ".join(diag["analysis"]["issues"])


async def test_energy_statistic_ids_are_masked(
    hass: HomeAssistant, entry: MockConfigEntry, coordinator: SchluterDataUpdateCoordinator
) -> None:
    """Test imported-row counts keep their statistic but hide the identifier."""
    coordinator.energy_stats.note_run({"schluterditraheat:energy_aa11bb22cc33dd44": 24})

    energy = (await async_get_config_entry_diagnostics(hass, entry))["energy"]

    assert energy["runs"] == 1
    assert energy["rows_imported_last_run"] == {"schluterditraheat:energy_aa11…": 24}


class TestPollStats:
    """Test the coordinator records poll outcomes."""

    async def test_success_and_failure_are_recorded(
        self, hass: HomeAssistant, coordinator: SchluterDataUpdateCoordinator
    ) -> None:
        """Test a failing poll then a successful one update the counters."""
        coordinator._static_data = None
        coordinator.api.get_static_data = MagicMock(side_effect=SchluterConnectionError("offline"))
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        stats: PollStats = coordinator.poll_stats
        assert stats.polls == 1
        assert stats.consecutive_failures == 1
        assert stats.last_failure is not None
        assert stats.last_failure["type"] == "SchluterConnectionError"

        async def _static() -> dict[int, dict[str, Any]]:
            return {40001: {"identifier": "aa11"}, 40002: {"identifier": "bb22"}}

        async def _bulk(_ids: list[int]) -> dict[int, dict[str, Any]]:
            return {40001: {"mode": "auto"}}

        coordinator._static_data = None
        coordinator.api.get_static_data = _static
        coordinator.api.get_device_attributes_bulk = _bulk
        coordinator.api.rate_limit = None
        await coordinator._async_update_data()

        assert stats.polls == 2
        assert stats.consecutive_failures == 0
        assert stats.failures == 1
        assert stats.failures_by_type == {"SchluterConnectionError": 1}
        assert stats.devices_missing_last_poll == [40002]
        assert stats.last_static_refresh is not None


class TestApiStats:
    """Test the API client counts requests and logins."""

    async def test_login_and_requests_counted(self, api_client, mock_aiohttp) -> None:
        """Test a login and an authenticated request are both counted."""
        from custom_components.schluterditraheat.const import API_BASE_URL

        mock_aiohttp.post(
            f"{API_BASE_URL}/login",
            payload={"session": "s", "account": {"id": 10001}, "user": {}},
        )
        mock_aiohttp.get(
            f"{API_BASE_URL}/locations?account$id=10001",
            payload=[{"id": 1, "name": "Home"}],
        )

        await api_client.authenticate()
        await api_client.get_locations()

        assert api_client.stats.logins == 1
        assert api_client.stats.requests == 1
        assert api_client.stats.last_login is not None
