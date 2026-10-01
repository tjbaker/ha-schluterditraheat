"""Diagnostics support for Schluter DITRA-HEAT."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SchluterConfigEntry, SchluterDataUpdateCoordinator
from .const import DOMAIN, RATE_LIMIT_REMAINING_FLOOR, SCAN_INTERVAL
from .energy import statistic_id_for

TO_REDACT_ENTRY = {CONF_USERNAME, CONF_PASSWORD, "title", "unique_id"}
# location_name is user-entered and is often a street address.
TO_REDACT_DEVICE = {"location_name"}

# Wi-Fi levels, in dBm, below which a thermostat is likely to drop off the cloud.
WIFI_WEAK_DBM = -75
WIFI_VERY_WEAK_DBM = -85
# Consecutive failed polls before connectivity is reported as a problem.
FAILED_POLLS_ISSUE_THRESHOLD = 3


def _mask(identifier: str | None) -> str | None:
    """Keep enough of a device identifier to tell devices apart, hide the rest."""
    if not identifier:
        return identifier
    return f"{identifier[:4]}…" if len(identifier) > 4 else "…"


def _seconds(interval: timedelta | None) -> float | None:
    return interval.total_seconds() if interval is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SchluterConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    diagnostics: dict[str, Any] = {
        "config_entry": async_redact_data(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "version": entry.version,
                "state": entry.state.value,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT_ENTRY,
        ),
    }

    if entry.state is not ConfigEntryState.LOADED:
        diagnostics["analysis"] = {
            "health": "not_loaded",
            "issues": ["The integration is not set up; see the Home Assistant log."],
            "recommendations": [],
        }
        return diagnostics

    coordinator = entry.runtime_data
    diagnostics["api"] = _api_diagnostics(coordinator)
    diagnostics["coordinator"] = _coordinator_diagnostics(coordinator)
    diagnostics["devices"] = _device_diagnostics(coordinator)
    diagnostics["energy"] = _energy_diagnostics(coordinator)
    diagnostics["analysis"] = _analyze(coordinator)
    return diagnostics


def _api_diagnostics(coordinator: SchluterDataUpdateCoordinator) -> dict[str, Any]:
    api = coordinator.api
    rate_limit = api.rate_limit
    return {
        "authenticated": api.is_authenticated,
        "temperature_unit": api.temperature_unit,
        "rate_limit": (
            None
            if rate_limit is None
            else {
                "limit": rate_limit.limit,
                "remaining": rate_limit.remaining,
                "seconds_until_reset": rate_limit.seconds_until_reset(),
            }
        ),
        **api.stats.as_dict(),
    }


def _coordinator_diagnostics(coordinator: SchluterDataUpdateCoordinator) -> dict[str, Any]:
    exc = coordinator.last_exception
    return {
        "update_interval_seconds": _seconds(coordinator.update_interval),
        "normal_interval_seconds": _seconds(SCAN_INTERVAL),
        "backoff_interval_seconds": _seconds(coordinator._backoff_interval),
        "throttle_interval_seconds": _seconds(coordinator._throttle_interval),
        "daily_limit_reached": coordinator.daily_limit_reached,
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            None if exc is None else {"type": type(exc).__name__, "message": str(exc)}
        ),
        "polls_since_static_refresh": coordinator._polls_since_static_refresh,
        "known_devices": sorted(coordinator._static_data or {}),
        **coordinator.poll_stats.as_dict(),
    }


def _device_diagnostics(coordinator: SchluterDataUpdateCoordinator) -> dict[str, Any]:
    devices: dict[str, Any] = {}
    for device_id, thermostat in (coordinator.data or {}).items():
        device = async_redact_data(dict(thermostat), TO_REDACT_DEVICE)
        device["identifier"] = _mask(thermostat.get("identifier"))
        devices[str(device_id)] = device
    return devices


def _energy_diagnostics(coordinator: SchluterDataUpdateCoordinator) -> dict[str, Any]:
    energy = coordinator.energy_stats.as_dict()
    # Statistic ids embed the device identifier; mask them the same way.
    masks = {
        statistic_id_for(t["identifier"]): f"{DOMAIN}:energy_{_mask(t['identifier'].lower())}"
        for t in (coordinator.data or {}).values()
        if t.get("identifier")
    }
    energy["rows_imported_last_run"] = {
        masks.get(stat_id, _mask(stat_id)): rows
        for stat_id, rows in energy["rows_imported_last_run"].items()
    }
    return energy


def _analyze(coordinator: SchluterDataUpdateCoordinator) -> dict[str, Any]:
    """Summarize health with the issues found and what to do about them."""
    issues: list[str] = []
    recommendations: list[str] = []
    poll = coordinator.poll_stats
    failure_type = (poll.last_failure or {}).get("type", "")

    if coordinator.daily_limit_reached:
        issues.append("The account's daily API request cap was reached; polling is paused.")
        recommendations.append(
            "Polling resumes automatically. Reduce other clients (other Home Assistant "
            "instances, scripts) that use the same Schluter account."
        )
    elif coordinator._backoff_interval is not None:
        issues.append(f"Rate limited; polling is backed off to {coordinator._backoff_interval}.")

    rate_limit = coordinator.api.rate_limit
    if rate_limit is not None and rate_limit.is_low(RATE_LIMIT_REMAINING_FLOOR):
        issues.append(f"Rate-limit budget is nearly exhausted (remaining={rate_limit.remaining}).")

    if poll.consecutive_failures >= FAILED_POLLS_ISSUE_THRESHOLD:
        issues.append(f"The last {poll.consecutive_failures} polls failed ({failure_type}).")
        if failure_type == "SchluterConnectionError":
            recommendations.append(
                "Check that Home Assistant can reach schluterditraheat.com and "
                "that the service is up."
            )
    if failure_type == "SchluterSessionLimitError":
        issues.append("The account has too many active sessions.")
        recommendations.append(
            "Log out of schluterditraheat.com in browsers you don't use, or stop "
            "other integrations using this account, then reload the integration."
        )

    if poll.devices_missing_last_poll:
        issues.append(
            "No data in the last poll for device(s) "
            f"{', '.join(map(str, poll.devices_missing_last_poll))}."
        )
        recommendations.append(
            "Check that the thermostat has power and Wi-Fi, and that it shows as "
            "online in the Schluter app."
        )

    for device_id, thermostat in (coordinator.data or {}).items():
        label = thermostat.get("group_name") or thermostat.get("name") or device_id
        rssi = thermostat.get("rssi")
        if isinstance(rssi, int) and rssi < WIFI_WEAK_DBM:
            strength = "very weak" if rssi < WIFI_VERY_WEAK_DBM else "weak"
            issues.append(f"{label}: Wi-Fi signal is {strength} ({rssi} dBm).")
            recommendations.append(
                f"{label}: move the router or add an access point closer to the thermostat."
            )
        code = thermostat.get("error_code")
        if isinstance(code, int) and code != 0:
            issues.append(f"{label}: thermostat reports fault code {code}.")
            recommendations.append(
                f"{label}: check the thermostat's display and the Schluter app for the "
                "fault, and include the code when contacting Schluter support."
            )
        gfci = thermostat.get("gfci_status")
        if gfci is not None and gfci != "ok":
            issues.append(f"{label}: GFCI reports '{gfci}'. Heating is cut off.")
            recommendations.append(
                f"{label}: follow the thermostat's GFCI test/reset procedure; "
                "contact an electrician if it trips again."
            )

    if coordinator.energy_stats.last_error is not None:
        issues.append(
            "The last energy import reported an error "
            f"({coordinator.energy_stats.last_error['type']})."
        )

    if not coordinator.last_update_success:
        health = "failing"
    elif issues:
        health = "degraded"
    else:
        health = "healthy"

    return {"health": health, "issues": issues, "recommendations": recommendations}
