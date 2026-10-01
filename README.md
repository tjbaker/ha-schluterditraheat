# Schluter DITRA-HEAT

A custom [Home Assistant](https://www.home-assistant.io/) integration for [Schluter DITRA-HEAT](https://www.schluter.com/schluter-us/en_US/ditra-heat) WiFi floor heating thermostats that use the [schluterditraheat.com](https://schluterditraheat.com) cloud service.

This is a maintained fork of [KevinFarrell/ha-schluterditraheat](https://github.com/KevinFarrell/ha-schluterditraheat), which it extends with fixes and features contributed upstream. It keeps the same integration domain and entity IDs, so existing installs can switch over without reconfiguring.

## Compatibility

Schluter has multiple apps and cloud platforms for different product lines. This integration works with thermostats managed through the **Schluter Smart Thermostat** app and [schluterditraheat.com](https://schluterditraheat.com) — **not** the older Schluter DITRA-HEAT app or other Schluter platforms. If you can log in at [schluterditraheat.com](https://schluterditraheat.com) with your credentials, this integration should work for you.

Tested with the **DITRA-HEAT-E-RS1** thermostat. Other models using the same cloud service should work but have not been verified. If you encounter issues with a different model, please [open an issue](https://github.com/tjbaker/ha-schluterditraheat/issues).

## Features

- **Thermostat control** — set the temperature, mode (Auto, Heat, Off) and presets (Away, Frost protection) for each thermostat
- **Home/Away for the whole home** — switch every thermostat at a location between Home and Away at once, like the Schluter app; useful with presence detection
- **Energy dashboard** — consumption imported into long-term statistics, backfilled with about a month of history on first setup, plus the electricity price from the Schluter app for cost tracking
- **Live readings** — heating output, power draw and Wi-Fi signal
- **Safety** — GFCI and thermostat fault sensors
- **Thermostat settings** — Child lock and Early start
- **Device metadata** — model, firmware and hardware version, and serial number on the device page
- **Diagnostics and repairs** — a redacted diagnostics download with a health check, and a Repairs notice when the account hits its session limit
- **Languages** — English, Spanish and French

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/tjbaker/ha-schluterditraheat` with category **Integration**
4. Search for "Schluter DITRA-HEAT" and install
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** and search for "Schluter DITRA-HEAT"

### Manual

1. Copy the `custom_components/schluterditraheat/` directory to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration** and search for "Schluter DITRA-HEAT"

## Configuration

Enter your [schluterditraheat.com](https://schluterditraheat.com) account credentials when prompted. All thermostats on your account are discovered automatically.

To change the saved password later (for example after changing it in the Schluter app), use **Settings → Devices & Services → Schluter DITRA-HEAT → ⋮ → Reconfigure**. If Schluter rejects the saved password, Home Assistant asks for the new one.

**Note:** Adding or removing thermostats from your Schluter account requires reloading the integration in Home Assistant.

## Entities

### Thermostat device

Each thermostat appears as a device named after its room:

| Entity | Type | Description |
|--------|------|-------------|
| Floor Heat | Climate | Temperature, mode and presets (see below) |
| Heating Output | Sensor | Current heating output percentage (0–100%) |
| Power | Sensor | Instantaneous power draw in watts — full connected load while heating, 0 when idle (the cable switches on and off rather than modulating) |
| GFCI Status | Binary sensor | Ground fault detection (problem) |
| Fault | Binary sensor | On when the thermostat reports a fault; the raw code is in the `error_code` attribute (problem) |
| Wi-Fi Signal | Sensor | Signal strength in dBm (diagnostic) |
| Refresh | Button | Poll the cloud now instead of waiting for the next scheduled poll |
| Child lock | Switch | Locks the thermostat's touchscreen (configuration) |
| Early start | Switch | Heats ahead of schedule changes so the floor is at temperature on time (configuration) |

The Fault, Wi-Fi, Child lock and Early start entities are only created when the thermostat reports them.

**Modes:** *Auto* follows the schedule set in the Schluter app, *Heat* holds the temperature you set, and *Off* turns the floor off. The setpoint range comes from the thermostat (5–32 °C by default).

**Presets:**
- *Away* switches the thermostat to the away temperature set in the Schluter app; choosing *None* restores the previous temperature.
- *Frost protection* keeps the floor just warm enough to prevent freezing.
- Only one preset is active at a time. Leaving *Away* never turns heating on by itself.

The Wi-Fi reading is the raw dBm value; the Schluter app shows the same reading as a five-level scale.

### Location device

Each home (location) in the Schluter app appears as a separate device:

| Entity | Type | Description |
|--------|------|-------------|
| Occupancy | Select | Home or Away for every thermostat at the location, the same as the Schluter app's mode |
| Electricity price | Sensor | Price per kWh set for the location in the Schluter app; only created when a price is set |

### Energy

Each thermostat's hourly energy consumption is imported into Home Assistant's long-term statistics (as an external statistic, in kWh) so it can be added to the **Energy dashboard**. The statistic refreshes hourly. On first setup it's backfilled from what the cloud still holds: about the last two days hour by hour, and roughly the month before that as one value per day. Older usage isn't available. The day where the daily and hourly history meet may be left out, so energy is never counted twice. Installs that already have this statistic aren't backfilled, because inserting older rows would corrupt the existing totals.

Add it via **Settings → Dashboards → Energy → Add consumption**, where it is listed as `Schluter DITRA-HEAT` energy for each thermostat. To show cost, edit that entry, choose **Use an entity with current price**, and pick the **Electricity price** sensor.

> **Note:** The thermostat reports energy per hour, not a continuously increasing meter reading, so energy appears as an Energy-dashboard statistic rather than a regular sensor entity.

> **Use the imported statistic for energy, not the Power sensor.** The imported consumption is the accurate energy figure and the one to add to the Energy dashboard. Do **not** build energy from the Power sensor (for example with a Riemann-sum integration helper): the thermostat is polled every five minutes while the heating cable switches on and off on a much faster cycle, so an integration of those sparse samples will not match actual usage. The Power sensor is meant for live power draw and automations, not energy totals.

## Polling and rate limits

The thermostat's cloud backend enforces request limits and publishes its remaining budget in `X-RateLimit-*` response headers on every call. This integration:

- Polls every **300 seconds** by default, the minimum cadence the backend's OEM (Sinopé) asks integrators to respect. (Static data such as device lists is refreshed roughly hourly; the fast path only fetches thermostat state.)
- Reads the rate-limit headers on every response and **defers the next poll** automatically when the remaining budget runs low, resuming normal cadence once it recovers.
- Recognizes the backend's JSON error codes (which it returns instead of HTTP 429): a daily-cap hit (`ACCDAYREQMAX`) pauses polling until midnight, an expired session (`USRSESSEXP`) re-authenticates transparently, and login/session limits are surfaced clearly.

### Sessions

Your Schluter account allows a limited number of logged-in sessions at once, shared by the Schluter app, the website and this integration. The integration keeps a single session and logs it out when Home Assistant stops or the integration is reloaded or removed. If the account still reports too many sessions, the integration retries setup on its own rather than asking for your password again. Signing out of schluterditraheat.com in browsers you no longer use frees sessions sooner.

Because the scheduled poll is 300 seconds, a change made on the thermostat itself or in the Schluter phone app can take up to five minutes to appear in Home Assistant. Rather than make every installation poll faster than Sinopé asks, each thermostat exposes a **Refresh** button that forces an immediate poll — press it (or call `button.press` from an automation) when you want state right now. One press refreshes every thermostat on the account, and rapid presses are coalesced so the button cannot be used to hammer the API.

## Troubleshooting

Go to **Settings → Devices & Services → Schluter DITRA-HEAT → ⋮ → Download diagnostics**. The file's `analysis` section lists any problems found and what to do about them. Your email, password, session tokens, device serial numbers and location names are removed, so you can attach it to an issue.

For more detail, enable debug logging:

```yaml
logger:
  logs:
    custom_components.schluterditraheat: debug
```

## Limitations

This integration supports monitoring and basic control. The following are **not** currently supported:

- Managing or editing heating schedules (schedules configured in the Schluter app are respected in Auto mode)
- Changing the air/floor sensor mode
- Firmware updates
- Adding or removing thermostats (requires reloading the integration)
- Recovering energy history older than the cloud's rolling window — it serves only about the last two days of hourly consumption, so if Home Assistant is offline for longer than that, the missed hours are lost and are simply absent from the Energy dashboard's totals

## Development

See [AGENTS.md](AGENTS.md) for project conventions and `make` targets, and [dev-config/README.md](dev-config/README.md) for running a local Home Assistant in Docker against your own thermostat.

## Disclaimer

This project is not affiliated with, endorsed by, or associated with Schluter Systems. It uses the existing schluterditraheat.com web APIs, which are undocumented and may change at any time. If the APIs change, this integration may break until it is updated.

## Requirements

- **Home Assistant 2026.9 or later.** This is the version the test suite and dev container run against; HACS will not offer updates on older versions.
- **A thermostat on the Schluter Smart Thermostat platform**, such as the DITRA-HEAT-E-RS1, and its [schluterditraheat.com](https://schluterditraheat.com) login (the same one the app uses). See [Compatibility](#compatibility).
- **Internet access.** The integration only talks to Schluter's cloud; there is no local control.
- **The Recorder integration** (enabled by default) for the Energy dashboard statistics.
- **HACS**, if installing through HACS rather than manually.

## Credits

Originally written by [@KevinFarrell](https://github.com/KevinFarrell). Thanks also to the contributors whose upstream pull requests are included here.
