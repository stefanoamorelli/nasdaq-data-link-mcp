"""Live checks of the carbon removal (Puro.earth CORC) tools.

About 11 API calls: one metadata read per table and tool call, one data read
per tool call, plus one facility-directory read when a call filters by facility.
The six free BUWP tables are refreshed daily; NDAQ/TRAN is premium.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import API_KEY_ENV, Settings
from nasdaq_data_link_mcp_os.server import create_server
from tests.conftest import error_text, payload

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get(API_KEY_ENV), reason=f"{API_KEY_ENV} unset"),
]

DATA = "ndl_get_carbon_removal_data"


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with Client(create_server(Settings.from_env())) as connected:
        yield connected


def _column(data: dict[str, Any], name: str) -> list[Any]:
    index = [c["name"] for c in data["columns"]].index(name)
    return [row[index] for row in data["rows"]]


def _recent(days: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=days)).isoformat()


async def test_live_facilities_by_country(client: Client) -> None:
    args = {"country": "finland", "methodology": "Biochar"}
    data = payload(await client.call_tool("ndl_get_carbon_removal_facilities", args))
    assert (data["table"], data["access"]) == ("NDAQ/FAFD", "free")
    assert data["rows"], "Puro.earth lists biochar facilities in Finland"
    assert set(_column(data, "country")) == {"Finland"}
    assert all(m.startswith("Biochar") for m in _column(data, "methodology"))
    assert data["refreshed_at"] >= _recent(14)


async def test_live_transactions_of_one_facility_id(client: Client) -> None:
    args = {"dataset": "transactions", "facilities": "353054", "start_date": "2026"}
    data = payload(await client.call_tool(DATA, args))
    assert data["table"] == "NDAQ/COLT"
    assert data["request"]["facility_id"] == "353054"
    assert data["matched_facilities"][0]["facility"] == "Gevo North Dakota"
    assert set(_column(data, "facility_id")) == {"353054"}
    dates = _column(data, "date")
    assert dates and dates == sorted(dates, reverse=True)
    assert dates[-1] >= "2026-01-01"


async def test_live_volumes_and_retirements_newest_first(client: Client) -> None:
    volumes = payload(
        await client.call_tool(
            DATA,
            {
                "dataset": "facility_volumes",
                "methodology": "Biochar",
                "durability_category": "CORC 100+",
                "start_date": "2025",
                "end_date": "2025",
                "limit": 10,
            },
        )
    )
    assert set(_column(volumes, "year")) == {2025}
    assert set(_column(volumes, "durability_category")) == {"CORC 100+"}
    net = _column(volumes, "volume_issued_net_vintage")
    assert net == sorted(net, reverse=True) and net[0] > 1000

    newest = payload(
        await client.call_tool(DATA, {"dataset": "retirements", "limit": 5})
    )
    dates = _column(newest, "date")
    assert dates == sorted(dates, reverse=True)
    assert dates[0] >= _recent(90), "the CORC tables are refreshed daily"
    assert newest["has_more"] is True


async def test_live_reference_prices_need_a_subscription(client: Client) -> None:
    args = {"dataset": "reference_prices", "start_date": "2025-02-15"}
    text = error_text(await client.call_tool(DATA, args))
    assert "[SUBSCRIPTION]" in text and "NDAQ/TRAN" in text
