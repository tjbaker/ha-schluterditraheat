# Local Development with Docker

`docker-compose.yml` runs a Home Assistant container (same version as the
test suite) with this integration mounted read-only, so you can try changes
against your real thermostat.

## Quick start

```bash
docker compose up -d
```

1. Open http://localhost:8124. Port 8124 is used so this can run alongside
   other HA dev containers on 8123.
2. **First start only:** finish onboarding and create any user, for example
   `dev` / `dev`. After that, local browsers are logged in automatically.
3. **Settings → Devices & Services → Add Integration → Schluter DITRA-HEAT**,
   then sign in with your schluterditraheat.com credentials.

## Workflow

```bash
# Edit code under custom_components/schluterditraheat/, then:
docker compose restart

docker compose logs -f                           # all logs
docker compose logs -f | grep -i schluterditraheat

docker compose down -v && docker compose up -d   # reset everything
```

## What this config sets up

- **No login for local browsers** after onboarding, using the
  `trusted_networks` auth provider for localhost and Docker's private ranges.
- **Debug logging** for `custom_components.schluterditraheat`.
- **Recorder and Energy** enabled, so the imported consumption statistic
  can be added under **Settings → Dashboards → Energy**.
- **Fast startup:** one day of short-term history; long-term statistics are
  kept.

## Things to know

- **Sessions:** the dev instance logs in to your real Schluter account and
  counts toward its session limit. If you hit "Too many active sessions",
  stop other Home Assistant instances that use the same account, or log out
  of schluterditraheat.com in your browser.
- **Rate limits:** each restart logs in again and re-reads static data. Avoid
  restart loops; use the Refresh button entity to force a poll instead.
- **Security:** local development only. Never expose this instance or reuse
  this configuration in production.
