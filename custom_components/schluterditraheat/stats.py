"""Runtime counters for diagnostics.

Small, dependency-free records the API client, coordinator and energy import
update as they run. They exist only to make the diagnostics download useful
when someone reports a problem; nothing reads them to make decisions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def describe_error(err: BaseException) -> dict[str, str]:
    """Type and message of an error, preferring the API error that caused it."""
    cause = err.__cause__ or err
    return {"type": type(cause).__name__, "message": str(cause), "at": _utcnow_iso()}


@dataclass
class ApiStats:
    """HTTP activity of one SchluterApi client since setup."""

    requests: int = 0
    logins: int = 0
    reauthentications: int = 0
    last_login: str | None = None

    def note_request(self) -> None:
        self.requests += 1

    def note_login(self) -> None:
        self.logins += 1
        self.last_login = _utcnow_iso()

    def note_reauthentication(self) -> None:
        self.reauthentications += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "logins": self.logins,
            "reauthentications": self.reauthentications,
            "last_login": self.last_login,
        }


@dataclass
class PollStats:
    """Outcome history of the coordinator's polls since setup."""

    polls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    failures_by_type: Counter[str] = field(default_factory=Counter)
    last_poll_started: str | None = None
    last_poll_duration_ms: float | None = None
    last_success: str | None = None
    last_failure: dict[str, str] | None = None
    last_static_refresh: str | None = None
    devices_missing_last_poll: list[int] = field(default_factory=list)

    def note_start(self) -> None:
        self.polls += 1
        self.last_poll_started = _utcnow_iso()

    def note_success(self, duration_ms: float, missing: list[int]) -> None:
        self.last_poll_duration_ms = round(duration_ms, 1)
        self.last_success = _utcnow_iso()
        self.consecutive_failures = 0
        self.devices_missing_last_poll = missing

    def note_failure(self, duration_ms: float, err: BaseException) -> None:
        self.last_poll_duration_ms = round(duration_ms, 1)
        self.failures += 1
        self.consecutive_failures += 1
        self.last_failure = describe_error(err)
        self.failures_by_type[self.last_failure["type"]] += 1

    def note_static_refresh(self) -> None:
        self.last_static_refresh = _utcnow_iso()

    def as_dict(self) -> dict[str, Any]:
        return {
            "polls": self.polls,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "failures_by_type": dict(self.failures_by_type),
            "last_poll_started": self.last_poll_started,
            "last_poll_duration_ms": self.last_poll_duration_ms,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_static_refresh": self.last_static_refresh,
            "devices_missing_last_poll": self.devices_missing_last_poll,
        }


@dataclass
class EnergyStats:
    """Outcome of the hourly energy-statistics imports since setup."""

    runs: int = 0
    last_run: str | None = None
    last_skipped_reason: str | None = None
    last_error: dict[str, str] | None = None
    rows_imported: dict[str, int] = field(default_factory=dict)

    def note_skipped(self, reason: str) -> None:
        self.last_skipped_reason = reason

    def note_run(self, rows_by_statistic: dict[str, int]) -> None:
        self.runs += 1
        self.last_run = _utcnow_iso()
        self.last_skipped_reason = None
        self.rows_imported.update(rows_by_statistic)

    def note_error(self, err: BaseException) -> None:
        self.last_error = describe_error(err)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "last_run": self.last_run,
            "last_skipped_reason": self.last_skipped_reason,
            "last_error": self.last_error,
            "rows_imported_last_run": dict(self.rows_imported),
        }
