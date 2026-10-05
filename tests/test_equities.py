"""Offline tests for the equities toolset (Sharadar + Zacks) against FakeNasdaq."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.tools import equities, table_tools
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

# Column names and filters copied from the live metadata endpoint.
SCHEMAS: dict[str, tuple[str, str]] = {
    "SHARADAR/TICKERS": (
        "table permaticker ticker name exchange isdelisted category cusips siccode "
        "sicsector sicindustry figi famaindustry sector industry scalemarketcap "
        "scalerevenue relatedtickers currency location lastupdated firstadded "
        "firstpricedate lastpricedate firstquarter lastquarter secfilings companysite",
        "lastupdated permaticker table ticker",
    ),
    "SHARADAR/SF1": (
        "ticker dimension calendardate datekey reportperiod fiscalperiod lastupdated "
        "accoci assets assetsavg assetsc assetsnc assetturnover bvps capex cashneq "
        "cashnequsd cor consolinc currentratio de debt debtc debtnc debtusd "
        "deferredrev depamor deposits divyield dps ebit ebitda ebitdamargin ebitdausd "
        "ebitusd ebt eps epsdil epsusd equity equityavg equityusd ev evebit evebitda "
        "fcf fcfps fxusd gp grossmargin intangibles intexp invcap invcapavg inventory "
        "investments investmentsc investmentsnc liabilities liabilitiesc "
        "liabilitiesnc marketcap ncf ncfbus ncfcommon ncfdebt ncfdiv ncff ncfi ncfinv "
        "ncfo ncfx netinc netinccmn netinccmnusd netincdis netincnci netmargin opex "
        "opinc payables payoutratio pb pe pe1 ppnenet prefdivis price ps ps1 "
        "receivables retearn revenue revenueusd rnd roa roe roic ros sbcomp sgna "
        "sharefactor sharesbas shareswa shareswadil sps tangibles taxassets taxexp "
        "taxliabilities tbvps workingcapital",
        "calendardate datekey dimension lastupdated reportperiod ticker",
    ),
    "SHARADAR/INDICATORS": (
        "table indicator isfilter isprimarykey title description unittype",
        "indicator isfilter isprimarykey table",
    ),
    "SHARADAR/SEP": (
        "ticker date open high low close volume closeadj closeunadj lastupdated",
        "date lastupdated ticker",
    ),
    "SHARADAR/SFP": (
        "ticker date open high low close volume closeadj closeunadj lastupdated",
        "date lastupdated ticker",
    ),
    "SHARADAR/DAILY": (
        "ticker date lastupdated ev evebit evebitda marketcap pb pe ps",
        "date lastupdated ticker",
    ),
    "SHARADAR/ACTIONS": (
        "date action ticker name value contraticker contraname",
        "action contraticker date ticker",
    ),
    "SHARADAR/SP500": (
        "date action ticker name contraticker contraname note",
        "action contraticker date ticker",
    ),
    "SHARADAR/SF2": (
        "ticker filingdate formtype issuername ownername officertitle isdirector "
        "isofficer istenpercentowner transactiondate securityadcode transactioncode "
        "sharesownedbeforetransaction transactionshares "
        "sharesownedfollowingtransaction transactionpricepershare transactionvalue "
        "securitytitle directorindirect natureofownership dateexercisable "
        "priceexercisable expirationdate rownum",
        "filingdate ownername securityadcode ticker transactionvalue",
    ),
    "SHARADAR/SF3": (
        "ticker investorid securitytype date value units",
        "investorid ticker date securitytype",
    ),
    "SHARADAR/SF3A": (
        "date ticker name shrholders cllholders putholders shrunits shrvalue "
        "totalvalue percentoftotal",
        "date ticker",
    ),
    "SHARADAR/EVENTS": (
        "ticker date eventcodes",
        "date ticker",
    ),
    "ZACKS/EE": (
        "m_ticker ticker comp_name comp_name_2 exchange currency_code per_end_date "
        "per_type eps_mean_est eps_high_est eps_low_est eps_cnt_est eps_pct_chg_est "
        "per_code per_fisc_year per_fisc_qtr per_cal_year per_cal_qtr eps_median_est "
        "eps_std_dev_est",
        "per_end_date ticker per_type",
    ),
    "ZACKS/ES": (
        "m_ticker ticker comp_name comp_name_2 exchange currency_code per_end_date "
        "per_type act_rpt_date eps_mean_est eps_act eps_amt_diff_surp "
        "eps_pct_diff_surp eps_std_dev_est eps_cnt_est eps_act_zacks_adj per_code "
        "per_fisc_year per_fisc_qtr per_cal_year per_cal_qtr act_rpt_time "
        "act_rpt_code act_rpt_desc",
        "per_end_date ticker",
    ),
    "ZACKS/AR": (
        "m_ticker ticker comp_name comp_name_2 exchange currency_code "
        "rating_cnt_strong_buys rating_cnt_buys rating_cnt_holds rating_cnt_sells "
        "rating_cnt_strong_sells rating_mean rating_mean_1m_ago rating_mean_3m_ago "
        "tp_mean_est tp_median_est tp_cnt_est tp_high_est tp_low_est last_rev_date",
        "m_ticker ticker",
    ),
}
SCHEMAS["SHARADAR/SFP"] = SCHEMAS["SHARADAR/SEP"]
SCHEMAS["SHARADAR/SF3B"] = (
    "date investorid investorname shrholders shrvalue totalvalue",
    "date investorid investorname",
)
TICKERS = "SHARADAR/TICKERS"


def columns_of(code: str) -> list[str]:
    return SCHEMAS[code][0].split()


def _cell(text: str) -> Any:
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text or None


def add(fake: FakeNasdaq, code: str, table: str = "", **kwargs: Any) -> None:
    """Register ``code`` with rows from ';'-separated lines under a header line."""
    names = columns_of(code)
    lines = table.strip().splitlines()
    header = [h.strip() for h in lines[0].split(";")] if lines else []
    assert set(header) <= set(names), set(header) - set(names)
    records = [
        dict(zip(header, map(_cell, line.split(";")), strict=True))
        for line in lines[1:]
    ]
    fake.add_table(
        code,
        columns=[(n, "text") for n in names],
        filters=SCHEMAS[code][1].split(),
        rows=[[r.get(n) for n in names] for r in records],
        **kwargs,
    )


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    return payload(await client.call_tool(tool, arguments))


async def fail(client: Client, tool: str, **arguments: Any) -> str:
    return error_text(await client.call_tool(tool, arguments))


def names_of(data: dict[str, Any]) -> list[str]:
    return [c["name"] for c in data["columns"]]


def column(data: dict[str, Any], name: str) -> list[Any]:
    i = names_of(data).index(name)
    return [r[i] for r in data["rows"]]


def metadata_requests(fake: FakeNasdaq, code: str) -> int:
    return sum(1 for r in fake.requests if r.url.path.endswith(f"/{code}/metadata"))


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    equities.clear_caches()
    yield
    equities.clear_caches()


# ------------------------------------------------------------ ticker search


def add_tickers(fake: FakeNasdaq) -> None:
    add(
        fake,
        TICKERS,
        """
        table;permaticker;ticker;name;exchange;isdelisted;category;sector;scalemarketcap;lastquarter
        SEP;100;AAPL;APPLE INC;NASDAQ;N;Common Stock;Technology;6 - Mega;
        SF1;100;AAPL;APPLE INC;NASDAQ;N;Common Stock;Technology;6 - Mega;2026-06-30
        SF2;100;AAPL;APPLE INC;;;;;;
        SEP;111;APLE;APPLE HOSPITALITY REIT INC;NYSE;N;Common Stock;Real Estate;4 - Mid;
        SEP;112;APPLB;APPLEBEES INTERNATIONAL INC;NASDAQ;Y;Common Stock;;3 - Small;
        SEP;113;AAPL1;APPLE COMPUTER OLD;NASDAQ;Y;Common Stock;;2 - Micro;
        SFP;200;VB;VANGUARD SMALL-CAP ETF;NYSEARCA;N;ETF;;;
        SEP;300;NVDA;NVIDIA CORP;NASDAQ;N;Common Stock;Technology;6 - Mega;
        """,
    )


async def test_search_tickers_exact_lookup(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add_tickers(fake)
    async with make_client() as client:
        tool = "ndl_search_tickers"
        data = await call(client, tool, tickers=["vb", "aapl", "zzzz"])
        funds = await call(client, tool, tickers="AAPL,VB", security_type="fund")
        stocks = await call(client, tool, tickers="AAPL,VB", security_type="stock")
    assert fake.data_requests(TICKERS)[0]["ticker"] == "VB,AAPL,ZZZZ"
    assert column(data, "ticker") == ["VB", "AAPL"]
    assert column(data, "tables") == ["SFP", "SF1,SEP,SF2"]
    assert column(data, "lastquarter") == [None, "2026-06-30"], "the SF1 row wins"
    assert "table" not in names_of(data)
    assert any("ZZZZ" in n for n in data["notes"])
    assert column(funds, "ticker") == ["VB"]
    assert column(stocks, "ticker") == ["AAPL"]
    assert any("VB" in n and "security_type" in n for n in stocks["notes"])


async def test_search_tickers_name_search_ranks_and_caches(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_tickers(fake)
    monkeypatch.setattr(equities, "UNIVERSE_PAGE_SIZE", 2)
    async with make_client() as client:
        tool = "ndl_search_tickers"
        first = await call(client, tool, query="Apple")
        sent = len(fake.data_requests(TICKERS))
        delisted = await call(client, tool, query="apple", include_delisted=True)
        nyse = await call(client, tool, query="apple", exchange="nyse")
        by_ticker = await call(client, tool, query="nvda")
    requests = fake.data_requests(TICKERS)
    # 5 SEP rows in pages of 2 plus 1 SFP page; later searches use the cache.
    assert sent == 4 and len(requests) == 4
    assert {r["table"] for r in requests} == {"SEP", "SFP"}
    assert metadata_requests(fake, TICKERS) == 0
    assert column(first, "ticker") == ["AAPL", "APLE"]
    assert column(first, "table") == ["SEP", "SEP"]
    assert first["request"]["security_type"] == "all"
    assert first["access"] == "free"
    # Name prefix before substring ('APPLEBEES'), listed before delisted.
    assert column(delisted, "ticker") == ["AAPL", "APLE", "AAPL1", "APPLB"]
    assert column(nyse, "ticker") == ["APLE"]
    assert column(by_ticker, "ticker") == ["NVDA"]


async def test_search_tickers_filters_without_query(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add_tickers(fake)
    async with make_client() as client:
        tech = await call(client, "ndl_search_tickers", sector="technology", limit=1)
    assert tech["row_count"] == 1 and tech["has_more"]
    assert column(tech, "ticker") == ["AAPL"]


async def test_search_tickers_does_not_cache_an_empty_list(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add(fake, TICKERS)
    async with make_client() as client:
        empty = await call(client, "ndl_search_tickers", query="apple")
        add_tickers(fake)
        found = await call(client, "ndl_search_tickers", query="apple")
    assert empty["row_count"] == 0 and empty["notes"]
    assert column(found, "ticker") == ["AAPL", "APLE"]


def test_reference_cache_is_bounded() -> None:
    newest = equities.MAX_CACHE_ENTRIES + 2
    for i in range(newest + 1):
        equities._cache_put(("https://x", True, str(i)), i)
    assert len(equities._CACHE) == equities.MAX_CACHE_ENTRIES
    assert equities._cache_get(("https://x", True, "0")) is None
    assert equities._cache_get(("https://x", True, str(newest))) == newest


def test_tools_declare_their_tables() -> None:
    mapping = table_tools(["equities"])
    assert mapping[TICKERS] == ["ndl_search_tickers"]
    assert mapping["SHARADAR/INDICATORS"] == [
        "ndl_search_financial_metrics",
        "ndl_get_company_events",
    ]
    assert mapping["SHARADAR/SFP"] == ["ndl_get_stock_prices"]
    assert {"SHARADAR/SF3", "SHARADAR/SF3B", "ZACKS/EA"} <= set(mapping)
    declared = {name for names in mapping.values() for name in names}
    assert declared == {spec.fn.__name__ for spec in equities.TOOLSET.tools}


def test_default_columns_exist() -> None:
    """Curated defaults only name columns the live metadata lists."""
    for spec in equities.ZACKS_DATASETS.values():
        if spec.code in SCHEMAS:
            assert set(spec.columns.split()) <= set(columns_of(spec.code)), spec.code
    assert set(equities.DEFAULT_SF1_METRICS) <= set(columns_of("SHARADAR/SF1"))
    tickers = set(columns_of(TICKERS))
    assert {*equities._LOOKUP_COLUMNS, *equities._UNIVERSE_COLUMNS} <= tickers


# ------------------------------------------------------------- fundamentals


async def test_fundamentals(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    add(
        fake,
        "SHARADAR/SF1",
        """
        ticker;dimension;calendardate;datekey;revenue
        AAPL;MRY;2022-12-31;2022-09-24;100
        MSFT;MRY;2023-12-31;2023-06-30;200
        AAPL;MRY;2023-12-31;2023-09-30;300
        AAPL;MRQ;2023-12-31;2023-12-30;40
        """,
        premium=True,
    )
    async with make_client() as client:
        tool, both = "ndl_get_fundamentals", ["MSFT", "AAPL"]
        data = await call(client, tool, tickers=both)
        top = await call(client, tool, tickers=both, limit=1)
        year = await call(
            client, tool, tickers="AAPL", metrics=["Revenue"], start_date="2023"
        )
        full = await call(client, tool, tickers="AAPL", metrics="all")
        bad = await fail(client, tool, tickers="AAPL", metrics="nope")
    sent = fake.data_requests("SHARADAR/SF1")
    assert sent[0]["ticker"] == "MSFT,AAPL" and sent[0]["dimension"] == "MRY"
    assert "fcf" in sent[0]["qopts.columns"]
    assert [r[0] + r[2] for r in data["rows"]] == [
        "AAPL2023-12-31",
        "MSFT2023-12-31",
        "AAPL2022-12-31",
    ]
    assert data["access"] == "sample"
    assert any("fractions" in n for n in data["notes"])
    # The limit applies after the (date desc, ticker) sort.
    assert [r[0] + r[2] for r in top["rows"]] == ["AAPL2023-12-31"] and top["has_more"]
    assert sent[2]["calendardate.gte"] == "2023-01-01"
    assert names_of(year) == [*equities._SF1_KEYS, "revenue"]
    assert column(year, "revenue") == [300]
    assert len(names_of(full)) == len(columns_of("SHARADAR/SF1"))
    assert "[INVALID_REQUEST]" in bad and "nope" in bad


@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    [
        ("ndl_search_tickers", {}, "`query`"),
        ("ndl_search_tickers", {"tickers": "AA PL"}, "AA PL"),
        ("ndl_get_fundamentals", {"tickers": []}, "at least one ticker"),
        ("ndl_get_fundamentals", {"tickers": "A", "dimension": "QQQ"}, "dimension"),
        (
            "ndl_get_fundamentals",
            {"tickers": "A", "start_date": "2024", "end_date": "2023"},
            "is after",
        ),
        ("ndl_get_corporate_actions", {"actions": ["buyback"]}, "actions"),
        ("ndl_get_sp500_constituents", {"start_date": "2020-01-01"}, "view='current'"),
        (
            "ndl_get_sp500_constituents",
            {"view": "snapshot", "as_of": "1990-01-01"},
            "1998-03-31",
        ),
        (
            "ndl_get_sp500_constituents",
            {"view": "snapshot", "as_of": "2020-02-30"},
            "real date",
        ),
        ("ndl_get_insider_transactions", {}, "owner_name"),
        ("ndl_get_institutional_holdings", {}, "start_date"),
        ("ndl_get_company_events", {"event_codes": ["x"]}, "2-digit"),
        (
            "ndl_get_analyst_estimates",
            {"tickers": "A", "dataset": "recommendations", "end_date": "2024-01-01"},
            "current snapshot",
        ),
    ],
)
async def test_bad_input_fails_before_any_request(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    tool: str,
    arguments: dict[str, Any],
    expected: str,
) -> None:
    async with make_client() as client:
        assert expected in await fail(client, tool, **arguments)
    assert fake.requests == []


async def test_search_financial_metrics(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add(
        fake,
        "SHARADAR/INDICATORS",
        """
        table;indicator;title;unittype;description
        SF1;fcf;Free Cash Flow;currency;NCFO minus capital expenditure.
        SF1;ncfo;Net Cash Flow from Operations;currency;Operating activities.
        SF1;debt;Total Debt;currency;Borrowings.
        SF1;de;Debt to Equity Ratio;ratio;Liabilities over equity.
        SEP;closeadj;Close Price - Adjusted;USD/share;Adjusted close.
        """,
    )
    async with make_client() as client:
        tool = "ndl_search_financial_metrics"
        free = await call(client, tool, query="free cash flow")
        cash = await call(client, tool, query="cash flow")
        debt = await call(client, tool, query="Debt")
        described = await call(client, tool, query="operating")
        everything = await call(client, tool, table="SEP")
        nothing = await call(client, tool, query="zzz")
    assert fake.data_requests("SHARADAR/INDICATORS")[0]["table"] == "SF1"
    assert column(free, "indicator") == ["fcf"]
    assert column(cash, "indicator") == ["fcf", "ncfo"]
    assert column(debt, "indicator") == ["debt", "de"], "exact code first"
    assert column(described, "indicator") == ["ncfo"]
    assert column(everything, "indicator") == ["closeadj"]
    assert nothing["row_count"] == 0 and nothing["notes"]
    assert metadata_requests(fake, "SHARADAR/INDICATORS") == 0


# -------------------------------------------------------- prices, valuation


async def test_stock_and_fund_prices(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    for code, ticker in (("SHARADAR/SEP", "AAPL"), ("SHARADAR/SFP", "VB")):
        add(
            fake,
            code,
            f"""
            ticker;date;close;closeadj;closeunadj;lastupdated
            {ticker};2018-12-27;39.0;38.0;156.0;2026-08-10
            {ticker};2018-12-31;39.4;38.4;157.6;2026-08-10
            {ticker};2018-12-28;39.1;38.1;156.4;2026-08-10
            """,
            premium=True,
        )
    async with make_client() as client:
        tool = "ndl_get_stock_prices"
        stock = await call(client, tool, tickers="AAPL", start_date="2018-12-28")
        fund = await call(client, tool, tickers="VB", security_type="fund")
        wrong = await call(client, tool, tickers="VB")
    assert fake.data_requests("SHARADAR/SEP")[0]["date.gte"] == "2018-12-28"
    assert column(stock, "date") == ["2018-12-31", "2018-12-28"]
    assert "lastupdated" not in names_of(stock)
    assert any("closeadj" in n for n in stock["notes"])
    assert fund["table"] == "SHARADAR/SFP"
    assert column(fund, "date")[0] == "2018-12-31"
    assert any("security_type='fund'" in n for n in wrong["notes"])


async def test_valuation_metrics(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    add(
        fake,
        "SHARADAR/DAILY",
        """
        ticker;date;marketcap;pe
        MSFT;2018-12-28;770615.6;40.9
        MSFT;2018-12-31;779673.5;41.4
        """,
        premium=True,
    )
    async with make_client() as client:
        data = await call(client, "ndl_get_valuation_metrics", tickers="MSFT")
    assert column(data, "pe") == [41.4, 40.9]
    assert names_of(data)[:3] == ["ticker", "date", "marketcap"]
    assert any("USD millions" in n for n in data["notes"])


# ---------------------------------------------- actions, S&P 500, insiders


async def test_corporate_actions(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    recent = (datetime.now(UTC).date() - timedelta(days=3)).isoformat()
    add(
        fake,
        "SHARADAR/ACTIONS",
        f"""
        date;action;ticker;value;name
        2020-08-31;split;AAPL;4.0;APPLE INC
        2024-08-12;dividend;AAPL;0.25;APPLE INC
        {recent};dividend;KO;0.51;COCA COLA CO
        """,
        premium=True,
    )
    async with make_client() as client:
        tool = "ndl_get_corporate_actions"
        aapl = await call(client, tool, tickers="AAPL", actions=["split", "dividend"])
        latest = await call(client, tool)
        window = await call(client, tool, end_date="2020-09-15")
    sent = fake.data_requests("SHARADAR/ACTIONS")
    assert sent[0]["action"] == "split,dividend"
    assert column(aapl, "date") == ["2024-08-12", "2020-08-31"]
    assert any("USD per share" in n for n in aapl["notes"])
    assert "date.gte" in sent[1] and "ticker" not in sent[1]
    assert column(latest, "ticker") == ["KO"]
    assert any("30 days" in n for n in latest["notes"])
    # Without tickers or start_date the 30-day window ends at end_date.
    assert (sent[2]["date.gte"], sent[2]["date.lte"]) == ("2020-08-16", "2020-09-15")
    assert column(window, "action") == ["split"]


async def test_sp500_views(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    add(
        fake,
        "SHARADAR/SP500",
        """
        date;action;ticker;name;contraticker;note
        2026-10-03;current;MSFT;MICROSOFT CORP;;
        2026-10-03;current;AAPL;APPLE INC;;
        2020-03-31;historical;AAPL;APPLE INC;;
        2020-08-31;added;CRM;SALESFORCE;XOM;market cap
        2020-08-31;removed;XOM;EXXON MOBIL;CRM;
        """,
        premium=True,
    )
    async with make_client() as client:
        tool = "ndl_get_sp500_constituents"
        current = await call(client, tool)
        snapshot = await call(client, tool, view="snapshot", as_of="2020-05-15")
        changes = await call(client, tool, view="changes", start_date="2020-01-01")
    sent = fake.data_requests("SHARADAR/SP500")
    assert sent[0]["action"] == "current"
    assert column(current, "ticker") == ["AAPL", "MSFT"]
    assert sent[1]["action"] == "historical" and sent[1]["date"] == "2020-03-31"
    assert column(snapshot, "ticker") == ["AAPL"]
    assert sent[2]["action"] == "added,removed"
    assert column(changes, "action") == ["added", "removed"]
    assert "note" in names_of(changes)
    assert len(sent) == 3


async def test_insider_transactions(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add(
        fake,
        "SHARADAR/SF2",
        """
        ticker;filingdate;ownername;securityadcode;transactioncode;transactionshares
        AAPL;2018-11-21;DOE JOHN;ND;S;-3000
        AAPL;2018-11-15;ROE JANE;ND;F;-7000
        AAPL;2018-11-15;ROE JANE;N;;
        """,
        premium=True,
    )
    async with make_client() as client:
        tool = "ndl_get_insider_transactions"
        data = await call(client, tool, tickers="AAPL")
        holdings = await call(
            client,
            tool,
            owner_name="roe jane",
            transactions_only=False,
            security="non_derivative",
        )
    sent = fake.data_requests("SHARADAR/SF2")
    assert sent[0]["securityadcode"] == "NA,ND,DA,DD"
    assert column(data, "filingdate") == ["2018-11-21", "2018-11-15"]
    assert any("S sale" in n for n in data["notes"])
    assert sent[1]["ownername"] == "ROE JANE"
    assert sent[1]["securityadcode"] == "N,NA,ND"
    assert holdings["row_count"] == 2


# --------------------------------------------------------- 13F, 8-K events


async def test_institutional_holdings(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    for code in ("SHARADAR/SF3", "SHARADAR/SF3B"):
        add(fake, code, premium=True, forbidden=True)
    add(
        fake,
        "SHARADAR/SF3A",
        """
        date;ticker;totalvalue
        2024-12-31;MSFT;2.0
        2024-12-31;AAPL;3.0
        2024-09-30;AAPL;2.5
        """,
        premium=True,
    )
    async with make_client() as client:
        tool = "ndl_get_institutional_holdings"
        denied = await fail(
            client, tool, dataset="holdings", tickers="AAPL", security_type="SHR"
        )
        quarter = await call(
            client, tool, start_date="2024-12-31", end_date="2024-12-31"
        )
        history = await call(client, tool, tickers=["AAPL", "MSFT"])
        wrong = await fail(client, tool, dataset="by_investor", tickers="AAPL")
    assert "[SUBSCRIPTION]" in denied and "ZACKS/IHC" in denied
    assert fake.data_requests("SHARADAR/SF3")[0]["securitytype"] == "SHR"
    assert column(quarter, "ticker") == ["AAPL", "MSFT"]
    assert column(history, "date") == ["2024-12-31", "2024-12-31", "2024-09-30"]
    assert column(history, "ticker")[:2] == ["AAPL", "MSFT"]
    assert "[INVALID_REQUEST]" in wrong and "'ticker' cannot be used" in wrong


async def test_company_events_are_decoded(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    add(
        fake,
        "SHARADAR/EVENTS",
        """
        ticker;date;eventcodes
        AAPL;2026-07-30;22|91
        AAPL;2026-09-01;52
        AAPL;2026-04-29;34
        """,
    )
    add(
        fake,
        "SHARADAR/INDICATORS",
        """
        table;indicator;title
        EVENTCODES;22;Results label
        EVENTCODES;52;Officers label
        EVENTCODES;91;Exhibits label
        """,
    )
    async with make_client() as client:
        tool = "ndl_get_company_events"
        data = await call(client, tool, tickers="AAPL")
        first = await call(client, tool, tickers="AAPL", event_codes=["22"], limit=1)
        window = await call(client, tool, end_date="2026-08-01")
    assert column(data, "date") == ["2026-09-01", "2026-07-30", "2026-04-29"]
    assert column(data, "events") == [
        "Officers label",
        "Results label; Exhibits label",
        "code 34",
    ]
    # event_codes is applied before the limit, so the newest '22' filing shows.
    assert column(first, "date") == ["2026-07-30"]
    assert first["request"]["event_codes"] == ["22"] and not first["has_more"]
    assert fake.data_requests("SHARADAR/EVENTS")[2]["date.gte"] == "2026-07-02"
    assert column(window, "date") == ["2026-07-30"]
    labels = fake.data_requests("SHARADAR/INDICATORS")
    assert len(labels) == 1 and labels[0]["table"] == "EVENTCODES", "cached"
    assert metadata_requests(fake, "SHARADAR/INDICATORS") == 0


# -------------------------------------------------------- analyst estimates


async def test_analyst_estimates(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    add(
        fake,
        "ZACKS/EE",
        """
        m_ticker;ticker;comp_name;per_end_date;per_type;eps_mean_est
        AAPL;AAPL;Apple;2027-09-30;A;9.5
        AAPL;AAPL;Apple;2026-09-30;A;8.7
        AAPL;AAPL;Apple;2026-12-31;Q;2.9
        AAPL;AAPL;Apple;2026-09-30;Q;1.98
        """,
        premium=True,
    )
    add(
        fake,
        "ZACKS/ES",
        """
        ticker;per_end_date;per_type;eps_act;eps_mean_est;eps_pct_diff_surp
        MSFT;2018-09-30;Q;1.14;0.96;18.75
        MSFT;2018-12-31;Q;1.1;1.09;0.92
        """,
        premium=True,
    )
    add(
        fake,
        "ZACKS/AR",
        """
        m_ticker;ticker;rating_mean;tp_mean_est
        AAPL;AAPL;2.04;331.6
        GS&;GS;2.5;700.0
        """,
        premium=True,
    )
    async with make_client() as client:
        tool = "ndl_get_analyst_estimates"
        estimates = await call(client, tool, tickers="AAPL")
        annual = await call(client, tool, tickers="AAPL", period_type="annual")
        surprises = await call(
            client,
            tool,
            tickers="MSFT",
            dataset="eps_surprises",
            period_type="quarterly",
            start_date="2018-07-01",
        )
        ratings = await call(
            client, tool, tickers=["GS", "AAPL"], dataset="recommendations"
        )
    assert [(r[2], r[3]) for r in estimates["rows"]] == [
        ("2026-09-30", "A"),
        ("2026-09-30", "Q"),
        ("2026-12-31", "Q"),
        ("2027-09-30", "A"),
    ]
    assert any("BNRI" in n for n in estimates["notes"])
    sent = fake.data_requests("ZACKS/EE")
    assert "per_type" not in sent[0] and sent[1]["per_type"] == "A"
    assert set(column(annual, "per_type")) == {"A"}
    es_sent = fake.data_requests("ZACKS/ES")[0]
    assert es_sent["per_end_date.gte"] == "2018-07-01" and "per_type" not in es_sent
    assert column(surprises, "per_end_date") == ["2018-12-31", "2018-09-30"]
    assert any("period_type does not apply" in n for n in surprises["notes"])
    assert fake.data_requests("ZACKS/AR")[0]["ticker"] == "GS,AAPL"
    assert column(ratings, "ticker") == ["AAPL", "GS"]
    assert "m_ticker" not in names_of(ratings)


async def test_company_snapshot_prompt(make_client: ClientFactory) -> None:
    async with make_client() as client:
        listed = {p.name for p in (await client.list_prompts()).prompts}
        result = await client.get_prompt("company_snapshot", {"ticker": "msft"})
    assert "company_snapshot" in listed
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert 'tickers="MSFT"' in text
    assert "ndl_get_analyst_estimates" in text
