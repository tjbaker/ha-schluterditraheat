# Test fixtures

Payloads the fake HTTP session (`tests/conftest.py`) serves for the Schluter
cloud API in integration tests.

| File | Source |
|---|---|
| `attributes_rs1.json` | Recorded from a DITRA-HEAT-E-RS1 (`GET /device/{id}/attribute`). Contains no identifying data. |
| `login.json`, `locations.json`, `devices.json`, `groups.json` | Reconstructed in the shape the client parses; ids, names and the device identifier are placeholders. |
| `consumption_hourly.json` | Reconstructed `GET /device/{id}/consumption/hourly` response (watt-hours per hour). |

When the API changes, re-record `attributes_rs1.json` from the debug log
line `Raw attributes for device …` and update the snapshots
(`pytest --snapshot-update`).
