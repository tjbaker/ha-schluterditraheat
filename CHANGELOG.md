# Changelog

## [2.2.0](https://github.com/tjbaker/ha-schluterditraheat/compare/2.1.0...2.2.0) (2026-10-01)


### Features

* add an Away preset ([#21](https://github.com/tjbaker/ha-schluterditraheat/issues/21)) ([9d3e457](https://github.com/tjbaker/ha-schluterditraheat/commit/9d3e45780f31a5f73fa1aa6b5bdff302f934baf6))
* add Child lock and Early start switches ([#20](https://github.com/tjbaker/ha-schluterditraheat/issues/20)) ([5eaa73b](https://github.com/tjbaker/ha-schluterditraheat/commit/5eaa73b8ade73761d4136f15decc1e3e10734604))
* add Keypad, Backlight and Away setpoint settings ([#24](https://github.com/tjbaker/ha-schluterditraheat/issues/24)) ([6888230](https://github.com/tjbaker/ha-schluterditraheat/commit/688823054c457d88c6f37dcdab590c94a5171270))
* add Spanish and French translations ([a0e284d](https://github.com/tjbaker/ha-schluterditraheat/commit/a0e284d71ab9e25fdf37dd56e2e766536027f736))
* add whole-home Home/Away and a thermostat fault sensor ([#22](https://github.com/tjbaker/ha-schluterditraheat/issues/22)) ([0e1dcfc](https://github.com/tjbaker/ha-schluterditraheat/commit/0e1dcfc1221c992ccacea6395c32814454657489))
* backfill a month of energy history and add an electricity price sensor ([#19](https://github.com/tjbaker/ha-schluterditraheat/issues/19)) ([eb9751e](https://github.com/tjbaker/ha-schluterditraheat/commit/eb9751e2a78f59af8f9cff0fe4bb5699874b7cac))
* show a repair issue while the account is at its session cap ([#17](https://github.com/tjbaker/ha-schluterditraheat/issues/17)) ([ee3287b](https://github.com/tjbaker/ha-schluterditraheat/commit/ee3287b3e4f3dbb9d198a076c47e03668fc9698b))


### Bug Fixes

* report preset-mode failures as Home Assistant errors ([4412f58](https://github.com/tjbaker/ha-schluterditraheat/commit/4412f584ee49edefbb96b87215aa473dfead8c95))
* stop exposing the serial number and location in climate attributes ([77aa425](https://github.com/tjbaker/ha-schluterditraheat/commit/77aa425e039c61c11b697c5d4a18e0f92c5f7865))


### Code Refactoring

* keep the coordinator in entry.runtime_data ([#15](https://github.com/tjbaker/ha-schluterditraheat/issues/15)) ([30b3d32](https://github.com/tjbaker/ha-schluterditraheat/commit/30b3d320a123909041f59a6ed8cffe56d91ae430))

## [2.1.0](https://github.com/tjbaker/ha-schluterditraheat/compare/2.0.0...2.1.0) (2026-10-01)

### Features

* **Reconfigure:** update the saved Schluter password from **Settings → Devices & Services → Schluter DITRA-HEAT → ⋮ → Reconfigure**, without removing the integration ([#13](https://github.com/tjbaker/ha-schluterditraheat/issues/13))

### Bug Fixes

* **The setup dialog shows its text again:** it had no title, field labels or readable error messages because the integration shipped without translations ([#13](https://github.com/tjbaker/ha-schluterditraheat/issues/13))
* **Setup retries after an outage:** if Schluter's cloud or your network is unreachable when Home Assistant starts, the integration retries automatically instead of staying failed until reloaded ([#13](https://github.com/tjbaker/ha-schluterditraheat/issues/13))
* **The setpoint range comes from the thermostat:** setpoints above 32 °C now work on thermostats configured for warmer floors (upstream [#7](https://github.com/KevinFarrell/ha-schluterditraheat/issues/7)) ([#8](https://github.com/tjbaker/ha-schluterditraheat/issues/8))
* Re-entering your password names the account it's for, and adding an account that's already set up no longer signs in to Schluter ([#13](https://github.com/tjbaker/ha-schluterditraheat/issues/13))

## [2.0.0](https://github.com/tjbaker/ha-schluterditraheat/compare/8646962...2.0.0) (2026-10-01)

First release of the maintained fork of [KevinFarrell/ha-schluterditraheat](https://github.com/KevinFarrell/ha-schluterditraheat). It brings in the community pull requests that were waiting upstream, plus fixes found by testing on a DITRA-HEAT-E-RS1.

### Upgrade notes

* **Home Assistant 2026.9 or later is required.** HACS won't offer this update on older versions.
* **Switching from the upstream repo:** in HACS, replace the custom repository with `https://github.com/tjbaker/ha-schluterditraheat` and update. The integration domain and existing entity IDs are unchanged, so your automations and history carry over.
* **The default poll interval is now 5 minutes**, up from 60 seconds, at the cloud operator's (Sinopé's) request. Use the new **Refresh** button when you want current state immediately.

### Features

* **Energy dashboard:** hourly consumption is imported into long-term statistics, plus a **Power** sensor for live draw ([#4](https://github.com/KevinFarrell/ha-schluterditraheat/pull/4), @deviantintegral)
* **Refresh** button, and rate limiting driven by the cloud's response headers and error codes, including a pause when the daily request cap is reached ([#5](https://github.com/KevinFarrell/ha-schluterditraheat/pull/5), @deviantintegral)
* **Wi-Fi signal** sensor, plus model, firmware and hardware version on the device page ([#6](https://github.com/KevinFarrell/ha-schluterditraheat/pull/6), @deviantintegral)
* **Frost protection** preset ([#3](https://github.com/KevinFarrell/ha-schluterditraheat/pull/3), @mszilagyi)
* **Diagnostics** download with a health check that flags rate limits, session-limit errors, weak Wi-Fi, GFCI faults and offline thermostats ([#4](https://github.com/tjbaker/ha-schluterditraheat/issues/4)) ([26826d6](https://github.com/tjbaker/ha-schluterditraheat/commit/26826d6a27145595523e348abaa387353820a6f2))

### Bug Fixes

* **Heat mode turns the floor on again:** manual mode now sends `manual` instead of `autoBypass` (upstream issues [#2](https://github.com/KevinFarrell/ha-schluterditraheat/issues/2) and [#8](https://github.com/KevinFarrell/ha-schluterditraheat/issues/8); [#3](https://github.com/KevinFarrell/ha-schluterditraheat/pull/3), @mszilagyi)
* **No more "Too many active sessions" after restarts:** sessions are now logged out on shutdown, reload and failed setup, and hitting the session cap retries instead of asking for your password again ([#7](https://github.com/tjbaker/ha-schluterditraheat/issues/7)) ([584ed31](https://github.com/tjbaker/ha-schluterditraheat/commit/584ed3177428635fe17182ddd965d73d991b695f))
* The energy import pauses while the daily request cap is in force ([feb3baf](https://github.com/tjbaker/ha-schluterditraheat/commit/feb3bafd2e0bfa17bd0691781c6784727622f23b), @deviantintegral)
* The Power sensor reports the full load while heating rather than load × percentage, which matches how the heating cable actually switches ([b56c326](https://github.com/tjbaker/ha-schluterditraheat/commit/b56c326b56987b13b6746c5c0542087418f08a15), @deviantintegral)
* Energy statistics declare `mean_type` and `unit_class`, as Home Assistant requires from 2026.11 ([83be346](https://github.com/tjbaker/ha-schluterditraheat/commit/83be346a7a064ef8a2f73ad9dcc9461a80db7eb1), [35519b9](https://github.com/tjbaker/ha-schluterditraheat/commit/35519b9735655ee902ce54bdd578d9e0bd9a1a7a), @deviantintegral)
* Removed the deprecated `async-timeout` dependency
