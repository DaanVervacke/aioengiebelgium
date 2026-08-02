"""Tests for EngieBeClient.async_get_epex_prices."""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aioresponses import aioresponses

from aioengiebelgium.client import EngieBeClient
from aioengiebelgium.const import EPEX_BASE_URL, EpexGranularity
from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeEpexNotPublishedError,
)

LoadFixture = Callable[[str], dict[str, Any]]

_TOKEN = "test-token"
_EPEX_URL = re.compile(rf"^{re.escape(EPEX_BASE_URL)}(\?.*)?$")


def _last_kwargs(m: aioresponses) -> dict[str, Any]:
    for (_method, url), calls in m.requests.items():
        if str(url).startswith(EPEX_BASE_URL):
            return cast("dict[str, Any]", calls[-1].kwargs)
    msg = "no matching request recorded"
    raise AssertionError(msg)


def _last_params(m: aioresponses) -> dict[str, str]:
    params: dict[str, str] = _last_kwargs(m)["params"]
    return params


async def test_url_and_query_params_are_utc_iso_with_z_suffix(
    load_fixture: LoadFixture,
) -> None:
    fixture = load_fixture("epex_24h.json")
    from_dt = datetime(2026, 5, 3, 22, 0, tzinfo=UTC)
    to_dt = datetime(2026, 5, 4, 22, 0, tzinfo=UTC)
    with aioresponses() as m:
        m.get(_EPEX_URL, payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            await client.async_get_epex_prices(from_dt, to_dt)

        params = _last_params(m)
    assert params["from"] == "2026-05-03T22:00:00.000Z"
    assert params["to"] == "2026-05-04T22:00:00.000Z"
    assert params["granularity"] == "HOURLY"


async def test_non_utc_datetimes_are_normalized_to_utc(
    load_fixture: LoadFixture,
) -> None:
    fixture = load_fixture("epex_24h.json")
    brussels = ZoneInfo("Europe/Brussels")
    from_dt = datetime(2026, 5, 4, 0, 0, tzinfo=brussels)
    to_dt = datetime(2026, 5, 5, 0, 0, tzinfo=brussels)
    with aioresponses() as m:
        m.get(_EPEX_URL, payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            await client.async_get_epex_prices(from_dt, to_dt)

        params = _last_params(m)
    assert params["from"] == "2026-05-03T22:00:00.000Z"
    assert params["to"] == "2026-05-04T22:00:00.000Z"


async def test_granularity_is_forwarded_as_query_param(
    load_fixture: LoadFixture,
) -> None:
    fixture = load_fixture("epex_96h.json")
    with aioresponses() as m:
        m.get(_EPEX_URL, payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            result = await client.async_get_epex_prices(
                datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
                granularity=EpexGranularity.QUARTER_HOURLY,
            )

        params = _last_params(m)
    assert params["granularity"] == "QUARTER_HOURLY"
    first_slot = result.slots[0]
    assert first_slot.end - first_slot.start == timedelta(minutes=15)


@pytest.mark.parametrize(
    ("from_dt", "to_dt"),
    [
        pytest.param(
            datetime(2026, 5, 3, 22, 0),  # noqa: DTZ001
            datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
            id="naive_from",
        ),
        pytest.param(
            datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
            datetime(2026, 5, 4, 22, 0),  # noqa: DTZ001
            id="naive_to",
        ),
    ],
)
async def test_naive_datetime_raises_value_error(
    from_dt: datetime,
    to_dt: datetime,
) -> None:
    async with aiohttp.ClientSession() as session:
        client = EngieBeClient(session, access_token=_TOKEN)
        with pytest.raises(ValueError, match="timezone-aware datetimes required"):
            await client.async_get_epex_prices(from_dt, to_dt)


async def test_works_without_authentication(
    load_fixture: LoadFixture,
) -> None:
    """The EPEX endpoint is public (verified 2026-07-31): no tokens needed."""
    fixture = load_fixture("epex_24h.json")
    with aioresponses() as m:
        m.get(_EPEX_URL, payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session)
            result = await client.async_get_epex_prices(
                datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
            )

        headers = _last_kwargs(m)["headers"]
    assert result.slots
    assert "authorization" not in {key.lower() for key in headers}
    assert headers["User-Agent"]
    assert headers["Accept"] == "application/json, application/problem+json"


async def test_tokenless_401_propagates_without_token_refresh() -> None:
    """A 401 on the public EPEX endpoint with no tokens raises at once, no refresh attempt."""
    with aioresponses() as m:
        m.get(_EPEX_URL, status=401)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session)
            with pytest.raises(EngieBeAuthenticationError):
                await client.async_get_epex_prices(
                    datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                    datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
                )
        assert all("oauth/token" not in str(url) for _method, url in m.requests)


async def test_server_error_reraises_communication_error() -> None:
    """A non-404 EPEX failure stays a communication error, not "not published"."""
    with aioresponses() as m:
        m.get(_EPEX_URL, status=500)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session)
            with pytest.raises(EngieBeCommunicationError) as excinfo:
                await client.async_get_epex_prices(
                    datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                    datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
                )
    assert not isinstance(excinfo.value, EngieBeEpexNotPublishedError)
    assert excinfo.value.status == 500


async def test_404_raises_epex_not_published_error() -> None:
    with aioresponses() as m:
        m.get(_EPEX_URL, status=404)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            with pytest.raises(EngieBeEpexNotPublishedError):
                await client.async_get_epex_prices(
                    datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                    datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
                )
