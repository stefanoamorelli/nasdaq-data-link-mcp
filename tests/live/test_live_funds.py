"""Live checks of the funds toolset (Nasdaq Fund Network NFN/MFR* tables).

About 15 API calls. Expectations match what a free key gets (fixed samples,
verified 2026-10-05): LIBAX is in the MFRSM, MFRSI, MFRPS and MFRPH10 samples;
MFRMF is 403.
"""

from __future__ import annotations

import os
from dataclasses import replace
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

LIBAX = "36e44fbe-384d-4f52-b107-9afbadec6bef"
COLUMBIA = "04638b4b-c7d3-490b-a98e-e00cb4eeeb3a"


def _client() -> Client:
    return Client(create_server(replace(Settings.from_env(), toolsets=("funds",))))


def _column(data: dict[str, Any], name: str) -> list[Any]:
    index = [c["name"] for c in data["columns"]].index(name)
    return [row[index] for row in data["rows"]]


async def test_live_search_by_ticker_and_name() -> None:
    async with _client() as client:
        found = payload(
            await client.call_tool("ndl_search_mutual_funds", {"query": "LIBAX"})
        )
        named = payload(
            await client.call_tool(
                "ndl_search_mutual_funds", {"query": "columbia bond"}
            )
        )
    assert found["matched_by"] == "ticker" and found["access"] == "sample"
    [fund] = found["funds"]
    assert fund["fund_id"] == COLUMBIA and fund["investment_company_type"] == "N-1A"
    assert fund["share_classes"][0]["security_id"] == LIBAX
    assert named["matched_by"] == "name"
    [columbia] = named["funds"]
    tickers = {s["ticker"] for s in columbia["share_classes"]}
    assert {"LIBAX", "CIBRX"} <= tickers and len(tickers) >= 6


async def test_live_reports() -> None:
    async with _client() as client:

        async def report(**arguments: Any) -> dict[str, Any]:
            result = await client.call_tool("ndl_get_mutual_fund_report", arguments)
            return payload(result)

        pricing = await report(report="pricing", tickers="LIBAX")
        fees = await report(report="fees", security_ids=LIBAX)
        top = await report(report="top_holdings", fund_ids=COLUMBIA)
        flows = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "flows", "fund_ids": COLUMBIA}
            )
        )
        missing = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "fees", "tickers": "VFIAX"}
            )
        )
    refs = _column(pricing, "ref_date")
    assert refs and refs == sorted(refs, reverse=True)
    assert set(_column(pricing, "pricing_type_id")) == {0, 2}
    assert 1 < _column(pricing, "last_price")[0] < 100
    assert pricing["resolved"][0]["security_id"] == LIBAX
    # Names are decoration, skipped when NFN/MFRPB is slow (shared key, 2 s box).
    skipped = any(n.startswith("Benchmark names") for n in pricing["notes"])
    assert pricing.get("benchmark_names") or skipped
    [expense_ratio] = _column(fees, "net_expenses_over_assets")
    assert 0 < expense_ratio < 0.03
    pct = _column(top, "pct_val")
    assert 1 <= len(pct) <= 10 and pct == sorted(pct, reverse=True)
    assert "[SUBSCRIPTION]" in flows and "fund_info" in flows
    assert "[INVALID_REQUEST]" in missing and "sample" in missing
