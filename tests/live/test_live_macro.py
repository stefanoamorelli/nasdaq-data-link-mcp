"""Live checks of the macro tools against QDL/ODA (IMF WEO) and QDL/ML (ICE BofA).

About 8 API calls: the module shares one server, so each table's metadata is
read once, plus one data read per successful tool call. Both tables are
frozen, so the expected values are exact.
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


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def client() -> AsyncIterator[Client]:
    async with Client(create_server(Settings.from_env())) as connected:
        yield connected


def _values(data: dict[str, Any]) -> dict[tuple[str, str], Any]:
    return {(row[0], row[1]): row[2] for row in data["rows"]}


async def test_live_weo_edition_and_projection_flags(client: Client) -> None:
    args = {
        "countries": "USA",
        "indicators": "NGDPD",
        "start_date": "2022",
        "end_date": "2028",
    }
    data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    values = _values(data)
    projected = {row[1][:4]: row[3] for row in data["rows"]}
    assert data["access"] == "free"
    # April 2023 WEO figures; the October 2023 edition has 25462.73 and 32690.37.
    assert values[("USA_NGDPD", "2022-12-31")] == 25464.475
    assert values[("USA_NGDPD", "2028-12-31")] == 32349.658
    assert data["rows"][0][1] == "2028-12-31"
    assert projected["2022"] is False and projected["2023"] is projected["2028"] is True
    assert data["series"][0]["unit"] == "USD bn"
    assert data["notes"][0].startswith("IMF WEO April 2023 edition")


async def test_live_weo_countries_groups_and_commodities(client: Client) -> None:
    args = {
        "countries": ["DEU", "JP", "FAD_G7"],
        "indicators": ["NGDP_RPCH", "POILBRE"],
        "start_date": "2019",
        "end_date": "2022",
    }
    data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    values = _values(data)
    assert data["request"]["indicator"] == (
        "DEU_NGDP_RPCH,WORLD_POILBRE,JPN_NGDP_RPCH,FAD_G7_NGDP_RPCH"
    )
    assert data["row_count"] == 16
    assert all(v is not None for v in values.values())
    assert values[("FAD_G7_NGDP_RPCH", "2020-12-31")] < -3
    assert values[("DEU_NGDP_RPCH", "2021-12-31")] > 2
    assert 90 < values[("WORLD_POILBRE", "2022-12-31")] < 110
    assert not any(row[3] for row in data["rows"])


async def test_live_bond_snapshot(client: Client) -> None:
    data = payload(await client.call_tool("ndl_get_bond_index_yields", {}))
    assert data["access"] == "free"
    assert data["row_count"] == 27 and len(data["series"]) == 27
    assert {r[1] for r in data["rows"]} == {"2025-02-27"}
    rates = {r[0]: r[2] for r in data["rows"]}
    assert 4 < rates["BAMLC0A0CMEY"] < 7
    assert rates["BAMLHYH0A3CMTRIV"] > 100
    assert any("no longer updated" in n for n in data["notes"])


async def test_live_bond_codes_and_range(client: Client) -> None:
    args = {
        "series": ["BAMLH0A0HYM2", "bamlc0a4cbbbey"],
        "start_date": "2025-02-01",
        "end_date": "2025-02-28",
    }
    data = payload(await client.call_tool("ndl_get_bond_index_yields", args))
    by_code: dict[str, list[float]] = {}
    for row in data["rows"]:
        by_code.setdefault(row[0], []).append(row[2])
    assert set(by_code) == {"BAMLH0A0HYM2", "BAMLC0A4CBBBEY"}
    assert all(1.5 < v < 5 for v in by_code["BAMLH0A0HYM2"])
    assert all(4 < v < 7 for v in by_code["BAMLC0A4CBBBEY"])
    assert data["rows"][0][1] == "2025-02-27"


async def test_live_unknown_codes_spend_no_data_calls(client: Client) -> None:
    country = error_text(
        await client.call_tool("ndl_get_imf_weo_data", {"countries": "Congo"})
    )
    bond = error_text(
        await client.call_tool("ndl_get_bond_index_yields", {"series": "BBB"})
    )
    assert "COD" in country and "COG" in country
    assert "BAMLC0A4CBBBEY" in bond
