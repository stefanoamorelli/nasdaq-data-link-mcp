"""Live checks of the nasdaq toolset (RTAT, ticker changes, Equities 360).

About 11 API calls per run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime

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
RETAIL = "ndl_get_retail_trading_activity"


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    settings = replace(Settings.from_env(), toolsets=("nasdaq",))
    async with Client(create_server(settings)) as connected:
        yield connected


async def test_live_retail_trading_activity(client: Client) -> None:
    top = payload(await client.call_tool(RETAIL, {}))
    rows = top["rows"]
    assert top["table"] == "NDAQ/RTAT10" and top["access"] == "free"
    assert top["row_count"] == 100
    latest = rows[0][0]
    assert (datetime.now(UTC).date() - date.fromisoformat(latest)).days <= 7
    # Ten rows per trading day, newest day first, ranked by activity.
    assert len({r[0] for r in rows[:10]}) == 1
    assert [r[2] for r in rows[:10]] == sorted((r[2] for r in rows[:10]), reverse=True)
    assert all(0 <= r[2] <= 1 and -100 <= r[3] <= 100 for r in rows)

    # KO left the daily top 10 years ago; the note says when.
    ko = payload(await client.call_tool(RETAIL, {"tickers": "KO"}))
    newest = ko["rows"][0][0]
    assert {r[1] for r in ko["rows"]} == {"KO"} and newest < latest
    assert (
        f"KO last appeared in the daily top 10 on {newest} (latest trading day "
        f"{latest})"
    ) in ko["notes"][0]

    one_day = {"start_date": "2016-01-15", "end_date": "2016-01-15"}
    sample = payload(await client.call_tool(RETAIL, {"dataset": "rtat", **one_day}))
    assert sample["access"] == "sample" and sample["row_count"] == 7


async def test_live_ticker_changes(client: Client) -> None:
    fb = payload(await client.call_tool("ndl_get_ticker_changes", {"tickers": "FB"}))
    assert fb["access"] == "free"
    meta = ["1980-01-01", "FB", "BBG000MM2P62", None, "META", "2022-06-09"]
    assert meta in fb["rows"]
    # FB was reused by another security in 2025.
    assert any(r[0] >= "2025-01-01" and r[2] != "BBG000MM2P62" for r in fb["rows"])


async def test_live_equities360_needs_subscription(client: Client) -> None:
    args = {"dataset": "fundamentals_details", "tickers": "MSFT", "dimension": "MRY"}
    text = error_text(await client.call_tool("ndl_get_equities360", args))
    assert "[SUBSCRIPTION]" in text and "NDAQ/FD" in text and "QEPx04" in text
    assert "SHARADAR/SF1" in text and "ndl_query_table" in text
