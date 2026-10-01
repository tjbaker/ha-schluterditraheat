"""Tests for the config flow: setup, reauth and reconfigure."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schluterditraheat.api import (
    SchluterApiError,
    SchluterAuthenticationError,
    SchluterConnectionError,
    SchluterDailyLimitError,
    SchluterRateLimitError,
    SchluterSessionLimitError,
)
from custom_components.schluterditraheat.const import DOMAIN

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
pytestmark = pytest.mark.usefixtures("recorder_loaded")

CREDENTIALS = {CONF_USERNAME: "owner@example.com", CONF_PASSWORD: "hunter2"}

ERROR_CASES = [
    (SchluterConnectionError("down"), "cannot_connect"),
    (SchluterAuthenticationError("bad"), "invalid_auth"),
    (SchluterSessionLimitError("too many"), "session_limit"),
    (SchluterRateLimitError("slow down"), "rate_limit"),
    (SchluterDailyLimitError("cap"), "rate_limit"),
    (SchluterApiError("odd"), "unknown"),
    (RuntimeError("boom"), "unknown"),
]


@pytest.fixture
def validate() -> Generator[AsyncMock]:
    """Credential check that succeeds unless a test says otherwise."""
    with patch(
        "custom_components.schluterditraheat.config_flow.validate_credentials",
        new=AsyncMock(return_value={"account_id": 10001, "temperature_unit": "f"}),
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def setup_entry() -> Generator[AsyncMock]:
    """Don't set the integration up for real when a flow creates or reloads an entry."""
    with patch(
        "custom_components.schluterditraheat.async_setup_entry", new=AsyncMock(return_value=True)
    ) as mock:
        yield mock


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """An existing account entry, as created by earlier versions."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="owner@example.com", unique_id="owner@example.com", data=CREDENTIALS
    )
    entry.add_to_hass(hass)
    return entry


async def _start_user_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


class TestUserStep:
    """Adding an account."""

    async def test_creates_entry(self, hass: HomeAssistant, validate: AsyncMock) -> None:
        """Test valid credentials create an entry keyed by the normalized email."""
        flow_id = await _start_user_flow(hass)

        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: "  Owner@Example.com ", CONF_PASSWORD: "hunter2"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "owner@example.com"
        assert result["data"] == CREDENTIALS
        assert result["result"].unique_id == "owner@example.com"
        validate.assert_awaited_once_with(hass, "owner@example.com", "hunter2")

    async def test_duplicate_aborts_without_logging_in(
        self, hass: HomeAssistant, entry: MockConfigEntry, validate: AsyncMock
    ) -> None:
        """Test an account that is already set up aborts before any API call."""
        flow_id = await _start_user_flow(hass)

        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: "OWNER@example.com", CONF_PASSWORD: "x"}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        validate.assert_not_awaited()

    @pytest.mark.parametrize(("error", "key"), ERROR_CASES)
    async def test_errors_then_recover(
        self, hass: HomeAssistant, validate: AsyncMock, error: Exception, key: str
    ) -> None:
        """Test each failure shows its error, keeps the email, and can be retried."""
        flow_id = await _start_user_flow(hass)
        validate.side_effect = error

        result = await hass.config_entries.flow.async_configure(flow_id, CREDENTIALS)

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": key}
        suggested = {
            str(field): field.description.get("suggested_value")
            for field in result["data_schema"].schema
            if field.description
        }
        assert suggested == {CONF_USERNAME: "owner@example.com"}

        validate.side_effect = None
        result = await hass.config_entries.flow.async_configure(flow_id, CREDENTIALS)
        assert result["type"] is FlowResultType.CREATE_ENTRY


class TestReauth:
    """Re-entering the password after Schluter rejects it."""

    async def test_updates_password_and_reloads(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        validate: AsyncMock,
        setup_entry: AsyncMock,
    ) -> None:
        """Test a new password is saved and the entry reloaded."""
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        assert result["description_placeholders"][CONF_USERNAME] == "owner@example.com"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data == {CONF_USERNAME: "owner@example.com", CONF_PASSWORD: "new-password"}
        validate.assert_awaited_once_with(hass, "owner@example.com", "new-password")
        setup_entry.assert_awaited()

    @pytest.mark.parametrize(("error", "key"), ERROR_CASES)
    async def test_errors_keep_old_password(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        validate: AsyncMock,
        error: Exception,
        key: str,
    ) -> None:
        """Test a failed attempt shows the error and leaves the entry unchanged."""
        result = await entry.start_reauth_flow(hass)
        validate.side_effect = error

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": key}
        assert entry.data[CONF_PASSWORD] == "hunter2"


class TestReconfigure:
    """Updating the credentials of an existing entry."""

    async def test_updates_credentials(
        self, hass: HomeAssistant, entry: MockConfigEntry, validate: AsyncMock
    ) -> None:
        """Test new credentials for the same account are saved."""
        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "Owner@example.com", CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data == {CONF_USERNAME: "owner@example.com", CONF_PASSWORD: "new-password"}

    async def test_different_account_aborts(
        self, hass: HomeAssistant, entry: MockConfigEntry, validate: AsyncMock
    ) -> None:
        """Test switching to another account's email is refused before logging in."""
        result = await entry.start_reconfigure_flow(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "someone@else.com", CONF_PASSWORD: "x"}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "wrong_account"
        assert entry.data == CREDENTIALS
        validate.assert_not_awaited()

    async def test_error_keeps_credentials(
        self, hass: HomeAssistant, entry: MockConfigEntry, validate: AsyncMock
    ) -> None:
        """Test a rejected password shows an error and changes nothing."""
        result = await entry.start_reconfigure_flow(hass)
        validate.side_effect = SchluterAuthenticationError("bad")

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "owner@example.com", CONF_PASSWORD: "wrong"}
        )

        assert result["errors"] == {"base": "invalid_auth"}
        assert entry.data == CREDENTIALS


class TestTranslations:
    """Custom integrations load UI text from translations/, not strings.json."""

    def test_english_matches_strings(self) -> None:
        """Test translations/en.json is an exact copy of strings.json."""
        strings = json.loads((COMPONENT / "strings.json").read_text())
        english = json.loads((COMPONENT / "translations" / "en.json").read_text())
        assert english == strings

    def test_every_flow_result_has_text(self) -> None:
        """Test each error, abort reason and step the flow can show is translated."""
        config = json.loads((COMPONENT / "strings.json").read_text())["config"]
        assert {key for _, key in ERROR_CASES} <= set(config["error"])
        assert {
            "already_configured",
            "reauth_successful",
            "reconfigure_successful",
            "wrong_account",
        } <= set(config["abort"])
        assert {"user", "reauth_confirm", "reconfigure"} <= set(config["step"])
