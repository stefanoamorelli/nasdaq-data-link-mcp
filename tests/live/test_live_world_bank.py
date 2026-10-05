"""Live checks of the World Bank tools against WB/DATA and WB/METADATA.

About 8 API calls: one full WB/METADATA download (reused by later calls on the
same server), small filtered WB/METADATA reads, WB/DATA metadata and one WB/DATA
read per data call.
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


async def _data(client: Client, **args: Any) -> Any:
    return await client.call_tool("ndl_get_world_bank_data", args)


async def test_live_search_then_data(client: Client) -> None:
    gdp = payload(
        await client.call_tool(
            "ndl_search_world_bank_indicators", {"query": "GDP", "limit": 5}
        )
    )
    assert gdp["indicators_searched"] > 1400
    assert gdp["results"][0]["series_id"] == "NY.GDP.MKTP.CD"
    assert gdp["results"][0]["name"] == "GDP (current US$)"

    data = payload(
        await _data(
            client,
            indicators=["NY.GDP.MKTP.CD", "SP.POP.TOTL"],
            countries=["ITA", "United Kingdom", "WLD", "EMU"],
            start_date="2020",
        )
    )
    assert [c["code"] for c in data["countries"]] == ["ITA", "GBR", "WLD", "EMU"]
    assert data["indicators"][1] == {
        "series_id": "SP.POP.TOTL",
        "name": "Population, total",
    }
    assert data["access"] == "free"
    rows = data["rows"]
    assert {r[3] for r in rows} == {2020, 2021, 2022, 2023}
    assert [r[3] for r in rows] == sorted((r[3] for r in rows), reverse=True)
    values = {(r[0], r[1], r[3]): r[4] for r in rows}
    assert 1.5e12 < values[("NY.GDP.MKTP.CD", "ITA", 2023)] < 3e12
    assert 7.5e9 < values[("SP.POP.TOTL", "WLD", 2023)] < 8.5e9
    assert 6e7 < values[("SP.POP.TOTL", "GBR", 2023)] < 7.5e7

    keyword = error_text(await _data(client, indicators="inflation", countries="ITA"))
    assert "[INVALID_REQUEST]" in keyword and "FP.CPI.TOTL.ZG" in keyword
    assert "ndl_search_world_bank_indicators" in keyword


async def test_live_codes_aliases_and_lowercase_ids(client: Client) -> None:
    data = payload(
        await _data(
            client,
            indicators="sp.pop.totl",
            countries=["Türkiye", "South Korea", "Ivory Coast", "Russia", "US", "CN"],
            start_date="2023",
            end_date="2023",
        )
    )
    assert [r[1] for r in data["rows"]] == ["TUR", "KOR", "CIV", "RUS", "USA", "CHN"]
    assert data["indicators"] == [
        {"series_id": "SP.POP.TOTL", "name": "Population, total"}
    ]
    assert all(r[4] > 2e7 for r in data["rows"])

    unknown = error_text(
        await _data(client, indicators="SP.POP.TOTL", countries="Trinidad")
    )
    assert "TTO (Trinidad and Tobago)" in unknown

    gini = payload(
        await _data(client, indicators="SI.POV.GINI", countries="ITA", limit=5)
    )
    assert gini["row_count"] == 5 and 20 < gini["rows"][0][4] < 50
    assert gini["coverage"][0]["first_year"] < gini["coverage"][0]["last_year"]
