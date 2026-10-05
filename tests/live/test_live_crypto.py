"""Live checks of the crypto tools against QDL/BITFINEX and QDL/BCHAIN.

About 9 API calls: one metadata read per table, one windowed data read per
tool call, and one full-range read for a pair or metric that stopped earlier.
Both tables stopped updating in June 2026.
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


def _by_code(data: dict[str, Any]) -> dict[str, list[list[Any]]]:
    out: dict[str, list[list[Any]]] = {}
    for row in data["rows"]:
        out.setdefault(row[0], []).append(row)
    return out


async def test_live_crypto_prices(client: Client) -> None:
    data = payload(
        await client.call_tool(
            "ndl_get_crypto_prices", {"pairs": ["btc/usd", "ETHUSD"], "limit": 6}
        )
    )
    assert data["access"] == "free"
    names = [c["name"] for c in data["columns"]]
    assert names == "code date high low mid last bid ask volume".split()
    by_code = _by_code(data)
    assert {code: len(rows) for code, rows in by_code.items()} == {
        "BTCUSD": 3,
        "ETHUSD": 3,
    }
    dates = [row[1] for row in data["rows"]]
    assert dates == sorted(dates, reverse=True) and dates[0] >= "2026-06-22"
    btc = by_code["BTCUSD"][0]
    assert 1_000 < btc[5] < 1_000_000 and btc[3] <= btc[5] <= btc[2]

    # SOLUSD left the daily feed in 2024: found by the full-range read.
    ended = payload(
        await client.call_tool("ndl_get_crypto_prices", {"pairs": "SOLUSD", "limit": 3})
    )
    sol_dates = [row[1] for row in ended["rows"]]
    assert len(sol_dates) == 3 and sol_dates == sorted(sol_dates, reverse=True)
    assert sol_dates[0] < "2026-01-01"
    assert any(n.startswith("SOLUSD has no rows after") for n in ended["notes"])
    assert ended["request"]["api_calls"] == 2


async def test_live_blockchain_metrics(client: Client) -> None:
    data = payload(
        await client.call_tool(
            "ndl_get_blockchain_metrics", {"metrics": ["MKPRU", "HRATE"], "limit": 10}
        )
    )
    assert data["access"] == "free"
    assert data["metrics"]["HRATE"]["unit"] == "TH/s"
    by_code = _by_code(data)
    assert {code: len(rows) for code, rows in by_code.items()} == {
        "MKPRU": 5,
        "HRATE": 5,
    }
    assert 1_000 < by_code["MKPRU"][0][2] < 1_000_000
    assert by_code["HRATE"][0][2] > 1e8  # hundreds of EH/s, expressed in TH/s

    snapshot = payload(
        await client.call_tool(
            "ndl_get_blockchain_metrics", {"metrics": "all", "limit": 23}
        )
    )
    codes = [row[0] for row in snapshot["rows"]]
    assert len(codes) == len(set(codes)) >= 20
    totbc = next(row[2] for row in snapshot["rows"] if row[0] == "TOTBC")
    assert 19_000_000 < totbc < 21_000_000

    old = payload(
        await client.call_tool(
            "ndl_get_blockchain_metrics", {"metrics": "TVTVR", "limit": 2}
        )
    )
    assert [row[1] for row in old["rows"]] == ["2016-07-17", "2016-07-16"]
    assert any(n.startswith("TVTVR has no rows after") for n in old["notes"])
