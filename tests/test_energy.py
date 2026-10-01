"""Unit tests for energy statistics helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.schluterditraheat.energy import statistic_id_for


class TestStatisticId:
    """Test external statistic id construction."""

    def test_statistic_id_format(self):
        """Test the statistic id is domain-prefixed and lowercased."""
        assert statistic_id_for("AA11BB22CC33DD44") == "schluterditraheat:energy_aa11bb22cc33dd44"

    def test_statistic_id_is_external(self):
        """Test the id uses a ':' separator (required for external statistics)."""
        assert ":" in statistic_id_for("device123")


class TestEnergyImportRespectsDailyCap:
    """The hourly energy timer must pause when the daily cap is in force.

    It runs on its own async_track_time_interval, independent of the
    coordinator's poll schedule, so it needs its own check — otherwise it keeps
    spending requests while the coordinator is paused on ACCDAYREQMAX.
    """

    @pytest.fixture
    def coordinator(self):
        """A coordinator with data and no daily cap in force."""
        coord = MagicMock()
        coord.data = {40001: {"device_id": 40001, "identifier": "aa11"}}
        coord.daily_limit_reached = False
        coord.note_daily_limit = MagicMock(return_value=1800.0)
        return coord

    async def test_skips_import_while_daily_capped(self, coordinator):
        """Test no API call is made while the cap is in force."""
        from custom_components.schluterditraheat import async_import_energy

        coordinator.daily_limit_reached = True

        with patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(),
        ) as mock_stats:
            await async_import_energy(MagicMock(), MagicMock(), coordinator)

        mock_stats.assert_not_awaited()

    async def test_imports_normally_when_not_capped(self, coordinator):
        """Test the import runs when the cap is not in force."""
        from custom_components.schluterditraheat import async_import_energy

        with patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(),
        ) as mock_stats:
            await async_import_energy(MagicMock(), MagicMock(), coordinator)

        mock_stats.assert_awaited_once()

    async def test_import_hitting_cap_pauses_coordinator(self, coordinator):
        """Test the energy path can trip the pause for the whole entry."""
        from custom_components.schluterditraheat import async_import_energy
        from custom_components.schluterditraheat.api import SchluterDailyLimitError

        with patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(side_effect=SchluterDailyLimitError("cap")),
        ):
            await async_import_energy(MagicMock(), MagicMock(), coordinator)

        coordinator.note_daily_limit.assert_called_once()

    async def test_other_errors_still_swallowed(self, coordinator):
        """Test an unrelated failure never propagates out of the timer."""
        from custom_components.schluterditraheat import async_import_energy

        with patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await async_import_energy(MagicMock(), MagicMock(), coordinator)

        coordinator.note_daily_limit.assert_not_called()


HISTORY = {
    "history": [
        {"date": "2026-09-30T10:00:00Z", "period": 264},
        {"date": "2026-09-30T11:00:00Z", "period": 132},
        {"date": "2026-09-30T12:00:00Z", "period": 0},
    ]
}
THERMOSTAT = {"device_id": 40001, "identifier": "AA11", "group_name": "Master Bath"}


class TestUpdateEnergyStatistics:
    """Test the import into long-term statistics with recorder calls mocked."""

    @pytest.fixture
    def api(self) -> MagicMock:
        """API mock whose parsing helpers are the real implementations."""
        from custom_components.schluterditraheat.api import SchluterApi

        mock = MagicMock()
        mock.get_consumption_history = AsyncMock(return_value=HISTORY)
        mock.parse_consumption_history = SchluterApi.parse_consumption_history
        mock.build_energy_statistics = SchluterApi.build_energy_statistics
        return mock

    async def _run(self, api: MagicMock, last_stats: dict, thermostats: list) -> MagicMock:
        from custom_components.schluterditraheat import energy

        recorder = MagicMock()
        recorder.async_add_executor_job = AsyncMock(return_value=last_stats)
        with (
            patch.object(energy, "get_instance", return_value=recorder),
            patch.object(energy, "async_add_external_statistics") as add_stats,
        ):
            await energy.async_update_energy_statistics(MagicMock(), api, thermostats)
        return add_stats

    async def test_first_import_metadata_and_rows(self, api: MagicMock) -> None:
        """Test a first import writes kWh rows with a running sum and mean_type NONE."""
        from homeassistant.components.recorder.models import StatisticMeanType

        add_stats = await self._run(api, {}, [THERMOSTAT])

        add_stats.assert_called_once()
        _, metadata, rows = add_stats.call_args.args
        assert metadata["statistic_id"] == "schluterditraheat:energy_aa11"
        assert metadata["name"] == "Master Bath Energy"
        assert metadata["mean_type"] is StatisticMeanType.NONE
        assert "has_mean" not in metadata
        assert metadata["has_sum"] is True
        assert metadata["unit_of_measurement"] == "kWh"
        assert metadata["unit_class"] == "energy"
        assert [(r["state"], r["sum"]) for r in rows] == [
            (0.264, 0.264),
            (0.132, pytest.approx(0.396)),
            (0.0, pytest.approx(0.396)),
        ]
        assert rows[0]["start"] == datetime(2026, 9, 30, 10, tzinfo=UTC)

    async def test_continues_from_last_recorded_bucket(self, api: MagicMock) -> None:
        """Test a re-import re-emits from the last bucket and keeps the sum continuous."""
        last_start = datetime(2026, 9, 30, 11, tzinfo=UTC).timestamp()
        last_stats = {
            "schluterditraheat:energy_aa11": [{"start": last_start, "sum": 5.1, "state": 0.1}]
        }

        add_stats = await self._run(api, last_stats, [THERMOSTAT])

        rows = add_stats.call_args.args[2]
        assert [r["start"].hour for r in rows] == [11, 12]
        # 5.1 total included a partial 0.1 for the 11:00 bucket; it is now 0.132.
        assert rows[0]["sum"] == pytest.approx(5.132)
        assert rows[1]["sum"] == pytest.approx(5.132)

    async def test_history_error_skips_device(self, api: MagicMock) -> None:
        """Test an API error is logged and skipped rather than raised."""
        from custom_components.schluterditraheat.api import SchluterApiError

        api.get_consumption_history = AsyncMock(side_effect=SchluterApiError("boom"))

        add_stats = await self._run(api, {}, [THERMOSTAT])

        add_stats.assert_not_called()

    async def test_device_without_identifier_is_skipped(self, api: MagicMock) -> None:
        """Test thermostats missing an identifier are ignored."""
        add_stats = await self._run(api, {}, [{"device_id": 40001}])

        api.get_consumption_history.assert_not_awaited()
        add_stats.assert_not_called()
