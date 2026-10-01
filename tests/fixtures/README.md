# Test fixtures

Payloads the fake HTTP session (`tests/conftest.py`) serves for the Schluter
cloud API in integration tests.

| File | Source |
|---|---|
| `attributes_rs1.json` | Recorded from a DITRA-HEAT-E-RS1 (`GET /device/{id}/attribute`). Contains no identifying data. |
| `locations.json`, `devices.json`, `groups.json`, `consumption_hourly.json` | Recorded from the same account; ids, names, the postal code and the device identifier are replaced with placeholders, and the consumption history is trimmed to three hours. |
| `location_mode.json`, `location_mode_set.json` | Recorded `GET`/`POST /location/{id}/mode` responses, ids replaced. |
| `login.json` | Reconstructed in the shape the client parses (login isn't captured by the request path). |

When the API changes, re-record `attributes_rs1.json` from the debug log
line `Raw attributes for device …` and update the snapshots
(`pytest --snapshot-update`).
