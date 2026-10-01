# AGENTS.md

Guidance for AI coding agents and human contributors working in this
repository. This is the single canonical instruction file.

## Project Overview

Custom Home Assistant integration for Schluter DITRA-HEAT Wi-Fi floor-heating
thermostats (tested on the **DITRA-HEAT-E-RS1**) that use the
schluterditraheat.com cloud. That cloud is a Schluter-branded instance of
Sinopé's Neviweb platform. There is no local API.

- **Integration domain**: `schluterditraheat`
- **IoT class**: `cloud_polling`
- **Python**: 3.14 for development and CI
- **Minimum Home Assistant**: 2026.9.0, set in `hacs.json`. Support the
  version pinned in `requirements-dev.txt` and newer only; don't add
  compatibility shims for older cores. Raise the floor along with the pin.
- **License**: MIT (no per-file license headers)
- **Origin**: maintained fork of
  [KevinFarrell/ha-schluterditraheat](https://github.com/KevinFarrell/ha-schluterditraheat).
  The `upstream` remote points there; credit upstream authors when bringing
  in their work (keep their commits, or use `Co-authored-by:` trailers).

## Compatibility Rules (do not break)

Existing users switch from the upstream repo by changing their HACS source.
To keep that seamless:

- Never change the integration domain.
- Never change existing entity `unique_id` formats (climate:
  `<identifier>`, sensor: `<identifier>_heating_output`, binary sensor:
  `<identifier>_gfci`) or device identifiers `(DOMAIN, identifier)`.
- If a change would rename entity IDs or alter state values, call it out in
  the commit body and README, and mark it as breaking (`feat!:` /
  `BREAKING CHANGE:` footer).

## Commands

```bash
make venv           # Create .venv with Python 3.14
make install        # Install requirements-dev.txt
make test           # Run all tests
make coverage       # Tests with coverage report (75%+ enforced in CI)
make lint           # Ruff
make format-check   # Black
make type-check     # mypy
make check          # All of the above
```

Single test file: `.venv/bin/pytest tests/test_api.py -v`

Local Home Assistant against a real thermostat (see `dev-config/README.md`):

```bash
make docker-up              # http://localhost:8123, integration mounted read-only
make docker-restart         # pick up code changes
make docker-logs-schluter   # follow this integration's log lines (debug is on)
make docker-down            # stop, keeping the HA config volume
make docker-reset           # wipe the HA volume and start fresh
make help                   # every target, including status, shell and pull
```

The dev instance uses a real Schluter account, so it counts toward that
account's session limit and API rate limits. Avoid restart loops.

## Architecture

| File | Responsibility |
|---|---|
| `__init__.py` | Entry setup/unload/removal, hourly energy-import timer, logout on stop; `SchluterDataUpdateCoordinator` (300s poll, hourly static refresh, per-poll location mode, rate-limit throttling, backoff and daily-cap pause) |
| `api.py` | Async aiohttp client using HA's shared session: login/logout, session reuse, one re-auth retry, rate-limit header parsing, JSON error-code mapping, device attributes, location mode, consumption history |
| `config_flow.py` | User, reauth and reconfigure steps (email/password) |
| `entity.py` | `SchluterEntity` (thermostat device) and `SchluterLocationEntity` (location service device) bases: coordinator wiring, availability, shared `device_info` |
| `climate.py` | Thermostat entity: HVAC modes, Away and Frost protection presets, setpoint range from the device, optimistic writes |
| `sensor.py` | Heating output %, power (W), Wi-Fi signal (dBm), location electricity price |
| `binary_sensor.py` | GFCI and fault-code problem sensors |
| `switch.py` | Child lock and Early start configuration switches |
| `select.py` | Location Home/Away (occupancy) and display backlight |
| `number.py` | Away temperature (`roomSetpointAway`) |
| `button.py` | Refresh button that forces an immediate poll |
| `energy.py` | Imports consumption into long-term statistics (hourly, plus a daily backfill on first import) |
| `diagnostics.py` | Redacted diagnostics download with a health analysis (issues and recommendations) |
| `issues.py` | Repairs issue for the account's session cap |
| `stats.py` | Diagnostics-only counters kept by the API client, coordinator and energy import |
| `const.py` | API URL, intervals, backoff, limits, temperature limits, mode, preset and occupancy strings |
| `strings.json` | UI text source; copied to `translations/en.json`, translated in `es.json` and `fr.json` |

Coordinator data shape: `dict[device_id, dict[str, Any]]`, merging static
device metadata with per-poll attributes. Each entity reads its own
`device_id`.

### Conventions (keep these; do not regress)

- The coordinator lives in `entry.runtime_data`, typed as
  `SchluterConfigEntry`; never store state in `hass.data`.
- Pass `config_entry=` to the coordinator.
- Entities subclass `SchluterEntity` (`entity.py`), which owns
  `device_info` and availability.
- `ConfigEntryNotReady` for transient setup failures (network, rate
  limits, the session cap), `ConfigEntryAuthFailed` only for credentials
  the API actually rejected, `UpdateFailed` during polls.
- Config flow: reauth and reconfigure use `async_update_reload_and_abort`;
  the unique ID is the lowercased email, checked before any login.
- UI text lives in `strings.json` and must be copied to
  `translations/en.json`; custom integrations only load `translations/`.
  Every string must also exist in `es.json` and `fr.json` with the same
  placeholders (tests enforce both). Entity names come from
  `_attr_translation_key`, never hardcoded `_attr_name`, except the
  climate entity, which names itself after the room.
- Diagnostics must stay redacted: never include the email, password,
  session id, tokens, full device identifiers or location names. Extend
  `diagnostics.py` and the `stats.py` counters when adding failure modes.

## Schluter / Neviweb API Notes

- Base URL `https://schluterditraheat.com/api`. Login is
  `POST /login` with `interface: "schluter"`. It returns `session`,
  `refreshToken` and `account.id`. Later calls send the `session-id` header.
- Discovery: `/locations?account$id=` → `/devices?location$id=` and
  `/groups?location$id=&type=room`.
- Read and write: `GET /device/{id}/attribute?attributes=...`,
  `PUT /device/{id}/attribute` with `{attribute: value}`.
- **Session cap**: error code `ACCSESSEXC` means the account has too many
  open sessions. Reuse one session per config entry. Never log in per poll,
  and never create throwaway API clients outside the config flow.
- **Rate limits**: HTTP 429, and a daily request cap (`ACCDAYREQMAX`).
  Sinopé asks for polling no faster than 300s. Keep request counts per poll
  minimal and back off on limits.
- Location occupancy: `GET /location/{id}/mode` returns `{"mode": "home"}`;
  `POST /location/{id}/mode` with `{"mode": "away"}` sets every thermostat
  at the location. Per thermostat, `occupancyMode` home/away switches to
  `roomSetpointAway` and back (the thermostat restores its setpoint).
- Writes confirmed on a DITRA-HEAT-E-RS1: `setpointMode`
  (auto/manual/off/frostProtection; `autoBypass` is ignored from off),
  `roomSetpoint`, `occupancyMode`, `keyboardLock` (lock/unlock),
  `earlyStartCfg` (on/off), `backlightAutoDim` (alwaysOn/bedroom/off;
  onDemand, sensing and auto are rejected), `roomSetpointAway` (within
  roomSetpointMin/Max; 4.5 °C is rejected).
- Read-only extras: `GET /device/{id}/consumption/{hourly|daily|monthly}`
  (rolling windows of ~2 days / ~1 month / months; date parameters are
  ignored), `GET /device/{id}/schedule?day=monday` (full lowercase day
  names; 8 periods of `{time, value, type}`), location `kwhCost`, and
  `errorCodeSet1` (`{"raw": n}`, 0 = no fault). An RS1 reports 31
  attributes in total; there is no outdoor temperature or humidity.
- Error codes seen: `SVCINVREQ` (unknown endpoint), `VALMISDATA` /
  `VALMISONEOF` (missing parameters), `VALINVLD` (invalid value).
- The API is undocumented. Confirm attribute names and values against a
  real device before relying on them, and record what you learned in the
  commit body. Writes to a real thermostat are run by the maintainer, not
  by an agent: provide a reversible script (read, write, read back,
  restore in `finally`) for them to run.
- Temperatures are Celsius. Some endpoints return a single object where a
  list is expected; use the `_validate_response_list` helpers.

## Code Style

- Black (line length 100) and Ruff (`E, F, I, B, UP`, known-first-party
  `custom_components`) as configured in `pyproject.toml`; mypy with
  `check_untyped_defs`.
- Fully type-annotate functions, including tests (`-> None`). Use `X | None`
  and import ABCs from `collections.abc`.
- Use builtin `TimeoutError` and `asyncio.timeout()`; never `async_timeout`.
- Catch narrow exception types; keep `try` blocks to the fallible call only.
- Magic numbers and API strings live in `const.py`.
- Comments only for non-obvious context, such as API quirks.
- Logging: DEBUG for diagnostics, INFO for notable events, WARNING for
  recoverable problems such as backoff, ERROR when the user must act. Never
  log passwords, session IDs or tokens.

## Testing

- Tests run against real Home Assistant via
  `pytest-homeassistant-custom-component` (pinned in `requirements-dev.txt`).
- No real network calls. API tests use the `mock_aiohttp` / `api_client`
  fixtures in `tests/conftest.py`, an in-process fake session with an
  aioresponses-style API:
  - Register responses with `mock_aiohttp.get/post/put(url_or_regex,
    payload=..., status=..., body=..., headers=...)`.
  - Routes are consumed in registration order; pass `repeat=True` to reuse
    one.
  - `mock_aiohttp.requests` records calls by `(METHOD, URL)`.
  - Do not reintroduce `aioresponses`; it is incompatible with the aiohttp
    version HA ships.
- Prefer testing through integration setup (`MockConfigEntry`,
  `hass.config_entries.async_setup`) and config flows through
  `hass.config_entries.flow.async_init`.
- New behavior needs tests. Coverage must stay ≥ 75%.

## Git, PRs and Releases

- Conventional Commits, subject ≤ 72 characters (commitizen pre-commit
  hook). PR titles are checked by the semantic-PR workflow.
- `fix:` → patch, `feat:` → minor, `feat!:` or a `BREAKING CHANGE:` footer
  → major. `docs/test/build/ci/chore` don't trigger a release and are hidden
  from the changelog. If a change mixes a fix with tooling, split it into a
  `fix:` commit and a `build:`/`ci:` commit.
- Write a body for non-trivial commits covering what and why, wrapped at
  ~72 characters.
- Releases are automated by release-please on `master`. It maintains a
  release PR that bumps `.release-please-manifest.json`, `manifest.json`
  `version` and `CHANGELOG.md`. Merging that PR (squash) tags `X.Y.Z` and publishes a
  GitHub release named `X.Y.Z` (never a `v` prefix), which HACS installs.
  Never hand-edit versions.
- Default branch is `master`.

## Quality Checklist (before committing)

- [ ] `make check` passes: tests, coverage ≥ 75%, ruff, black, mypy
- [ ] New behavior has tests; no real network calls
- [ ] No unique_id, device identifier or domain changes (or flagged as
      breaking)
- [ ] No new per-poll API requests without considering the rate and session
      limits
- [ ] Conventional commit subject ≤ 72 characters, with a body when
      non-trivial
