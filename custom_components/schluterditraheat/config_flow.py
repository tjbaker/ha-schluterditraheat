"""Config flow for Schluter DITRA-HEAT integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SchluterApi,
    SchluterApiError,
    SchluterAuthenticationError,
    SchluterConnectionError,
    SchluterRateLimitError,
    SchluterSessionLimitError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_PASSWORD_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def normalize_username(username: str) -> str:
    """Account email as stored in the entry; also the entry's unique ID."""
    return username.strip().lower()


async def validate_credentials(hass: HomeAssistant, username: str, password: str) -> dict[str, Any]:
    """Validate credentials by attempting authentication.

    Returns account information on success.
    Raises exceptions on failure.
    """
    session = async_get_clientsession(hass)
    api = SchluterApi(session, username, password)

    await api.authenticate()
    info = {
        "account_id": api.account_id,
        "temperature_unit": api.temperature_unit,
    }
    # The integration opens its own session on setup; don't leave this one
    # counting toward the account's session cap.
    await api.logout()
    return info


def _suggest_username(user_input: dict[str, Any] | None) -> dict[str, Any]:
    """Values to pre-fill when a form is shown again: never the password."""
    return {CONF_USERNAME: user_input[CONF_USERNAME]} if user_input else {}


async def _async_try_login(hass: HomeAssistant, username: str, password: str) -> str | None:
    """Validate credentials, returning a translated error key or None on success."""
    try:
        await validate_credentials(hass, username, password)
    except SchluterConnectionError:
        return "cannot_connect"
    except SchluterSessionLimitError:
        return "session_limit"
    except SchluterAuthenticationError:
        return "invalid_auth"
    except SchluterRateLimitError:
        return "rate_limit"
    except SchluterApiError:
        _LOGGER.exception("Unexpected response from the Schluter API")
        return "unknown"
    except Exception:  # noqa: BLE001 - surface any failure as a form error, not a crash
        _LOGGER.exception("Unexpected exception while validating credentials")
        return "unknown"
    return None


class SchluterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Schluter DITRA-HEAT."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up an account from its email and password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = normalize_username(user_input[CONF_USERNAME])
            # Abort before any network call, so adding an existing account
            # never opens a session.
            await self.async_set_unique_id(username)
            self._abort_if_unique_id_configured()

            password = user_input[CONF_PASSWORD]
            if not (error := await _async_try_login(self.hass, username, password)):
                return self.async_create_entry(
                    title=username,
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, _suggest_username(user_input)
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the stored credentials were rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account's current password."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            if not (error := await _async_try_login(self.hass, username, password)):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_PASSWORD_DATA_SCHEMA,
            errors=errors,
            description_placeholders={CONF_USERNAME: username},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the credentials of an existing account, for example a new password."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            username = normalize_username(user_input[CONF_USERNAME])
            # A different email is a different account: add it as a new entry
            # instead, so its devices and history aren't mixed with this one.
            await self.async_set_unique_id(username)
            self._abort_if_unique_id_mismatch(reason="wrong_account")

            password = user_input[CONF_PASSWORD]
            if not (error := await _async_try_login(self.hass, username, password)):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_USERNAME: username, CONF_PASSWORD: password}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                _suggest_username(user_input or {CONF_USERNAME: entry.data[CONF_USERNAME]}),
            ),
            errors=errors,
        )
