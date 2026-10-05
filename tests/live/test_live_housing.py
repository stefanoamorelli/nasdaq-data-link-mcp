"""Live checks of the Zillow housing tools (ZILLOW/DATA, REGIONS, INDICATORS).

About 9 API calls: one per region search, one ZILLOW/INDICATORS read per
server, and per data call one ZILLOW/REGIONS id lookup and one ZILLOW/DATA read
(plus one metadata read per server).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
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


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with Client(create_server(Settings.from_env())) as connected:
        yield connected


async def _call(client: Client, tool: str, **args: Any) -> dict[str, Any]:
    return payload(await client.call_tool(tool, args))


async def test_search_regions(client: Client) -> None:
    austin = await _call(client, "ndl_search_zillow_regions", query="Austin, TX")
    assert [(r["region_id"], r["match"]) for r in austin["results"]] == [
        ("394355", "exact"),
        ("10221", "exact"),
    ]
    assert austin["results"][1]["parents"] == [
        "Austin-Round Rock-Georgetown, TX",
        "Travis County",
    ]
    zip_code = await _call(client, "ndl_search_zillow_regions", query="94110")
    assert [(r["region_id"], r["name"]) for r in zip_code["results"]] == [
        ("97565", "94110")
    ]


async def test_search_indicators(client: Client) -> None:
    listed = await _call(client, "ndl_search_zillow_indicators")
    by_id = {i["indicator_id"]: i for i in listed["indicators"]}
    assert listed["result_count"] == len(by_id) == 56
    counts: dict[str, int] = {}
    for indicator in by_id.values():
        counts[indicator["category"]] = counts.get(indicator["category"], 0) + 1
    assert counts == {"Home values": 10, "Rentals": 2, "Inventory and sales": 44}
    assert by_id["RSNA"]["region_types"] == ["metro", "zip"]
    assert by_id["SSAW"]["frequency"] == "weekly"


async def test_get_zillow_data(client: Client) -> None:
    values = await _call(
        client,
        "ndl_get_zillow_data",
        indicator="ZALL",
        regions=["10221", "102001"],
        limit=12,
    )
    assert values["access"] == "free"
    assert values["refreshed_at"].startswith("2025-07")
    city, us = values["series"]
    assert (city["region_type"], city["region"]) == ("city", "Austin, TX")
    assert (city["available_to"], us["available_to"]) == ("2025-06-30", "2025-01-31")
    dates = [row[0] for row in values["rows"]]
    assert len(dates) == 12 and dates == sorted(dates, reverse=True)
    assert all(200_000 < row[2] < 2_000_000 for row in values["rows"])

    # an exact indicator name, as the indicator search returns it
    zori = await _call(client, "ndl_search_zillow_indicators", query="ZORI")
    rent = await _call(
        client,
        "ndl_get_zillow_data",
        indicator=next(
            i["name"] for i in zori["indicators"] if i["indicator_id"] == "RSNA"
        ),
        regions="394355",
        start_date="2022-01-01",
    )
    assert rent["indicator"]["indicator_id"] == "RSNA"
    assert rent["rows"][0][0] == "2022-07-31"
    assert 800 < rent["rows"][0][2] < 5_000

    name = error_text(
        await client.call_tool(
            "ndl_get_zillow_data", {"indicator": "ZALL", "regions": "Austin"}
        )
    )
    assert "[INVALID_REQUEST]" in name and "ndl_search_zillow_regions" in name
