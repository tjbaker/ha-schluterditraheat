"""Constants for the Schluter DITRA-HEAT integration."""

from datetime import timedelta

DOMAIN = "schluterditraheat"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# API
API_BASE_URL = "https://schluterditraheat.com/api"
API_TIMEOUT = 30

# Update interval. Sinope (the RS1's backend OEM) asks integrators to poll no
# faster than 300s; polling much faster risks the frequency-based session/login
# limits. Do not exceed ~600s or the server session expires (USRSESSEXP).
#
# Source: the Neviweb community integration documents Sinope's ask
# (https://github.com/claudegel/sinope-130 — scan_interval): "Sinope asked for a
# minimum of 5 minutes between polling now so you can reduce scan_interval to
# 300. Don't go over 600, the session will expire." That integration ships an
# even more conservative 540s default.
#
# 300s means an app-side change can take up to 5 minutes to appear here. The
# per-device Refresh button (button.py) exists so users can force a poll on
# demand rather than making every install poll faster than Sinope asked.
SCAN_INTERVAL = timedelta(seconds=300)

# Energy statistics refresh interval (matches the cloud's hourly consumption buckets)
ENERGY_UPDATE_INTERVAL = timedelta(hours=1)

# Static data cache refresh (polls between full refreshes; ~1 hour at 300s interval)
STATIC_REFRESH_INTERVAL_POLLS = 12

# Rate limit backoff
RATE_LIMIT_INITIAL_BACKOFF = timedelta(minutes=2)
RATE_LIMIT_MAX_BACKOFF = timedelta(minutes=16)
RATE_LIMIT_BACKOFF_FACTOR = 2

# Maximum pause after a daily-cap (ACCDAYREQMAX) hit. The pause targets the next
# local midnight but is capped at this value so polling re-checks periodically —
# the backend's true reset boundary (UTC vs. local) is not certain.
DAILY_LIMIT_MAX_PAUSE = timedelta(hours=1)

# Proactive throttle: when the API's reported remaining budget drops to or below
# this floor, defer the next poll until the rate-limit window resets.
#
# Observed limits (authenticated session, 2026-07): the polling routes allow
# 120 requests per rolling 10-second window (x-ratelimit-reset counts down in
# seconds). That is far more headroom than the default 300s poll needs, so this
# floor is a safety net for bursts (many thermostats, retries) rather than a
# constraint hit in normal operation. Login is capped far tighter (limit 3).
RATE_LIMIT_REMAINING_FLOOR = 1

# Setpoint limits (Celsius) used when a thermostat doesn't report its own
# roomSetpointMin / roomSetpointMax
MIN_TEMP_C = 5.0
MAX_TEMP_C = 32.0

# Device info
DEFAULT_MANUFACTURER = "Schluter"
DEFAULT_MODEL = "DITRA-HEAT-E-WiFi"

# Attributes
ATTR_GROUP_NAME = "group_name"

# Modes
MODE_AUTO = "auto"
MODE_OFF = "off"
MODE_MANUAL = "manual"
MODE_FROST_SAFE = "frostProtection"

# Preset modes — only needed for modes that have no HVACMode enum equivalent.
# auto/manual/off map to HVACMode.AUTO/HEAT/OFF so HA owns those labels.
# Frost protection has no HVACMode, so it uses a plain string that must be
# declared here to avoid scattering the literal across the codebase.
PRESET_NONE = "none"
PRESET_FROST_PROTECTION = "frost_protection"

# Occupancy is separate from setpointMode: away switches the thermostat to its
# away setpoint (roomSetpointAway) and home restores the previous setpoint.
OCCUPANCY_HOME = "home"
OCCUPANCY_AWAY = "away"

# Backlight (backlightAutoDim) values an RS1 accepts, keyed by the
# option Home Assistant shows. onDemand, sensing and auto are rejected.
BACKLIGHT_OPTIONS = {"always_on": "alwaysOn", "bedroom": "bedroom", "off": "off"}

# Keypad (keyboardLock) values, as the Schluter app labels them
KEYPAD_OPTIONS = {"unlocked": "unlock", "locked": "lock"}

# Away setpoint step; the thermostat accepts values within its setpoint range
AWAY_TEMPERATURE_STEP = 0.5
