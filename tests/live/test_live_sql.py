"""Live checks of ndl_sql_query against DataLink SQL (Trino).

Each statement costs 2-6 HTTP calls (one POST, then nextUri polls).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from datetime import date, timedelta
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
    settings = Settings.from_env()
    async with Client(create_server(settings)) as connected:
        yield connected


async def _query(client: Client, sql: str, **extra: Any) -> tuple[Any, float]:
    started = time.monotonic()
    result = await client.call_tool("ndl_sql_query", {"sql": sql, **extra})
    return result, time.monotonic() - started


async def test_show_tables_lists_rtat(client: Client) -> None:
    result, elapsed = await _query(client, "SHOW TABLES")
    data = payload(result)
    tables = {row[0] for row in data["rows"]}
    assert "ndaq_rtat10" in tables, tables
    assert data["has_more"] is False
    assert any("Tables API" in note for note in data["notes"])
    assert elapsed < 60, elapsed


async def test_describe_rtat10(client: Client) -> None:
    result, _ = await _query(client, "DESCRIBE ndaq_rtat10")
    data = payload(result)
    assert [c["name"] for c in data["columns"]][:2] == ["Column", "Type"]
    types = {row[0]: row[1] for row in data["rows"]}
    assert types["date"] == "date"
    assert types["ticker"] == "varchar"
    assert types["activity"] == "double"
    assert types["sentiment"] == "integer"


async def test_latest_rows_sorted_server_side(client: Client) -> None:
    # The trailing ';' is rejected by Trino itself; the tool strips it.
    result, elapsed = await _query(
        client,
        "SELECT date, ticker, activity, sentiment FROM ndaq_rtat10 "
        "ORDER BY date DESC, activity DESC LIMIT 5;",
    )
    data = payload(result)
    assert data["row_count"] == 5 and data["has_more"] is False
    dates = [row[0] for row in data["rows"]]
    assert dates == sorted(dates, reverse=True)
    newest = date.fromisoformat(dates[0])
    assert newest >= date.today() - timedelta(days=10), newest
    for _, ticker, activity, sentiment in data["rows"]:
        assert ticker and 0 < activity < 1 and -100 <= sentiment <= 100
    assert elapsed < 60, elapsed


async def test_aggregate_sentiment_last_30_days(client: Client) -> None:
    result, _ = await _query(
        client,
        "SELECT ticker, count(*) AS days, round(avg(sentiment), 2) AS avg_sentiment "
        "FROM ndaq_rtat10 WHERE date >= current_date - INTERVAL '30' DAY "
        "GROUP BY ticker ORDER BY days DESC, ticker LIMIT 10",
    )
    data = payload(result)
    assert [c["name"] for c in data["columns"]] == ["ticker", "days", "avg_sentiment"]
    assert 1 <= data["row_count"] <= 10
    counts = [row[1] for row in data["rows"]]
    assert counts == sorted(counts, reverse=True)
    for ticker, days, avg_sentiment in data["rows"]:
        assert ticker and 1 <= days <= 31
        assert -100 <= float(avg_sentiment) <= 100


async def test_limit_cuts_a_larger_result(client: Client) -> None:
    result, _ = await _query(
        client,
        "SELECT date, ticker FROM ndaq_rtat10 WHERE date >= DATE '2026-09-01' "
        "ORDER BY date DESC, ticker",
        limit=3,
    )
    data = payload(result)
    assert data["row_count"] == 3 and data["has_more"] is True


async def test_denied_table_is_a_subscription_error(client: Client) -> None:
    result, _ = await _query(client, "SELECT * FROM qdl_opec LIMIT 2")
    text = error_text(result)
    assert "[SUBSCRIPTION]" in text and "qdl_opec" in text
    assert "ndl_query_table" in text
    key = os.environ[API_KEY_ENV]
    assert key not in text


async def test_syntax_error_is_an_invalid_request(client: Client) -> None:
    result, _ = await _query(client, "SELECT FROM ndaq_rtat10 WHERE")
    text = error_text(result)
    assert "[INVALID_REQUEST]" in text and "SYNTAX_ERROR" in text


async def test_write_statement_is_rejected_locally(client: Client) -> None:
    result, _ = await _query(client, "DROP TABLE ndaq_rtat10")
    assert "[INVALID_REQUEST]" in error_text(result)
