"""Offline tests for the nasdaq toolset (RTAT, ticker changes, Equities 360)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from nasdaq_data_link_mcp_os.tools.nasdaq import (
    E360_TABLES,
    FD_DEFAULT_COLUMNS,
    RTAT_SAMPLE_NOTE,
    TC_HISTORY_COLUMNS,
)
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

RETAIL, CHANGES, E360 = (
    "ndl_get_retail_trading_activity",
    "ndl_get_ticker_changes",
    "ndl_get_equities360",
)
TICKERS = ["TSLA", "NVDA", "SPY", "QQQ", "AAPL", "AMD", "MU", "PLTR", "AMZN", "META"]
RTAT_COLUMNS = [
    ("date", "Date"),
    ("ticker", "text"),
    ("activity", "double"),
    ("sentiment", "Integer"),
]
# Synthetic stand-in for the free 7-row NDAQ/RTAT sample.
RTAT_SAMPLE = [["2016-01-15", f"T{i}", 0.001 * (i + 1), i - 3] for i in range(7)]


async def _ok(make: ClientFactory, tool: str, args: dict[str, Any], **kw: Any) -> Any:
    async with make(**kw) as client:
        return payload(await client.call_tool(tool, args))


async def _error(
    make: ClientFactory, tool: str, args: dict[str, Any], **kw: Any
) -> str:
    async with make(**kw) as client:
        return error_text(await client.call_tool(tool, args))


def _rtat(
    fake: FakeNasdaq, code: str = "NDAQ/RTAT10", rows: Any = None, days: int = 30
) -> list[str]:
    """Register an RTAT table; by default ten rows per weekday, oldest first."""
    trading: list[str] = []
    day = date(2026, 10, 2)
    while len(trading) < days:
        if day.weekday() < 5:
            trading.append(day.isoformat())
        day -= timedelta(days=1)
    if rows is None:
        rows = [
            [d, t, round(0.01 + ((i * 7 + j) % 10) / 1000, 4), (i * 13 + j) % 41 - 20]
            for j, d in enumerate(reversed(trading))
            for i, t in enumerate(TICKERS)
        ]
    fake.add_table(
        code,
        columns=RTAT_COLUMNS,
        filters=["date", "ticker"],
        rows=rows,
        premium=code == "NDAQ/RTAT",
        refreshed_at="2026-10-03T02:54:23.000Z",
    )
    return trading


def _tc(fake: FakeNasdaq) -> None:
    fake.add_table(
        "NDAQ/TC",
        columns=[("date", "text"), ("symbol", "text"), ("figi", "text")],
        filters=["date", "symbol", "figi"],
        rows=[
            ["1980-01-01", "FB", "BBG000MM2P62"],
            ["2022-06-09", "META", "BBG000MM2P62"],
            ["2025-06-26", "FB", "BBG01VRMNFB1"],
            ["2026-10-02", "BCOM", "BBG025FW37D6"],
            ["1980-01-01", "OLDX", "BBG000AAAAA1"],
            ["2026-09-30", "NEWX", "BBG000AAAAA1"],
        ],
        refreshed_at="2026-10-02T08:12:07.000Z",
    )


# Equities 360 schemas (column names, filters) from the documented /metadata endpoint.
_E360_RAW = {
    "NDAQ/STAT": (
        "symbol figi marketcap high52week high52week_date low52week "
        "low52week_date avgvolume1m avgvolume3m divyield dividendpershare "
        "exdividenddate pe epsdil eps pe1 pb freefloat fxusd",
        "figi symbol",
    ),
    "NDAQ/FS": (
        "calendardate symbol figi reportperiod dimension fcfps ps pe revenue "
        "currentratio de roa roe ros gp opinc netmargin ebitda bvps evebit "
        "evebitda tbvps",
        "calendardate dimension figi symbol",
    ),
    "NDAQ/FD": (
        "calendardate symbol figi reportperiod dimension payables receivables "
        "cashneq investmentsnc investmentsc taxassets ncfo capex cashnequsd "
        "netincdis debtc dps retearn ebitda ebit equity ncfbus depamor taxexp "
        "sgna rnd opex sbcomp tangibles intangibles eps ebt netinc opinc "
        "consolinc inventory debtnc taxliabilities liabilitiesnc liabilities "
        "deferredrev accoci ppnenet pe1 gp grossmargin revenue intexp cor "
        "ncfcommon netinccmn ncfinv ncff shareswa epsusd workingcapital invcap "
        "invcapavg roic freecashflow ebitdamargin ev evebit evebitda divyield "
        "assetturnover revenueusd debttoassests shareswadil sharesbas",
        "calendardate dimension figi symbol",
    ),
    "NDAQ/BS": (
        "calendardate symbol figi reportperiod dimension assets bvps cashneq "
        "debt liabilities equity accoci currency investmentsnc investmentsc "
        "receivables inventory assetsnc assetsc investments ppnenet intangibles "
        "tangibles payables liabilitiesnc liabilitiesc debtc debtnc deferredrev "
        "retearn taxassets taxliabilities cashnequsd",
        "calendardate dimension figi symbol",
    ),
    "NDAQ/IS": (
        "calendardate symbol figi reportperiod dimension revenue cor opinc eps "
        "epsdil ebitda ebit gp rnd sgna opex intexp ebt taxexp netinc netincnci "
        "netinccmnusd netinccmn netincdis dps shareswa shareswadil epsusd "
        "consolinc prefdivis",
        "calendardate dimension figi symbol",
    ),
    "NDAQ/CF": (
        "calendardate symbol figi reportperiod dimension opex ncfi ncff fcf "
        "ncfo capex ncfbus sbcomp depamor ncfcommon ncfinv debttoassets",
        "calendardate dimension figi symbol",
    ),
    "NDAQ/RD": (
        "symbol figi exchange category cusips name industry companysite sector "
        "major_theme_1 major_theme_2 secfilings siccode location isdelisted",
        "symbol figi",
    ),
    "NDAQ/CA": (
        "date symbol figi action value contrasymbol contraname",
        "contrasymbol date figi symbol",
    ),
}
E360_SCHEMAS = {code: (c.split(), f.split()) for code, (c, f) in _E360_RAW.items()}


def _e360(
    fake: FakeNasdaq, code: str, rows: list[dict[str, Any]] | None = None
) -> None:
    """Register an Equities 360 table with its live schema; 403 without rows."""
    columns, filters = E360_SCHEMAS[code]
    fake.add_table(
        code,
        columns=[(c, "text") for c in columns],
        filters=list(filters),
        rows=[[row.get(c) for c in columns] for row in rows or []],
        premium=True,
        forbidden=rows is None,
        refreshed_at="2026-10-02T09:16:08.000Z",
    )


# -------------------------------------------------------- retail activity


async def test_retail_default_reads_recent_days_ranked(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    days = _rtat(fake)
    data = await _ok(make_client, RETAIL, {"limit": 15})
    # 2 trading days -> ceil(2 * 1.5) + 10 = 13 calendar days before the refresh
    assert fake.data_requests("NDAQ/RTAT10")[-1]["date.gte"] == "2026-09-20"
    rows = data["rows"]
    assert [r[0] for r in rows] == [days[0]] * 10 + [days[1]] * 5
    for day_rows in (rows[:10], rows[10:]):
        assert [r[2] for r in day_rows] == sorted(
            (r[2] for r in day_rows), reverse=True
        )
    assert rows[10][2] == max(
        r[2] for r in fake.tables["NDAQ/RTAT10"].rows if r[0] == days[1]
    )
    assert "100 rows matched; showing the first 15." in data["notes"]


async def test_retail_tickers_and_dates(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    days = _rtat(fake)
    args = {"tickers": "tsla, nvda", "start_date": days[4], "end_date": days[0]}
    data = await _ok(make_client, RETAIL, args)
    [sent] = fake.data_requests("NDAQ/RTAT10")  # an end_date needs no latest lookup
    assert sent["ticker"] == "TSLA,NVDA"
    assert (sent["date.gte"], sent["date.lte"]) == (days[4], days[0])
    assert data["row_count"] == 10 and {r[1] for r in data["rows"]} == {"TSLA", "NVDA"}
    assert data["rows"][0][0] == days[0] and data["rows"][-1][0] == days[4]
    assert not any("top 10" in n for n in data["notes"])  # both are current


async def test_retail_notes_tickers_outside_the_top10(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    days = _rtat(fake)
    fake.tables["NDAQ/RTAT10"].rows.append([days[20], "KO", 0.011, 3])
    recent = await _ok(make_client, RETAIL, {"tickers": ["ko", "TSLA", "PEP"]})
    main, lookup = fake.data_requests("NDAQ/RTAT10")
    assert "date.gte" not in main and main["ticker"] == "KO,TSLA,PEP"
    assert lookup["qopts.columns"] == "date" and lookup["date.gte"] == "2026-09-19"
    assert recent["notes"][0] == (
        f"KO last appeared in the daily top 10 on {days[20]} (latest trading day "
        f"{days[0]}); PEP: not in the daily top 10 on any day; RTAT10 lists only "
        "each day's top 10."
    )
    args = {"tickers": "KO,PEP", "start_date": days[25], "end_date": days[15]}
    past = await _ok(make_client, RETAIL, args)
    assert len(fake.data_requests("NDAQ/RTAT10")) == 3
    assert [r[1] for r in past["rows"]] == ["KO"]
    assert past["notes"][0] == (
        "PEP: not in the daily top 10 in the requested dates; RTAT10 lists only "
        "each day's top 10."
    )


async def test_retail_rtat_latest_day_and_free_sample(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    days = _rtat(fake)
    _rtat(fake, "NDAQ/RTAT", RTAT_SAMPLE)
    latest = await _ok(make_client, RETAIL, {"dataset": "rtat"})
    [lookup] = fake.data_requests("NDAQ/RTAT10")
    assert lookup["qopts.per_page"] == "500"
    assert fake.data_requests("NDAQ/RTAT")[0]["date"] == days[0]
    assert latest["access"] == "sample" and latest["rows"] == []
    assert RTAT_SAMPLE_NOTE in latest["notes"]
    assert f"showing the latest trading day, {days[0]}." in latest["notes"][0]

    one_day = {"start_date": "2016-01-15", "end_date": "2016-01-15"}
    sample = await _ok(make_client, RETAIL, {"dataset": "rtat", **one_day})
    assert [r[1] for r in sample["rows"]] == [f"T{i}" for i in range(6, -1, -1)]
    assert any(n.startswith("Sample data:") for n in sample["notes"])
    assert RTAT_SAMPLE_NOTE not in sample["notes"]


async def test_retail_ticker_history_reads_every_page(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    # 11,000 rows stored oldest first: the newest day is only on the second page.
    days = _rtat(fake, days=1_100)
    data = await _ok(make_client, RETAIL, {"tickers": TICKERS, "limit": 10})
    first, second, _lookup = fake.data_requests("NDAQ/RTAT10")
    assert "qopts.cursor_id" not in first and "qopts.cursor_id" in second
    assert {r[0] for r in data["rows"]} == {days[0]}
    assert data["notes"][0] == "11000 rows matched; showing the first 10."


# --------------------------------------------------------- ticker changes


async def test_ticker_changes_adds_symbol_history(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _tc(fake)
    data = await _ok(make_client, CHANGES, {"tickers": "fb"})
    main, history = fake.data_requests("NDAQ/TC")
    assert main["symbol"] == "FB"
    assert history["figi"] == "BBG01VRMNFB1,BBG000MM2P62"
    assert tuple(c["name"] for c in data["columns"][3:]) == TC_HISTORY_COLUMNS
    assert data["rows"] == [
        ["2025-06-26", "FB", "BBG01VRMNFB1", None, None, None],
        ["1980-01-01", "FB", "BBG000MM2P62", None, "META", "2022-06-09"],
    ]


async def test_ticker_changes_default_window_and_history_cap(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tc(fake)
    data = await _ok(make_client, CHANGES, {})
    assert fake.data_requests("NDAQ/TC")[0]["date.gte"] == "2026-07-04"
    assert data["rows"] == [
        ["2026-10-02", "BCOM", "BBG025FW37D6", None, None, None],
        ["2026-09-30", "NEWX", "BBG000AAAAA1", "OLDX", None, None],
    ]
    monkeypatch.setattr("nasdaq_data_link_mcp_os.tools.nasdaq.TC_HISTORY_MAX_FIGIS", 1)
    capped = await _ok(make_client, CHANGES, {})
    assert capped["rows"][1][3:] == [None, None, None]
    assert (
        "previous/next symbols cover the first 1 of 2 FIGIs only." in (capped["notes"])
    )


async def test_ticker_changes_figis(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _tc(fake)
    args = {"figis": ["bbg000mm2p62"], "resolve_history": False}
    plain = await _ok(make_client, CHANGES, args)
    [sent] = fake.data_requests("NDAQ/TC")
    assert sent["figi"] == "BBG000MM2P62"
    assert [r[1] for r in plain["rows"]] == ["META", "FB"]
    assert len(plain["columns"]) == 3
    bad = await _error(make_client, CHANGES, {"figis": "AAPL"})
    assert "[INVALID_REQUEST] Not a FIGI: AAPL" in bad


# ----------------------------------------------------------- Equities 360


@pytest.mark.parametrize("dataset", list(E360_TABLES))
async def test_equities360_free_key_gets_subscription_error(
    fake: FakeNasdaq, make_client: ClientFactory, dataset: str
) -> None:
    code = E360_TABLES[dataset]
    _e360(fake, code)
    text = await _error(make_client, E360, {"dataset": dataset, "tickers": "MSFT"})
    assert "[SUBSCRIPTION]" in text and code in text
    assert "ndl_search_tickers" in text and "ndl_get_fundamentals" in text
    assert fake.data_requests(code)[-1]["symbol"] == "MSFT"


async def test_equities360_hint_without_equities_toolset(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _e360(fake, "NDAQ/STAT")
    args = {"dataset": "statistics", "tickers": "MSFT"}
    text = await _error(make_client, E360, args, toolsets=("nasdaq",))
    assert "ndl_get_fundamentals" not in text
    assert "SHARADAR/SF1" in text and "ndl_query_table" in text


async def test_equities360_fundamentals_columns_and_order(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    dates = ["2023-06-30", "2025-06-30", "2024-06-30"]
    rows = [{"calendardate": d, "symbol": "MSFT", "dimension": "MRY"} for d in dates]
    _e360(fake, "NDAQ/FD", rows)
    args = {"tickers": "msft", "dimension": "MRY", "start_date": "2024-01-01"}
    data = await _ok(make_client, E360, {"dataset": "fundamentals_details", **args})
    await _ok(
        make_client, E360, {"dataset": "fundamentals_details", "columns": ["eps"]}
    )
    first, second = fake.data_requests("NDAQ/FD")
    assert first["qopts.columns"] == ",".join(FD_DEFAULT_COLUMNS)
    assert first["dimension"] == "MRY" and first["calendardate.gte"] == "2024-01-01"
    assert [r[0] for r in data["rows"]] == ["2025-06-30", "2024-06-30"]
    assert data["notes"][0].startswith("Showing 27 of NDAQ/FD's columns")
    # The primary key stays in front of the caller's columns.
    assert second["qopts.columns"] == "calendardate,symbol,dimension,reportperiod,eps"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"dataset": "statistics", "dimension": "MRY"}, "'dimension' cannot be used"),
        ({"dataset": "reference_data", "start_date": "2024-01-01"}, "'date' cannot"),
        ({"dataset": "balance_sheet", "contra_tickers": "AAPL"}, "'contrasymbol'"),
        ({"dataset": "cash_flow", "columns": ["nope"]}, "Unknown column(s)"),
        ({"dataset": "statistics", "tickers": "MSFT,BBG000BPH459"}, "not both"),
    ],
)
async def test_equities360_rejects_inapplicable_arguments(
    fake: FakeNasdaq, make_client: ClientFactory, args: dict[str, Any], message: str
) -> None:
    _e360(fake, E360_TABLES[args["dataset"]])
    text = await _error(make_client, E360, args)
    assert "[INVALID_REQUEST]" in text and message in text
    assert fake.data_requests() == []


async def test_equities360_corporate_actions_default_window(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    actions = [("2026-09-10", "AAA"), ("2026-09-29", "BBB"), ("2026-07-01", "C")]
    _e360(fake, "NDAQ/CA", [{"date": d, "symbol": s} for d, s in actions])
    data = await _ok(make_client, E360, {"dataset": "corporate_actions"})
    assert fake.data_requests("NDAQ/CA")[0]["date.gte"] == "2026-09-02"
    assert [r[1] for r in data["rows"]] == ["BBB", "AAA"]


async def test_equities360_unidentified_rows_and_figis(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    rows = [{"symbol": f"S{i}", "figi": f"BBG00000000{i}"} for i in range(5)]
    _e360(fake, "NDAQ/STAT", rows)
    data = await _ok(make_client, E360, {"dataset": "statistics", "limit": 2})
    assert data["row_count"] == 2 and data["has_more"]
    assert "next_cursor" not in data  # the tool takes no cursor
    assert any("ndl_query_table on NDAQ/STAT" in n for n in data["notes"])
    args = {"dataset": "statistics", "tickers": "bbg000000003"}
    by_figi = await _ok(make_client, E360, args)
    sent = fake.data_requests("NDAQ/STAT")[-1]
    assert sent["figi"] == "BBG000000003" and "symbol" not in sent
    assert by_figi["row_count"] == 1
    assert not any("ndl_query_table" in n for n in by_figi["notes"])


async def test_retail_sentiment_brief_prompt(make_client: ClientFactory) -> None:
    async with make_client() as client:
        result = await client.get_prompt(
            "retail_sentiment_brief", {"tickers": "tsla,nvda", "days": "3"}
        )
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert "limit=30" in text and "['TSLA', 'NVDA']" in text


async def test_prompt_errors_reach_the_user(make_client: ClientFactory) -> None:
    from mcp import MCPError

    async with make_client() as client:
        with pytest.raises(MCPError, match="days must be"):
            await client.get_prompt("retail_sentiment_brief", {"days": "500"})
