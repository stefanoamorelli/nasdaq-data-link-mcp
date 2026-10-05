from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.tools.crypto import (
    _metrics,
    _pairs,
    resolve_metrics,
    resolve_pairs,
)
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

PRICE_COLUMNS = [
    ("code", "text"),
    ("date", "Date"),
    *((name, "double") for name in ("high", "low", "mid", "last", "bid", "ask")),
    ("volume", "double"),
]


def _days(start: str, end: str, skip_every: int = 0) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [
        (first + timedelta(days=i)).isoformat()
        for i in range((last - first).days + 1)
        if not (skip_every and i % skip_every == 0)
    ]


def _prices(code: str, start: str, end: str) -> list[list[Any]]:
    return [[code, d, 6.0, 4.0, 5.0, 5.0, 4.9, 5.1, 1.0] for d in _days(start, end)]


def _bitfinex(fake: FakeNasdaq) -> None:
    # Rows are stored oldest first so the tests prove the tool sorts them.
    fake.add_table(
        "QDL/BITFINEX",
        columns=PRICE_COLUMNS,
        filters=["code", "date"],
        refreshed_at="2026-06-22T22:50:57.000Z",
        rows=[
            *_prices("BTCUSD", "2026-01-01", "2026-06-22"),
            *_prices("ETHUSD", "2026-01-01", "2026-06-22"),
            # A pair that left the feed: only a full-range read finds it.
            *_prices("ADAUSD", "2023-12-01", "2024-02-20"),
        ],
    )


def _bchain(fake: FakeNasdaq, rows: list[list[Any]] | None = None) -> None:
    if rows is None:
        rows = [["MKPRU", d, 60_000.0] for d in _days("2026-01-01", "2026-06-23")]
        # HRATE misses every 5th day, like the gaps in the live table.
        rows += [["HRATE", d, 9.0e8] for d in _days("2026-01-01", "2026-06-22", 5)]
    fake.add_table(
        "QDL/BCHAIN",
        columns=[("code", "text"), ("date", "Date"), ("value", "double")],
        filters=["code", "date"],
        refreshed_at="2026-06-23T05:01:02.000Z",
        rows=rows,
    )


def _keys(data: dict[str, Any]) -> list[tuple[str, str]]:
    return [(row[0], row[1]) for row in data["rows"]]


# ------------------------------------------------------------ resolution


def test_bundled_code_lists() -> None:
    current, ended = _pairs()
    assert len(current) == 44 and {"BTCUSD", "BTCUST", "UDCUSD"} <= set(current)
    assert "SOLUSD" in ended and not set(current) & set(ended)
    info, discontinued = _metrics()
    assert len(info) == 33 and len(discontinued) == 10
    assert set(discontinued) <= set(info) and info["HRATE"].unit == "TH/s"


@pytest.mark.parametrize(
    ("given", "code"),
    [("BTCUSD", "BTCUSD"), ("btc/usd", "BTCUSD"), (" eth-btc ", "ETHBTC")],
)
def test_pairs_accept_codes_ignoring_case_and_separators(given: str, code: str) -> None:
    assert resolve_pairs([given, code]) == [code]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("ETH", "Matching codes: ETHBTC, ETHEUR, ETHGBP, ETHUSD, ETHUST."),
        ("BTC/USDT", "Pairs with rows up to June 2026: ALGUSD"),
    ],
)
def test_pairs_reject_other_spellings(given: str, expected: str) -> None:
    with pytest.raises(InvalidRequestError, match="Unknown Bitfinex pair") as info:
        resolve_pairs([given])
    assert expected in str(info.value)


def test_metrics_accept_codes_and_all() -> None:
    assert resolve_metrics(["hrate", "MKPRU", "HRATE"]) == ["HRATE", "MKPRU"]
    everything = resolve_metrics(["all"])
    assert len(everything) == 23 and "BCDDE" not in everything


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("price", "Matching codes: MKPRU (bitcoin price, USD), MKTCP"),
        ("mempool", "Current codes: MKPRU (bitcoin price, USD); MKTCP"),
    ],
)
def test_metrics_reject_keywords(given: str, expected: str) -> None:
    with pytest.raises(InvalidRequestError, match="Unknown blockchain metric") as info:
        resolve_metrics([given])
    assert expected in str(info.value)


# ------------------------------------------------------------ reading


async def test_prices_newest_first_from_one_windowed_read(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bitfinex(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_crypto_prices", {"pairs": ["eth/usd", "BTCUSD"], "limit": 4}
            )
        )
    assert data["table"] == "QDL/BITFINEX" and data["access"] == "free"
    assert _keys(data) == [
        ("ETHUSD", "2026-06-22"),
        ("BTCUSD", "2026-06-22"),
        ("ETHUSD", "2026-06-21"),
        ("BTCUSD", "2026-06-21"),
    ]
    assert data["has_more"] is True
    assert any("raise limit (max 1000)" in n for n in data["notes"])
    assert any("last refreshed" in n for n in data["notes"])
    # 2 rows per pair: a window of ceil(2 * 1.4) + 14 = 17 days before the refresh.
    [request] = fake.data_requests("QDL/BITFINEX")
    assert request["code"] == "ETHUSD,BTCUSD" and request["date.gte"] == "2026-06-05"


async def test_prices_range_covered_by_the_window_and_fields(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bitfinex(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_crypto_prices",
                {
                    "pairs": "BTCUSD",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-10",
                    "fields": ["last", "volume"],
                },
            )
        )
    assert [c["name"] for c in data["columns"]] == ["code", "date", "last", "volume"]
    assert [row[1] for row in data["rows"]] == _days("2026-03-01", "2026-03-10")[::-1]
    assert data["has_more"] is False
    [request] = fake.data_requests("QDL/BITFINEX")
    assert (request["date.gte"], request["date.lte"]) == ("2026-03-01", "2026-03-10")
    assert request["qopts.columns"] == "code,date,last,volume"


async def test_short_code_is_read_again_over_the_whole_range(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bitfinex(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_crypto_prices", {"pairs": "BTCUSD,ADAUSD", "limit": 4}
            )
        )
    assert _keys(data) == [
        ("BTCUSD", "2026-06-22"),
        ("BTCUSD", "2026-06-21"),
        ("ADAUSD", "2024-02-20"),
        ("ADAUSD", "2024-02-19"),
    ]
    _, again = fake.data_requests("QDL/BITFINEX")
    assert again["code"] == "ADAUSD" and "date.gte" not in again
    assert data["request"]["api_calls"] == 2
    assert (
        "ADAUSD has no rows after 2024-02-20; the table runs to 2026-06-22."
        in data["notes"]
    )
    # One metadata read serves both data reads.
    assert sum(r.url.path.endswith("/metadata") for r in fake.requests) == 1


async def test_complete_short_read_has_no_more_rows(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bitfinex(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_crypto_prices", {"pairs": "ADAUSD", "limit": 100}
            )
        )
        empty = payload(
            await client.call_tool(
                "ndl_get_crypto_prices",
                {
                    "pairs": "BTCUSD",
                    "start_date": "2010-01-01",
                    "end_date": "2010-12-31",
                },
            )
        )
    assert data["row_count"] == 82 and data["has_more"] is False
    assert not any(n.startswith("Showing up to") for n in data["notes"])
    assert empty["rows"] == [] and empty["has_more"] is False
    assert "No rows for BTCUSD in the requested dates." in empty["notes"]


async def test_metrics_gaps_labels_and_order(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bchain(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_blockchain_metrics", {"metrics": "MKPRU,HRATE", "limit": 30}
            )
        )
    assert data["metrics"] == {
        "MKPRU": {"label": "bitcoin price", "unit": "USD"},
        "HRATE": {"label": "hash rate of the network, estimated", "unit": "TH/s"},
    }
    counts = {
        code: sum(row[0] == code for row in data["rows"]) for code in data["metrics"]
    }
    assert counts == {"MKPRU": 15, "HRATE": 15}
    dates = [row[1] for row in data["rows"]]
    assert dates == sorted(dates, reverse=True)
    # HRATE's missing days still fit in the first window.
    assert len(fake.data_requests("QDL/BCHAIN")) == 1


async def test_rereads_are_capped(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _bchain(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_blockchain_metrics", {"metrics": "all", "limit": 23}
            )
        )
    # Only MKPRU and HRATE exist in the fake; 5 of the other 21 are read again.
    assert _keys(data) == [("MKPRU", "2026-06-23"), ("HRATE", "2026-06-22")]
    assert len(fake.data_requests("QDL/BCHAIN")) == 1 + 5
    assert any("had fewer rows than requested" in n for n in data["notes"])
    assert data["has_more"] is True


async def test_truncated_read_is_flagged(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    start = date(1990, 1, 1)
    _bchain(
        fake,
        [
            ["MKPRU", (start + timedelta(days=i)).isoformat(), 1.0]
            for i in range(10_001)
        ],
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_blockchain_metrics", {"metrics": "MKPRU", "limit": 3}
            )
        )
    assert data["has_more"] is True and data["row_count"] == 3
    assert any("more than 10,000 rows" in n for n in data["notes"])


async def test_paging_note_at_the_maximum_limit(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _bitfinex(fake)
    async with make_client(max_limit=5, default_limit=5) as client:
        data = payload(
            await client.call_tool("ndl_get_crypto_prices", {"pairs": "BTCUSD"})
        )
    [paging] = [n for n in data["notes"] if n.startswith("Showing up to 5")]
    assert "raise limit" not in paging


async def test_without_metadata_the_newest_rows_are_still_found(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nasdaq_data_link_mcp_os.tools import crypto

    async def no_metadata(state: Any, code: str) -> None:
        return None

    monkeypatch.setattr(crypto, "get_metadata", no_metadata)
    _bitfinex(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_crypto_prices", {"pairs": "BTCUSD", "limit": 2}
            )
        )
    assert _keys(data) == [("BTCUSD", "2026-06-22"), ("BTCUSD", "2026-06-21")]


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("ndl_get_crypto_prices", {"pairs": "FOOBAR"}, "Unknown Bitfinex pair"),
        ("ndl_get_crypto_prices", {"pairs": list(_pairs()[0][:21])}, "the limit is 20"),
        ("ndl_get_crypto_prices", {"pairs": []}, "at least one pair"),
        (
            "ndl_get_crypto_prices",
            {"pairs": "BTCUSD", "start_date": "2026-05-01", "end_date": "2026-04-01"},
            "after end date",
        ),
        ("ndl_get_blockchain_metrics", {"metrics": "hash rate"}, "HRATE"),
        (
            "ndl_get_blockchain_metrics",
            {"metrics": "MKPRU", "start_date": "01/02/2026"},
            "",
        ),
    ],
)
async def test_invalid_requests_make_no_data_calls(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    tool: str,
    args: dict[str, Any],
    expected: str,
) -> None:
    _bitfinex(fake)
    _bchain(fake)
    async with make_client() as client:
        assert expected in error_text(await client.call_tool(tool, args))
    assert fake.data_requests() == []
