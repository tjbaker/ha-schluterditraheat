"""Shared pytest fixtures for the Schluter DITRA-HEAT tests.

Tests run against the real Home Assistant package via
pytest-homeassistant-custom-component. HTTP traffic is faked with a small
in-process session (see ``MockSession``) because aioresponses is not
compatible with the aiohttp release Home Assistant ships.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import pytest
from multidict import CIMultiDict
from yarl import URL

# Ensure the repo root is importable so `custom_components.schluterditraheat`
# resolves to this checkout.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pre-import custom_components as a namespace package anchored to this repo.
# HA's loader temporarily puts its testing_config (which ships a regular
# custom_components package) on sys.path; importing first keeps ours visible.
import custom_components  # noqa: E402,F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the integration under test."""
    yield


@pytest.fixture
def recorder_loaded(hass):
    """Satisfy the integration's recorder dependency without a database.

    For tests that set up or reload a config entry with the energy import
    patched out; tests of the statistics import itself mock the recorder.
    """
    hass.config.components.add("recorder")


@dataclass
class _MockRoute:
    """A single registered response, consumed by the first matching request."""

    method: str
    url: str | re.Pattern[str]
    status: int = 200
    payload: Any = None
    body: str | bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    exception: BaseException | None = None
    repeat: bool = False

    def matches(self, method: str, url: URL) -> bool:
        if method != self.method:
            return False
        if isinstance(self.url, re.Pattern):
            return self.url.match(str(url)) is not None
        return URL(self.url) == url


@dataclass
class _MockCall:
    """Arguments of a request seen by the mock session."""

    kwargs: dict[str, Any]


class _MockResponse:
    """Minimal stand-in for aiohttp.ClientResponse."""

    def __init__(self, route: _MockRoute) -> None:
        self.status = route.status
        self.headers = CIMultiDict(route.headers)
        if route.payload is not None:
            self._body = json.dumps(route.payload).encode()
        elif isinstance(route.body, str):
            self._body = route.body.encode()
        else:
            self._body = route.body or b""

    async def text(self) -> str:
        return self._body.decode()

    async def json(self, **_: Any) -> Any:
        return json.loads(self._body)

    async def __aenter__(self) -> _MockResponse:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _RequestContext:
    """Awaitable/async-context wrapper mirroring aiohttp's request API."""

    def __init__(self, session: MockSession, method: str, url: str, kwargs: dict) -> None:
        self._session = session
        self._method = method
        self._url = url
        self._kwargs = kwargs

    async def __aenter__(self) -> _MockResponse:
        return self._session._dispatch(self._method, self._url, self._kwargs)

    async def __aexit__(self, *_: Any) -> None:
        return None


class MockSession:
    """In-process fake of aiohttp.ClientSession with an aioresponses-like API.

    Register responses with ``get``/``post``/``put`` (``payload=``,
    ``status=``, ``body=``, ``headers=``, ``exception=``, ``repeat=``); routes
    are consumed in registration order. Issue requests with ``request`` or
    the ``session_*`` helpers; ``requests`` records calls keyed by
    ``(METHOD, URL)``.
    """

    def __init__(self) -> None:
        self._routes: list[_MockRoute] = []
        self.requests: dict[tuple[str, URL], list[_MockCall]] = defaultdict(list)

    # Registration API (mirrors aioresponses).
    def _add(self, method: str, url: str | re.Pattern[str], **kwargs: Any) -> None:
        self._routes.append(_MockRoute(method=method, url=url, **kwargs))

    def get(self, url: str | re.Pattern[str], **kwargs: Any) -> None:
        self._add("GET", url, **kwargs)

    def post(self, url: str | re.Pattern[str], **kwargs: Any) -> None:
        self._add("POST", url, **kwargs)

    def put(self, url: str | re.Pattern[str], **kwargs: Any) -> None:
        self._add("PUT", url, **kwargs)

    def fail_next(self, method: str, url: str | re.Pattern[str], **kwargs: Any) -> None:
        """Answer the next matching request with this response, ahead of other routes."""
        self._routes.insert(0, _MockRoute(method=method, url=url, **kwargs))

    # Request dispatch.
    def _dispatch(self, method: str, url: str, kwargs: dict) -> _MockResponse:
        request_url = URL(url)
        self.requests[(method, request_url)].append(_MockCall(kwargs))
        for index, route in enumerate(self._routes):
            if route.matches(method, request_url):
                if not route.repeat:
                    del self._routes[index]
                if route.exception is not None:
                    raise route.exception
                return _MockResponse(route)
        raise aiohttp.ClientConnectionError(f"No mock registered for {method} {url}")


class _SessionView:
    """The object handed to SchluterApi: request methods only."""

    def __init__(self, mock: MockSession) -> None:
        self._mock = mock

    def request(self, method: str, url: str, **kwargs: Any) -> _RequestContext:
        return _RequestContext(self._mock, method.upper(), url, kwargs)

    def get(self, url: str, **kwargs: Any) -> _RequestContext:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _RequestContext:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> _RequestContext:
        return self.request("PUT", url, **kwargs)


@pytest.fixture
def mock_aiohttp() -> MockSession:
    """Response registry for the fake HTTP session."""
    return MockSession()


@pytest.fixture
def mock_session(mock_aiohttp: MockSession) -> _SessionView:
    """Fake aiohttp session backed by ``mock_aiohttp``."""
    return _SessionView(mock_aiohttp)


@pytest.fixture
def api_client(mock_session: _SessionView):
    """SchluterApi wired to the fake session."""
    from custom_components.schluterditraheat.api import SchluterApi

    return SchluterApi(mock_session, "test@example.com", "password123")


FIXTURES = ROOT / "tests" / "fixtures"
DEVICE_ID = 995001


def load_fixture(name: str) -> Any:
    """Load a JSON payload from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def mock_cloud(mock_aiohttp: MockSession) -> MockSession:
    """Serve one RS1 thermostat from recorded/reconstructed cloud payloads.

    Routes repeat, so polls, refreshes and reloads keep working; tests can
    register earlier, non-repeating routes to inject failures.
    """
    from custom_components.schluterditraheat.const import API_BASE_URL

    base = re.escape(API_BASE_URL)
    routes = {
        ("POST", rf"{base}/login$"): "login.json",
        ("GET", rf"{base}/locations\?.*"): "locations.json",
        ("GET", rf"{base}/devices\?.*"): "devices.json",
        ("GET", rf"{base}/groups\?.*"): "groups.json",
        ("GET", rf"{base}/device/{DEVICE_ID}/attribute\?.*"): "attributes_rs1.json",
        ("GET", rf"{base}/device/{DEVICE_ID}/consumption/hourly$"): "consumption_hourly.json",
    }
    for (method, pattern), name in routes.items():
        mock_aiohttp._add(method, re.compile(pattern), payload=load_fixture(name), repeat=True)
    mock_aiohttp.put(re.compile(rf"{base}/device/{DEVICE_ID}/attribute$"), payload={}, repeat=True)
    mock_aiohttp.get(re.compile(rf"{base}/logout$"), payload={}, repeat=True)
    return mock_aiohttp


@pytest.fixture
async def init_integration(hass, mock_cloud: MockSession, mock_session, recorder_loaded):
    """Set the integration up through Home Assistant against the fake cloud.

    Uses the real API client, coordinator and platforms; only HTTP is faked
    and the energy-statistics import (which needs a database) is skipped.
    """
    from unittest.mock import AsyncMock, patch

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.schluterditraheat.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="owner@example.com",
        unique_id="owner@example.com",
        data={"username": "owner@example.com", "password": "hunter2"},
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.schluterditraheat.async_get_clientsession",
            return_value=mock_session,
        ),
        patch(
            "custom_components.schluterditraheat.async_update_energy_statistics",
            new=AsyncMock(return_value={}),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


@pytest.fixture
def snapshot(snapshot):
    """Snapshots with Home Assistant's serializer (stable ids and timestamps).

    pytest-homeassistant-custom-component defines the same override, but
    syrupy's own fixture can win depending on plugin load order.
    """
    from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension

    return snapshot.use_extension(HomeAssistantSnapshotExtension)
