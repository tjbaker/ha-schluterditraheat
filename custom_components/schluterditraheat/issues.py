"""Repair issues shown in Settings → System → Repairs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

SESSIONS_DOCS_URL = "https://github.com/tjbaker/ha-schluterditraheat#sessions"


def _session_limit_issue_id(entry: ConfigEntry) -> str:
    return f"session_limit_{entry.entry_id}"


def async_raise_session_limit(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Tell the user the account has too many sessions and what to do about it.

    Shown rather than only logged because the fix is outside Home Assistant:
    signing out of other Schluter clients. Not fixable from the issue itself.
    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        _session_limit_issue_id(entry),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="session_limit",
        translation_placeholders={"account": entry.title},
        learn_more_url=SESSIONS_DOCS_URL,
    )


def async_clear_session_limit(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the session-limit issue once the account can sign in again."""
    ir.async_delete_issue(hass, DOMAIN, _session_limit_issue_id(entry))
