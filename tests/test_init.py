"""Tests for config entry setup, unload and session handling."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schluterditraheat import SchluterDataUpdateCoordinator
from custom_components.schluterditraheat.api import (
    SchluterApiError,
    SchluterAuthenticationError,
    SchluterConnectionError,
    SchluterSessionLimitError,
)
from custom_components.schluterditraheat.const import DOMAIN
from custom_components.schluterditraheat.stats import ApiStats

STATIC = {40001: {"device_id": 40001, "identifier": "aa11bb22", "name": "Floor"}}
DYNAMIC = {40001: {"mode": "auto", "heating_percent": 0, "current_temperature": 21.0}}


pytestmark = pytest.mark.usefixtures("recorder_loaded")


@pytest.fixture
def api() -> MagicMock:
    """A SchluterApi double that logs in and returns one thermostat."""
    mock = MagicMock()
    mock.authenticate = AsyncMock()
    mock.logout = AsyncMock()
    mock.get_static_data = AsyncMock(return_value=STATIC)
    mock.get_device_attributes_bulk = AsyncMock(return_value=DYNAMIC)
    mock.rate_limit = None
    mock.stats = ApiStats()
    return mock


@pytest.fixture
def patched_api(api: MagicMock) -> Generator[MagicMock]:
    """Make the integration construct ``api`` and skip the energy import."""
    with (
        patch("custom_components.schluterditraheat.SchluterApi", return_value=api),
        patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(return_value={}),
        ),
    ):
        yield api


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry for one Schluter account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="owner@example.com",
        unique_id="owner@example.com",
        data={"username": "owner@example.com", "password": "hunter2"},
    )
    entry.add_to_hass(hass)
    return entry


def _reauth_flows(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]


async def test_setup_and_unload_logs_out(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock
) -> None:
    """Test unloading the entry ends its API session."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    patched_api.logout.assert_not_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    patched_api.logout.assert_awaited_once()


async def test_stop_logs_out(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock
) -> None:
    """Test Home Assistant shutting down ends the API session.

    Config entries are not unloaded on shutdown, so without this every
    restart would leave a session open on the account.
    """
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    patched_api.logout.assert_awaited_once()


async def test_session_limit_at_login_retries_without_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock
) -> None:
    """Test the session cap at setup retries instead of asking for the password."""
    patched_api.authenticate.side_effect = SchluterSessionLimitError("too many")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _reauth_flows(hass) == []


async def test_bad_credentials_start_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock
) -> None:
    """Test genuinely invalid credentials still ask the user to re-authenticate."""
    patched_api.authenticate.side_effect = SchluterAuthenticationError("bad password")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_failed_first_refresh_logs_out(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock
) -> None:
    """Test a setup that fails after login ends the session before HA retries."""
    patched_api.get_static_data.side_effect = SchluterConnectionError("offline")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    patched_api.logout.assert_awaited_once()


async def test_session_limit_during_poll_is_not_auth_failure(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Test the cap hit while re-logging in mid-poll fails the poll, not the credentials."""
    coordinator = SchluterDataUpdateCoordinator(hass, api)
    api.get_static_data.side_effect = SchluterSessionLimitError("too many")

    with pytest.raises(UpdateFailed, match="too many sessions"):
        await coordinator._async_update_data()


class TestReauthenticate:
    """Test the API client's mid-request re-login."""

    async def test_session_limit_propagates_unchanged(self, api_client) -> None:
        """Test the session cap is not relabeled as an authentication failure."""
        api_client.authenticate = AsyncMock(side_effect=SchluterSessionLimitError("too many"))

        with pytest.raises(SchluterSessionLimitError):
            await api_client._reauthenticate()

    async def test_other_login_errors_become_auth_failures(self, api_client) -> None:
        """Test other login failures still surface as authentication errors."""
        api_client.authenticate = AsyncMock(side_effect=SchluterApiError("nope"))

        with pytest.raises(SchluterAuthenticationError):
            await api_client._reauthenticate()


async def test_credential_check_logs_out(hass: HomeAssistant) -> None:
    """Test the config flow's credential check does not leave a session open."""
    from custom_components.schluterditraheat import config_flow

    api = MagicMock(authenticate=AsyncMock(), logout=AsyncMock())
    api.account_id = 10001
    api.temperature_unit = "f"
    with patch.object(config_flow, "SchluterApi", return_value=api):
        info = await config_flow.validate_credentials(hass, "owner@example.com", "hunter2")

    assert info["account_id"] == 10001
    api.logout.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [SchluterConnectionError("network unreachable"), SchluterApiError("missing session id")],
)
async def test_login_failure_retries_setup(
    hass: HomeAssistant, entry: MockConfigEntry, patched_api: MagicMock, error: Exception
) -> None:
    """Test an outage at startup retries instead of failing until a manual reload."""
    patched_api.authenticate.side_effect = error

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _reauth_flows(hass) == []
