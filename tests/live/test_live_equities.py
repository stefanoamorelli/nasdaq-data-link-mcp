"""Live checks of the equities toolset (Sharadar + Zacks) with a free key.

About 17 API calls per run. A free key reads SHARADAR/TICKERS and INDICATORS in
full and a fixed sample of the other Sharadar and Zacks tables; SF3* return
403. The assertions check shapes, orderings and plausible ranges, not values of
the sample rows.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import API_KEY_ENV, Settings
from nasdaq_data_link_mcp_os.server import create_server
from nasdaq_data_link_mcp_os.tools import equities
from tests.conftest import error_text, payload

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get(API_KEY_ENV), reason=f"{API_KEY_ENV} unset"),
]


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    settings = replace(Settings.from_env(), toolsets=("equities",))
    async with Client(create_server(settings)) as connected:
        yield connected


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    names = [c["name"] for c in data["columns"]]
    return [dict(zip(names, row, strict=True)) for row in data["rows"]]


def _column(data: dict[str, Any], name: str) -> list[Any]:
    return [r[name] for r in _records(data)]


def _newest_first(values: list[str]) -> bool:
    return bool(values) and values == sorted(values, reverse=True)


async def _call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    return payload(await client.call_tool(tool, arguments))


async def test_live_search_tickers(client: Client) -> None:
    found = await _call(client, "ndl_search_tickers", tickers=["AAPL", "NVDA", "SPY"])
    assert found["access"] == "free"
    by_ticker = {r["ticker"]: r for r in _records(found)}
    assert list(by_ticker) == ["AAPL", "NVDA", "SPY"]
    assert by_ticker["AAPL"]["exchange"] == "NASDAQ"
    assert by_ticker["AAPL"]["tables"].startswith("SF1,SEP")
    assert by_ticker["SPY"]["tables"] == "SFP"

    equities.clear_caches()  # cold fund list: one SHARADAR/TICKERS read
    funds = await _call(
        client, "ndl_search_tickers", query="vanguard small cap", security_type="fund"
    )
    assert "VB" in _column(funds, "ticker")[:5]
    assert set(_column(funds, "table")) == {"SFP"}


async def test_live_fundamentals_and_dictionary(client: Client) -> None:
    data = await _call(
        client,
        "ndl_get_fundamentals",
        tickers="AAPL",
        metrics=["revenue", "grossmargin"],
    )
    assert data["access"] == "sample"
    assert _newest_first(_column(data, "calendardate"))
    assert all(r["revenue"] > 0 and 0 < r["grossmargin"] < 1 for r in _records(data))

    fields = await _call(client, "ndl_search_financial_metrics", query="free cash flow")
    assert _column(fields, "indicator")[0] == "fcf"


async def test_live_stock_prices(client: Client) -> None:
    prices = await _call(client, "ndl_get_stock_prices", tickers="AAPL", limit=5)
    assert prices["access"] == "sample" and prices["row_count"] == 5
    assert _newest_first(_column(prices, "date"))
    assert all(r["low"] <= r["close"] <= r["high"] for r in _records(prices))


async def test_live_corporate_actions_and_events(client: Client) -> None:
    actions = await _call(
        client,
        "ndl_get_corporate_actions",
        tickers="AAPL",
        actions=["dividend"],
        limit=4,
    )
    assert _newest_first(_column(actions, "date"))
    assert all(0 < v < 5 for v in _column(actions, "value"))
    assert any("USD per share" in n for n in actions["notes"])

    events = await _call(
        client, "ndl_get_company_events", tickers="AAPL", start_date="2025-01-01"
    )
    assert _newest_first(_column(events, "date"))
    assert any(not e.startswith("code ") for e in _column(events, "events"))


async def test_live_institutional_holdings_need_subscription(client: Client) -> None:
    denied = error_text(
        await client.call_tool(
            "ndl_get_institutional_holdings",
            {"dataset": "by_ticker", "tickers": "AAPL"},
        )
    )
    assert "[SUBSCRIPTION]" in denied and "ZACKS/IHC" in denied


async def test_live_analyst_estimates(client: Client) -> None:
    estimates = await _call(
        client, "ndl_get_analyst_estimates", tickers="AAPL", period_type="annual"
    )
    assert set(_column(estimates, "per_type")) == {"A"}
    ends = _column(estimates, "per_end_date")
    assert ends == sorted(ends) and all(
        v > 0 for v in _column(estimates, "eps_mean_est")
    )
