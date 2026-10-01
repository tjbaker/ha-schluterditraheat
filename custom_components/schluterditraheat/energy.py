"""Long-term energy statistics for Schluter DITRA-HEAT.

Imports the cloud's hourly consumption history into Home Assistant's long-term
statistics so each thermostat's energy usage appears in the Energy dashboard.
One external statistic is maintained per device, sourced from this integration's
domain.

The cloud only serves a rolling window of roughly the last 24 hours of hourly
buckets, so an import can only ever recover that much history: hours missed
while Home Assistant was down for longer than the window are gone for good and
are simply absent from the cumulative sum.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import SchluterApi, SchluterApiError
from .const import DOMAIN
from .stats import EnergyStats

_LOGGER = logging.getLogger(__name__)

# Daily buckets are stamped at 12:00 UTC, so which hours a day covers depends
# on a timezone the API doesn't state. When backfilling, only use days that
# end before the hourly history starts under any offset (UTC-12 to UTC+14), so
# no energy is counted twice; at worst one boundary day is left out.
_MAX_UTC_OFFSET = timedelta(hours=14)


def statistic_id_for(identifier: str) -> str:
    """Return the external statistic id for a device identifier."""
    return f"{DOMAIN}:energy_{identifier.lower()}"


def _row_start(row: StatisticsRow) -> datetime:
    """Return a statistics row's start (a UTC timestamp) as a datetime."""
    return dt_util.utc_from_timestamp(row["start"])


async def async_update_energy_statistics(
    hass: HomeAssistant,
    api: SchluterApi,
    thermostats: list[dict[str, Any]],
    stats: EnergyStats | None = None,
) -> dict[str, int]:
    """Import hourly energy consumption into long-term statistics.

    Runs for every thermostat. A device whose history is unavailable is logged
    (and recorded in ``stats``) and skipped; it never raises, so a failure here
    cannot break the config entry or the climate poll loop.

    Returns the number of rows written per statistic id.
    """
    imported: dict[str, int] = {}
    for thermostat in thermostats:
        device_id = thermostat.get("device_id")
        identifier = thermostat.get("identifier")
        if device_id is None or not identifier:
            continue

        name = thermostat.get("group_name") or thermostat.get("name") or f"Thermostat {device_id}"
        statistic_id = statistic_id_for(identifier)

        try:
            raw = await api.get_consumption_history(device_id, "hourly")
        except SchluterApiError as err:
            _LOGGER.warning("Energy history unavailable for %s: %s", name, err)
            if stats is not None:
                stats.note_error(err)
            continue

        points = api.parse_consumption_history(raw)
        if not points:
            continue

        last_stats = await get_instance(hass).async_add_executor_job(
            get_last_statistics, hass, 1, statistic_id, True, {"sum", "state"}
        )

        last_start = None
        last_sum = 0.0
        last_state = 0.0
        if last_stats and last_stats.get(statistic_id):
            row = last_stats[statistic_id][0]
            last_sum = row.get("sum") or 0.0
            last_state = row.get("state") or 0.0
            last_start = _row_start(row)

        if last_start is None:
            # First import: prepend up to a month of daily history so the
            # Energy dashboard doesn't start nearly empty.
            points = await _with_daily_backfill(api, device_id, name, points) + points

        rows = api.build_energy_statistics(
            points,
            last_start=last_start,
            last_sum=last_sum,
            last_state=last_state,
        )
        if not rows:
            continue

        metadata: StatisticMetaData = {
            "has_sum": True,
            "mean_type": StatisticMeanType.NONE,
            "name": f"{name} Energy",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            # ``EnergyConverter.UNIT_CLASS``; a plain string, so spell the
            # literal rather than importing the converter for one constant.
            "unit_class": "energy",
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }
        statistics = [
            StatisticData(start=row["start"], state=row["state"], sum=row["sum"]) for row in rows
        ]
        async_add_external_statistics(hass, metadata, statistics)
        imported[statistic_id] = len(statistics)
        _LOGGER.debug(
            "Imported %d energy statistics rows for %s (%s)",
            len(rows),
            name,
            statistic_id,
        )

    return imported


async def _with_daily_backfill(
    api: SchluterApi,
    device_id: int,
    name: str,
    hourly: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Daily buckets that end before the hourly history begins, or [] if unavailable."""
    try:
        raw = await api.get_consumption_history(device_id, "daily")
    except SchluterApiError as err:
        _LOGGER.debug("Daily energy history unavailable for %s: %s", name, err)
        return []

    first_hourly = hourly[0][0]
    days = [
        (start, kwh)
        for start, kwh in api.parse_consumption_history(raw)
        if _day_end_upper_bound(start) <= first_hourly
    ]
    if days:
        _LOGGER.debug("Backfilling %d days of energy history for %s", len(days), name)
    return days


def _day_end_upper_bound(stamp: datetime) -> datetime:
    """Latest moment the daily bucket stamped ``stamp`` could end, in UTC."""
    midnight = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(days=1) + _MAX_UTC_OFFSET
