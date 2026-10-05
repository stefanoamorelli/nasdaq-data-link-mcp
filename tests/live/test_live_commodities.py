"""Live checks of the commodities tools (CFTC COT, JODI, OPEC, LME, WASDE).

About 16 API calls: a metadata and a data read per table per test (repeated
reads in one test are cached), plus two WASDE/METADATA reads. Every table here
stopped updating (COT 2026-06, JODI 2024-12, LME 2024-07, WASDE 2024-02, OPEC
2024-01), so the assertions pin those end dates loosely ("at or after").
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import API_KEY_ENV, Settings
from nasdaq_data_link_mcp_os.server import create_server
from tests.conftest import payload

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get(API_KEY_ENV), reason=f"{API_KEY_ENV} unset"),
]


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with Client(create_server(Settings.from_env())) as connected:
        yield connected


async def _call(client: Client, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return payload(await client.call_tool(tool, args))


def _col(data: dict[str, Any], name: str) -> list[Any]:
    names = [c["name"] for c in data["columns"]]
    return [row[names.index(name)] for row in data["rows"]]


async def test_live_cot_gold_by_market_name(client: Client) -> None:
    data = await _call(client, "ndl_get_cot_report", {"contract": "GOLD", "limit": 8})
    assert data["access"] == "free" and data["contract"]["code"] == "088691"
    assert data["report"] == "disaggregated" and data["row_count"] == 8
    dates = _col(data, "date")
    assert dates == sorted(dates, reverse=True) and dates[0] >= "2026-06-09"
    assert all(oi > 100_000 for oi in _col(data, "market_participation"))
    longs, shorts = (
        _col(data, "money_manager_longs"),
        _col(data, "money_manager_shorts"),
    )
    assert _col(data, "money_manager_net") == [
        a - b for a, b in zip(longs, shorts, strict=True)
    ]


async def test_live_cot_legacy_and_concentration_by_code(client: Client) -> None:
    es = await _call(
        client,
        "ndl_get_cot_report",
        {"contract": "13874A", "start_date": "2026-01-01", "limit": 5},
    )
    assert es["contract"]["market"] == "E-MINI S&P 500"
    assert es["report"] == "legacy" and es["row_count"] == 5
    assert all(oi > 500_000 for oi in _col(es, "market_participation"))
    conc = await _call(
        client,
        "ndl_get_cot_report",
        {"contract": "067651", "report": "concentration", "limit": 2},
    )
    assert conc["type_code"] == "F_L_ALL_CR" and conc["row_count"] == 2
    assert all(0 < v < 100 for v in _col(conc, "largest_4_longs_gross"))


async def test_live_jodi_us_crude_production(client: Client) -> None:
    data = await _call(
        client,
        "ndl_get_jodi_energy_data",
        {"countries": "USA", "codes": "CRPRKD", "limit": 12},
    )
    assert data["codes"] == {"CRPRKD": "crude_oil | production | kbd"}
    assert data["row_count"] == 12 and _col(data, "date")[0] >= "2024-12-31"
    assert all(8_000 < v < 20_000 for v in _col(data, "value"))
    assert set(_col(data, "assessment")) <= {1, 2, 3}


async def test_live_opec_basket_price(client: Client) -> None:
    data = await _call(client, "ndl_get_opec_basket_price", {"limit": 5})
    assert [c["name"] for c in data["columns"]] == ["date", "price_usd_per_barrel"]
    assert data["row_count"] == 5 and data["rows"][0][0] >= "2024-01-25"
    assert all(20 < r[1] < 200 for r in data["rows"])


async def test_live_lme_copper_stocks(client: Client) -> None:
    data = await _call(
        client, "ndl_get_lme_warehouse_stocks", {"metals": "CU", "limit": 5}
    )
    assert data["location"] == "ALL" and data["row_count"] == 5
    assert _col(data, "date")[0] >= "2024-07-30"
    for row in data["rows"]:
        named = dict(zip([c["name"] for c in data["columns"]], row, strict=True))
        assert named["closing_stock"] == (
            named["opening_stock"] + named["delivered_in"] - named["delivered_out"]
        )
        assert named["closing_stock"] > 50_000


async def test_live_wasde_tables_by_code(client: Client) -> None:
    corn = await _call(
        client, "ndl_get_wasde_data", {"query": "CORN_US_12", "item": "Ending Stocks"}
    )
    assert corn["report_month"] >= "2024-02" and corn["row_count"] > 0
    assert set(_col(corn, "item")) == {"Ending Stocks"}
    assert all(v > 500 for v in _col(corn, "value"))  # million bushels
    wheat = await _call(
        client,
        "ndl_get_wasde_data",
        {
            "query": "WHEAT_WORLD_18,WHEAT_WORLD_19",
            "region": "US",
            "item": "Production",
        },
    )
    assert set(_col(wheat, "region")) == {"United States"}
    assert all(20 < v < 100 for v in _col(wheat, "value"))  # million tonnes
