"""US equities from Sharadar and Zacks: tickers, fundamentals, prices, estimates.

Sharadar tables (SHARADAR/*) cover US stocks and funds: the ticker master
(TICKERS), fundamentals (SF1), prices (SEP stocks, SFP funds), daily valuation
ratios (DAILY), corporate actions (ACTIONS), S&P 500 membership (SP500), 8-K
events (EVENTS), insider filings (SF2) and 13F holdings (SF3*). Zacks tables
(ZACKS/*) add consensus estimates, surprises and ratings. Every tool except the
ndl_search_tickers name search takes exact ticker symbols.

A free key reads TICKERS and INDICATORS in full, a fixed sample from most other
tables, and nothing from SF3/SF3A/SF3B.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import Field

from nasdaq_data_link_mcp_os.client import MAX_PAGE_SIZE
from nasdaq_data_link_mcp_os.errors import (
    InvalidRequestError,
    SubscriptionRequiredError,
)
from nasdaq_data_link_mcp_os.query import check_date, sort_rows_by
from nasdaq_data_link_mcp_os.results import ColumnInfo, TableResult, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    DATE_PATTERN,
    EndDateArg,
    EndYearOrDateArg,
    LimitArg,
    OptionalTickersArg,
    PromptSpec,
    StartDateArg,
    StartYearOrDateArg,
    TableRead,
    TickersArg,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    fetch_table,
    period_bounds,
    read_table,
)

TICKERS_TABLE = "SHARADAR/TICKERS"
INDICATORS_TABLE = "SHARADAR/INDICATORS"
DAILY = "SHARADAR/DAILY"
ACTIONS = "SHARADAR/ACTIONS"
SP500 = "SHARADAR/SP500"
SF2 = "SHARADAR/SF2"
EVENTS = "SHARADAR/EVENTS"

MAX_TICKERS = 100
RECENT_DAYS = 30
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-_/^&]{0,19}$")
_WORD_RE = re.compile(r"[a-z0-9]+")

# Reference lists (ticker universes, 8-K code titles) cached for 24 hours.
# Keys hold the base URL, whether a key is configured and the list name, never
# the key itself; at most MAX_CACHE_ENTRIES entries.
REFERENCE_TTL_SECONDS = 24 * 3600.0
MAX_CACHE_ENTRIES = 8
UNIVERSE_PAGE_SIZE = MAX_PAGE_SIZE
MAX_UNIVERSE_PAGES = 8
_CacheKey = tuple[str, bool, str]
_CACHE: dict[_CacheKey, tuple[float, Any]] = {}


def clear_caches() -> None:
    _CACHE.clear()


def _cache_key(ctx: Context, name: str) -> _CacheKey:
    settings = app_state(ctx).settings
    return (settings.base_url, settings.has_api_key, name)


def _cache_get(key: _CacheKey) -> Any:
    hit = _CACHE.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None


def _cache_put(key: _CacheKey, value: Any) -> None:
    _CACHE.pop(key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic() + REFERENCE_TTL_SECONDS, value)


# ------------------------------------------------------------------ helpers


def _tickers(value: str | Sequence[str] | None, *, required: bool) -> list[str]:
    items = as_list(value)
    if required and not items:
        raise InvalidRequestError(
            "Pass at least one ticker, e.g. 'AAPL' or ['AAPL', 'MSFT']. "
            "ndl_search_tickers finds tickers by company name."
        )
    if len(items) > MAX_TICKERS:
        raise InvalidRequestError(
            f"{len(items)} tickers given; at most {MAX_TICKERS} per call."
        )
    bad = [t for t in items if not _TICKER_RE.match(t)]
    if bad:
        raise InvalidRequestError(
            f"Not a ticker symbol: {', '.join(bad)}. ndl_search_tickers with "
            "`query` finds tickers by company name."
        )
    return items


def _recent_start(end_date: str | None) -> str:
    """Start of the default 30-day window, ending at end_date or today."""
    end = date.fromisoformat(check_date("end_date", end_date)) if end_date else None
    return ((end or datetime.now(UTC).date()) - timedelta(days=RECENT_DAYS)).isoformat()


def _column_list(
    value: str | Sequence[str] | None, default: Sequence[str], keep: Sequence[str]
) -> list[str] | None:
    """Columns to request: the default subset, the caller's list, or all (None)."""
    items = [i.lower() for i in as_list(value, upper=False)]
    if items == ["all"]:
        return None
    if not items:
        return list(default)
    return list(dict.fromkeys([*keep, *items]))


def _with_note(result: TableResult, note: str) -> TableResult:
    return result.model_copy(update={"notes": [*result.notes, note]})


def _norm(text: Any) -> str:
    return " ".join(_WORD_RE.findall(str(text or "").lower()))


def _has_words(query: str, text: str) -> bool:
    """Every word of a normalized query occurs in the normalized text."""
    return all(word in text for word in query.split())


# ------------------------------------------------------- 1. ticker search

SecurityType = Literal["all", "stock", "fund"]
_UNIVERSE_TABLES = {"all": ("SEP", "SFP"), "stock": ("SEP",), "fund": ("SFP",)}
# Tables an exact lookup must find a security in, per security_type.
_REQUIRED_TABLES = {"stock": {"SF1", "SEP"}, "fund": {"SFP"}}
# The row that describes a security listed in several Sharadar tables.
_TABLE_ORDER = {"SF1": 0, "SEP": 1, "SFP": 2}
_LOOKUP_COLUMNS = (
    "table permaticker ticker name exchange isdelisted category sector industry "
    "sicindustry scalemarketcap scalerevenue currency location firstpricedate "
    "lastpricedate firstquarter lastquarter relatedtickers secfilings companysite"
).split()
_UNIVERSE_COLUMNS = (
    "ticker name exchange category sector industry scalemarketcap isdelisted "
    "lastpricedate permaticker"
).split()


def _match(query: str, ticker: str, name: str) -> int:
    """3: the ticker itself, 2: the name starts with the query, 1: the name
    contains every query word, 0: no match (case and punctuation ignored)."""
    if ticker == query.strip().upper():
        return 3
    q, n = _norm(query), _norm(name)
    if not q or not _has_words(q, n):
        return 0
    return 2 if f"{n} ".startswith(f"{q} ") else 1


def _scale(value: Any) -> int:
    """'6 - Mega' -> 6; unknown -> 0."""
    head = str(value or "").split(" ", 1)[0]
    return int(head) if head.isdigit() else 0


def _attribute_filter(
    exchange: str | None, category: str | None, sector: str | None
) -> Callable[[Mapping[str, Any]], bool] | None:
    """Exact exchange, category/sector substring (Nasdaq cannot filter these)."""
    pairs = (("exchange", exchange), ("category", category), ("sector", sector))
    wanted = {column: v.strip().lower() for column, v in pairs if v and v.strip()}
    if not wanted:
        return None

    def keep(record: Mapping[str, Any]) -> bool:
        text = {column: str(record.get(column) or "").lower() for column in wanted}
        return all(
            text[column] == value if column == "exchange" else value in text[column]
            for column, value in wanted.items()
        )

    return keep


async def _universe(ctx: Context, table: str) -> TableRead:
    """SHARADAR/TICKERS rows of one Sharadar table, cached for 24 hours."""
    key = _cache_key(ctx, table)
    cached: TableRead | None = _cache_get(key)
    if cached is not None:
        return cached
    read = await read_table(
        ctx,
        TICKERS_TABLE,
        filters={"table": table},
        columns=_UNIVERSE_COLUMNS,
        page_size=UNIVERSE_PAGE_SIZE,
        max_pages=MAX_UNIVERSE_PAGES,
        use_cache=False,
        validate=False,
    )
    if read.rows:
        _cache_put(key, read)
    return read


async def _lookup_exact(
    ctx: Context,
    tickers: list[str],
    security_type: str,
    keep: Callable[[Mapping[str, Any]], bool] | None,
) -> TableResult:
    read = await read_table(
        ctx,
        TICKERS_TABLE,
        filters={"ticker": tickers},
        columns=_LOOKUP_COLUMNS,
        page_size=1000,
    )
    groups: dict[Any, list[dict[str, Any]]] = {}
    for record in read.records():
        groups.setdefault(record.get("permaticker"), []).append(record)
    required = _REQUIRED_TABLES.get(security_type)
    columns = [c for c in read.columns if c.name != "table"]
    columns.append(ColumnInfo(name="tables", type="text"))
    out: list[list[Any]] = []
    for records in groups.values():
        in_tables = sorted(
            {str(r.get("table")) for r in records},
            key=lambda t: (_TABLE_ORDER.get(t, len(_TABLE_ORDER)), t),
        )
        best = next(r for r in records if str(r.get("table")) == in_tables[0])
        if required and not required.intersection(in_tables):
            continue
        if keep is not None and not keep(best):
            continue
        best["tables"] = ",".join(in_tables)
        out.append([best.get(c.name) for c in columns])
    at = [c.name for c in columns].index("ticker")
    order = {symbol: i for i, symbol in enumerate(tickers)}
    out.sort(key=lambda r: (order.get(str(r[at]), len(order)), str(r[at])))
    notes = [
        "One row per security (permaticker). `tables` lists the Sharadar tables "
        "that carry it: SF1 fundamentals, SEP stock prices, SFP fund prices, SF2 "
        "insider filings. A delisted company whose ticker was reused carries a "
        "numeric suffix (e.g. 'ABC1')."
    ]
    found = {str(r[at]) for r in out}
    missing = [symbol for symbol in tickers if symbol not in found]
    if missing:
        narrowed = " with this security_type and filters" if keep or required else ""
        notes.append(
            f"No security found for {', '.join(missing)}{narrowed}. `query` "
            "searches by name."
        )
    return build_result(
        ctx,
        read,
        out,
        limit=max(1, len(out)),
        columns=columns,
        notes=notes,
        count_note=False,
    )


async def ndl_search_tickers(
    ctx: Context,
    tickers: OptionalTickersArg = None,
    query: Annotated[
        str | None,
        Field(description="Company or fund name words, e.g. 'nvidia'.", max_length=100),
    ] = None,
    security_type: Annotated[
        SecurityType,
        Field(description="stock: SEP/SF1; fund: ETFs, CEFs, ETNs (SFP); all: both."),
    ] = "all",
    exchange: Annotated[
        str | None,
        Field(
            description="Exact exchange, e.g. NASDAQ, NYSE, NYSEARCA.", max_length=20
        ),
    ] = None,
    category: Annotated[
        str | None,
        Field(description="Category substring, e.g. 'ADR' or 'ETF'.", max_length=100),
    ] = None,
    sector: Annotated[
        str | None,
        Field(description="Sector substring, e.g. 'Technology'.", max_length=100),
    ] = None,
    include_delisted: Annotated[
        bool, Field(description="Include delisted securities in searches.")
    ] = False,
    limit: Annotated[
        int, Field(ge=1, le=200, description="Maximum securities from a search.")
    ] = 20,
) -> Annotated[CallToolResult, TableResult]:
    """Find US stocks and ETFs by ticker or company name (free Sharadar ticker master).

    SHARADAR/TICKERS, free and current, delisted securities included. `tickers`
    gives one row per security: exchange, sector, industry, market-cap scale,
    date ranges and `tables` (the Sharadar tables that carry it). `query`
    matches a ticker exactly or names containing every query word, over ticker
    lists downloaded once (about 4 calls) and cached for 24 hours.
    """
    symbols = _tickers(tickers, required=False)
    query = (query or "").strip() or None
    keep = _attribute_filter(exchange, category, sector)
    if symbols:
        return to_tool_result(await _lookup_exact(ctx, symbols, security_type, keep))
    if not (query or keep):
        raise InvalidRequestError(
            "Pass `tickers` (exact symbols) or `query` (name words), optionally with "
            "exchange, category or sector filters."
        )
    tables = _UNIVERSE_TABLES[security_type]
    reads = [await _universe(ctx, table) for table in tables]
    ranked: list[tuple[tuple[int, int, int, int, str], list[Any]]] = []
    for table, read in zip(tables, reads, strict=True):
        for row, record in zip(read.rows, read.records(), strict=True):
            ticker = str(record.get("ticker") or "")
            name = str(record.get("name") or "")
            delisted = record.get("isdelisted") == "Y"
            if (delisted and not include_delisted) or (keep and not keep(record)):
                continue
            match = _match(query, ticker, name) if query else 1
            if match:
                scale = _scale(record.get("scalemarketcap"))
                rank = (-match, int(delisted), -scale, len(name), ticker)
                ranked.append((rank, [*row, table]))
    ranked.sort(key=lambda item: item[0])
    notes = [
        f"Name search over the SHARADAR/TICKERS lists of {' and '.join(tables)}, "
        "cached for 24 hours. Exact `tickers` lookups add details such as SF1 "
        "coverage, related tickers and the SEC filings link."
    ]
    if not ranked:
        notes.append(
            "No security matched. Fewer words, include_delisted=true or "
            "security_type='all' widen the search."
        )
    request = {
        "query": query,
        "security_type": security_type,
        "exchange": exchange,
        "category": category,
        "sector": sector,
        "include_delisted": include_delisted,
    }
    result = build_result(
        ctx,
        next((r for r in reads if r.next_cursor), reads[0]),
        [row for _, row in ranked],
        limit=limit,
        columns=[*reads[0].columns, ColumnInfo(name="table", type="text")],
        notes=notes,
        request={k: v for k, v in request.items() if v is not None},
    )
    return to_tool_result(result)


# --------------------------------------------------------- 2. fundamentals

SF1 = "SHARADAR/SF1"
Dimension = Literal["MRY", "MRQ", "MRT", "ARY", "ARQ", "ART"]
_SF1_KEYS = tuple(
    "ticker dimension calendardate datekey reportperiod fiscalperiod".split()
)
DEFAULT_SF1_METRICS = tuple(
    "revenue gp opinc ebitda netinc eps epsdil ncfo capex fcf assets liabilities "
    "equity debt cashneq sharesbas marketcap ev pe pb ps evebitda grossmargin "
    "netmargin roe roic de currentratio dps divyield".split()
)
SF1_UNITS_NOTE = (
    "Amounts are in the reporting currency in whole units (not thousands); "
    "fields ending in 'usd' are converted to USD. Margins, returns (roe, roic) "
    "and divyield are fractions (0.25 = 25%). MR* dimensions include "
    "restatements and are keyed to the fiscal period; AR* are as first filed "
    "and datekey is the SEC filing date. Y = annual, Q = quarterly, T = "
    "trailing twelve months. ndl_search_financial_metrics defines every field."
)


async def ndl_get_fundamentals(
    ctx: Context,
    tickers: TickersArg,
    dimension: Annotated[
        Dimension,
        Field(
            description="MR*: restated; AR*: as first reported. Y annual, Q "
            "quarterly, T trailing 12 months."
        ),
    ] = "MRY",
    start_date: StartYearOrDateArg = None,
    end_date: EndYearOrDateArg = None,
    date_field: Annotated[
        Literal["calendardate", "datekey", "reportperiod"],
        Field(description="Date the range filters (datekey: filing date for AR*)."),
    ] = "calendardate",
    metrics: Annotated[
        str | list[str] | None,
        Field(
            description="SF1 field codes to add to the date keys, e.g. "
            "['revenue', 'fcf'], or 'all' (default: 30 common fields)."
        ),
    ] = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get income statement, balance sheet, cash flow and ratio data from Sharadar SF1.

    About 105 fields per US company and period, newest first (definitions:
    ndl_search_financial_metrics). Free key: a fixed sample (about 30 large US
    companies, a few years).
    """
    symbols = _tickers(tickers, required=True)
    columns = _column_list(metrics, (*_SF1_KEYS, *DEFAULT_SF1_METRICS), _SF1_KEYS)
    start, end = period_bounds(start_date, end_date)
    filters: dict[str, Any] = {"ticker": symbols, "dimension": dimension}
    filters.update(date_range(date_field, start, end))
    result = await fetch_table(
        ctx,
        SF1,
        filters=filters,
        columns=columns,
        limit=limit,
        sort_by=[(date_field, True), ("ticker", False)],
        scan_size=300 * len(symbols),
        notes=[SF1_UNITS_NOTE],
    )
    return to_tool_result(result)


# ------------------------------------------------- 3. metric definitions

IndicatorTable = Literal[
    "SF1",
    "DAILY",
    "SEP",
    "SFP",
    "METRICS",
    "TICKERS",
    "ACTIONS",
    "ACTIONTYPES",
    "SP500",
    "EVENTS",
    "EVENTCODES",
    "SF2",
    "SF3",
    "SF3A",
    "SF3B",
    "INDICATORS",
    "TABLE-DESCRIPTIONS",
]
_INDICATOR_COLUMNS = (
    "indicator title unittype isfilter isprimarykey description".split()
)


async def ndl_search_financial_metrics(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description="Words in field codes, titles or definitions.", max_length=100
        ),
    ] = "",
    table: Annotated[
        IndicatorTable,
        Field(
            description="Table whose fields to list (EVENTCODES, ACTIONTYPES: codes)."
        ),
    ] = "SF1",
    limit: Annotated[
        int, Field(ge=1, le=200, description="Maximum fields to return.")
    ] = 30,
) -> Annotated[CallToolResult, TableResult]:
    """Search the Sharadar data dictionary for field codes, titles, units and meaning.

    Reads SHARADAR/INDICATORS (free, full) for one table: each field's code (the
    column name to pass as `metrics` to ndl_get_fundamentals), title, unit
    type, whether it is filterable, and its definition; an empty query lists
    them all. Also decodes the 8-K event codes (EVENTCODES) and corporate action
    types (ACTIONTYPES).
    """
    read = await read_table(
        ctx,
        INDICATORS_TABLE,
        filters={"table": table},
        columns=_INDICATOR_COLUMNS,
        page_size=1000,
        validate=False,
    )
    q = _norm(query)
    ranked: list[tuple[int, str, list[Any]]] = []
    for row, record in zip(read.rows, read.records(), strict=True):
        code = str(record.get("indicator") or "")
        title = _norm(record.get("title"))
        if not q:
            rank = 0
        elif code.lower() == q.replace(" ", ""):
            rank = -3
        elif _has_words(q, title):
            rank = -2
        elif _has_words(
            q, f"{code.lower()} {title} {_norm(record.get('description'))}"
        ):
            rank = -1
        else:
            continue
        ranked.append((rank, code, row))
    ranked.sort(key=lambda item: item[:2])
    notes = []
    if not ranked:
        notes.append(
            f"No {table} field matched {query!r}. An empty query lists every field."
        )
    result = build_result(
        ctx,
        read,
        [row for *_, row in ranked],
        limit=limit,
        notes=notes,
        request={**read.request, "query": query},
    )
    return to_tool_result(result)


# ------------------------------------------------------------- 4. prices

_PRICE_TABLES = {"stock": "SHARADAR/SEP", "fund": "SHARADAR/SFP"}
_PRICE_COLUMNS = "ticker date open high low close volume closeadj closeunadj".split()
PRICE_NOTE = (
    "open/high/low/close and volume are adjusted for splits and stock dividends "
    "only; closeadj is also adjusted for cash dividends and spinoffs (use it for "
    "total-return calculations); closeunadj is the price as printed that day."
)
_NEWEST_FIRST = [("date", True), ("ticker", False)]


async def ndl_get_stock_prices(
    ctx: Context,
    tickers: TickersArg,
    security_type: Annotated[
        Literal["stock", "fund"],
        Field(description="stock: SEP (stocks, ADRs); fund: SFP (ETFs, CEFs, ETNs)."),
    ] = "stock",
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get daily open/high/low/close/volume for US stocks (SEP) or funds and ETFs (SFP).

    `close` is split-adjusted, `closeadj` also adjusts for dividends and
    spinoffs, and `closeunadj` is as traded. Newest first; without dates, the
    latest rows. A free key gets a fixed sample of large stocks and funds over
    a past date window. ndl_search_tickers tells whether a symbol is a stock or
    a fund.
    """
    symbols = _tickers(tickers, required=True)
    code = _PRICE_TABLES[security_type]
    filters: dict[str, Any] = {"ticker": symbols}
    filters.update(date_range("date", start_date, end_date))
    result = await fetch_table(
        ctx,
        code,
        filters=filters,
        columns=_PRICE_COLUMNS,
        limit=limit,
        sort_by=_NEWEST_FIRST,
        notes=[PRICE_NOTE],
    )
    if not result.rows:
        other = "fund" if security_type == "stock" else "stock"
        result = _with_note(
            result,
            f"No rows in {code}. For a {other}, security_type='{other}' reads "
            f"{_PRICE_TABLES[other]}.",
        )
    return to_tool_result(result)


# ---------------------------------------------------------- 5. valuation

_DAILY_COLUMNS = "ticker date marketcap ev pe pb ps evebit evebitda".split()
DAILY_NOTE = (
    "marketcap and ev are in USD millions. pe, pb, ps, evebit and evebitda "
    "divide the day's market cap or EV by figures from the most recent SEC "
    "10-K/10-Q filing; negative earnings give negative ratios."
)


async def ndl_get_valuation_metrics(
    ctx: Context,
    tickers: TickersArg,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get daily market cap, enterprise value and P/E, P/B, P/S, EV/EBIT, EV/EBITDA.

    Reads SHARADAR/DAILY: one row per US stock and trading day, combining the
    close price with the latest reported fundamentals. Rows come back newest
    first. A free key gets a fixed sample of large US companies over a past
    date window. Reported (quarterly/annual) ratios are in ndl_get_fundamentals.
    """
    symbols = _tickers(tickers, required=True)
    filters: dict[str, Any] = {"ticker": symbols}
    filters.update(date_range("date", start_date, end_date))
    result = await fetch_table(
        ctx,
        DAILY,
        filters=filters,
        columns=_DAILY_COLUMNS,
        limit=limit,
        sort_by=_NEWEST_FIRST,
        notes=[DAILY_NOTE],
    )
    return to_tool_result(result)


# --------------------------------------------------- 6. corporate actions

ActionType = Literal[
    "dividend",
    "split",
    "spinoff",
    "spinoffdividend",
    "spunofffrom",
    "acquisitionby",
    "acquisitionof",
    "acquisitioncash",
    "acquisitionstock",
    "acquisitionelectcash",
    "acquisitionelectstock",
    "mergerfrom",
    "mergerto",
    "spacmerger",
    "spacunitseparation",
    "listed",
    "initiated",
    "delisted",
    "voluntarydelisting",
    "regulatorydelisting",
    "bankruptcyliquidation",
    "tickerchangefrom",
    "tickerchangeto",
    "namechangefrom",
    "namechangeto",
    "exchangefrom",
    "exchangeto",
    "sicchangefrom",
    "sicchangeto",
    "relation",
    "adrratiosplit",
]
_ACTION_COLUMNS = "date ticker action value contraticker contraname name".split()
ACTIONS_NOTE = (
    "`value` depends on the action: USD per share for dividends (dated on the "
    "ex-date) and cash considerations; new shares per old share for splits, "
    "spinoffs and stock considerations; market cap in USD millions for "
    "listings, delistings, acquisitions and mergers. contraticker/contraname "
    "name the other company, or the old or new ticker, name or exchange. "
    "ndl_search_financial_metrics(table='ACTIONTYPES') defines every action."
)


async def ndl_get_corporate_actions(
    ctx: Context,
    tickers: OptionalTickersArg = None,
    actions: Annotated[
        list[ActionType] | None,
        Field(description="Action types (default: all)."),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get dividends, splits, M&A, ticker changes and delistings (SHARADAR/ACTIONS).

    Newest first; without tickers or start_date, the last 30 days. Free key:
    about 30 large US companies, all dates. ndl_get_ticker_changes (free) has
    symbol changes for all US tickers.
    """
    symbols = _tickers(tickers, required=False)
    notes = [ACTIONS_NOTE]
    if not symbols and not start_date:
        start_date = _recent_start(end_date)
        notes.append(
            f"No tickers or start_date given: showing the 30 days from {start_date}."
        )
    filters: dict[str, Any] = {"ticker": symbols, "action": actions}
    filters = {k: list(dict.fromkeys(v)) for k, v in filters.items() if v}
    filters.update(date_range("date", start_date, end_date))
    result = await fetch_table(
        ctx,
        ACTIONS,
        filters=filters,
        columns=_ACTION_COLUMNS,
        limit=limit,
        sort_by=_NEWEST_FIRST,
        notes=notes,
    )
    return to_tool_result(result)


# ----------------------------------------------------------- 7. S&P 500

FIRST_SP500_SNAPSHOT = date(1998, 3, 31)


def _quarter_end_on_or_before(day: date) -> date:
    for month, last in ((12, 31), (9, 30), (6, 30), (3, 31)):
        candidate = date(day.year, month, last)
        if candidate <= day:
            return candidate
    return date(day.year - 1, 12, 31)


async def ndl_get_sp500_constituents(
    ctx: Context,
    view: Annotated[
        Literal["current", "changes", "snapshot"],
        Field(
            description="current: today's members; changes: additions and "
            "removals, newest first; snapshot: members at the quarter-end on or "
            "before as_of (from 1998-03-31)."
        ),
    ] = "current",
    tickers: OptionalTickersArg = None,
    as_of: Annotated[
        str | None,
        Field(description="Snapshot date (default: today).", pattern=DATE_PATTERN),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: Annotated[
        int | None,
        Field(
            ge=1, le=1000, description="Maximum rows (default 600; 100 for changes)."
        ),
    ] = None,
) -> Annotated[CallToolResult, TableResult]:
    """List S&P 500 members now, at a past quarter-end, or the history of index changes.

    Reads SHARADAR/SP500. 'changes' rows give the effective date, the ticker
    added or removed, the paired ticker (contraticker) and the stated reason
    (note). A free key gets current data and full history for the sample
    tickers only, so 'current' lists a few dozen of the ~500 members.
    """
    symbols = _tickers(tickers, required=False)
    filters: dict[str, Any] = {"ticker": symbols} if symbols else {}
    columns = ["date", "ticker", "name"]
    sort = [("ticker", False)]
    if (
        (view == "current" and (start_date or end_date or as_of))
        or (view == "snapshot" and (start_date or end_date))
        or (view == "changes" and as_of)
    ):
        raise InvalidRequestError(
            "view='current' takes no dates, view='snapshot' takes as_of and "
            "view='changes' takes start_date/end_date."
        )
    if view == "current":
        filters["action"] = "current"
        note = "`date` is Sharadar's last refresh date."
    elif view == "snapshot":
        day = datetime.now(UTC).date()
        if as_of:
            day = date.fromisoformat(check_date("as_of", as_of))
        quarter = _quarter_end_on_or_before(day)
        if quarter < FIRST_SP500_SNAPSHOT:
            raise InvalidRequestError(
                "Quarter-end snapshots start at 1998-03-31; use view='changes' for "
                "earlier membership history."
            )
        filters["action"] = "historical"
        filters["date"] = quarter.isoformat()
        note = f"Members as of the quarter-end snapshot {quarter.isoformat()}."
    else:
        filters["action"] = ["added", "removed"]
        filters.update(date_range("date", start_date, end_date))
        columns = "date action ticker name contraticker contraname note".split()
        sort = [("date", True), ("action", False), ("ticker", False)]
        note = (
            "`date` is the effective membership date; contraticker is the security "
            "removed (for 'added') or added (for 'removed') in the same change."
        )
    result = await fetch_table(
        ctx,
        SP500,
        filters=filters,
        columns=columns,
        limit=limit or (100 if view == "changes" else 600),
        sort_by=sort,
        notes=[note],
    )
    if view == "snapshot" and not result.rows:
        result = _with_note(
            result,
            "No snapshot rows: a new quarter-end snapshot can take a few days to "
            "appear; an earlier as_of reads the previous one.",
        )
    return to_tool_result(result)


# -------------------------------------------------------------- 8. insiders

# securityadcode values per (security, transactions_only); None: no filter.
_SECURITY_CODES = {
    ("non_derivative", True): ["NA", "ND"],
    ("non_derivative", False): ["N", "NA", "ND"],
    ("derivative", True): ["DA", "DD"],
    ("derivative", False): ["D", "DA", "DD"],
    ("all", True): ["NA", "ND", "DA", "DD"],
    ("all", False): None,
}
_SF2_COLUMNS = (
    "ticker filingdate formtype ownername officertitle isdirector isofficer "
    "istenpercentowner transactiondate securityadcode transactioncode "
    "transactionshares transactionpricepershare transactionvalue "
    "sharesownedfollowingtransaction securitytitle directorindirect"
).split()
SF2_NOTE = (
    "securityadcode: NA/ND = non-derivative acquisition/disposition, DA/DD = "
    "derivative acquisition/disposition, N/D = holding with no transaction. "
    "transactioncode is the SEC Form 4 code: P purchase, S sale, A grant, M or "
    "X option exercise, F shares withheld for tax, G gift, J other. "
    "transactionshares is negative for disposals; transactionvalue is in USD."
)


async def ndl_get_insider_transactions(
    ctx: Context,
    tickers: OptionalTickersArg = None,
    owner_name: Annotated[
        str | None,
        Field(description="Insider name as filed, last name first.", max_length=100),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    security: Annotated[
        Literal["all", "non_derivative", "derivative"],
        Field(description="Non-derivative (shares), derivative (options, RSUs), all."),
    ] = "all",
    transactions_only: Annotated[
        bool,
        Field(description="Drop holding-only rows that report no transaction."),
    ] = True,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get insider purchases, sales, grants and holdings from SEC Forms 3/4/5 (SF2).

    Reads SHARADAR/SF2, newest filing first: owner, role, transaction code
    (P = purchase, S = sale, A = grant, M = exercise, F = tax withholding...),
    shares, price, value and shares held afterwards. Dates filter on the SEC
    filing date. A free key gets a fixed sample of large US companies over a
    past filing window.
    """
    symbols = _tickers(tickers, required=False)
    owner = (owner_name or "").strip().upper() or None
    if not symbols and not owner:
        raise InvalidRequestError("Pass `tickers`, `owner_name`, or both.")
    filters: dict[str, Any] = {
        "ticker": symbols,
        "ownername": owner,
        "securityadcode": _SECURITY_CODES[(security, transactions_only)],
    }
    filters = {k: v for k, v in filters.items() if v}
    filters.update(date_range("filingdate", start_date, end_date))
    result = await fetch_table(
        ctx,
        SF2,
        filters=filters,
        columns=_SF2_COLUMNS,
        limit=limit,
        sort_by=[("filingdate", True), ("ticker", False), ("ownername", False)],
        notes=[SF2_NOTE],
    )
    return to_tool_result(result)


# --------------------------------------------------- 9. institutional (13F)

SF3_DATASETS = {
    "holdings": "SHARADAR/SF3",
    "by_ticker": "SHARADAR/SF3A",
    "by_investor": "SHARADAR/SF3B",
}
SF3_HINT = (
    "SF3, SF3A and SF3B have no free sample. ZACKS/IHC has a small free sample of "
    "institutional holders, readable through ndl_query_table."
)


async def ndl_get_institutional_holdings(
    ctx: Context,
    dataset: Annotated[
        Literal["holdings", "by_ticker", "by_investor"],
        Field(description="SF3 positions, or SF3A/SF3B totals per ticker or investor."),
    ] = "by_ticker",
    tickers: OptionalTickersArg = None,
    investor_id: Annotated[
        str | None,
        Field(description="Sharadar investor code (investorid).", max_length=20),
    ] = None,
    investor_name: Annotated[
        str | None,
        Field(description="Exact investor name (by_investor).", max_length=200),
    ] = None,
    security_type: Annotated[
        Literal["SHR", "FND", "CLL", "PUT", "WNT", "DBT", "PRF", "UND"] | None,
        Field(description="holdings only; SHR = shares, CLL/PUT = options."),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Needs a paid Sharadar SF3 subscription (no free sample): 13F holdings data.

    Quarter-end positions, newest first. SF3A filters by ticker, SF3B by
    investor. ZACKS/IHC (ndl_query_table) has a small free sample.
    """
    filters: dict[str, Any] = {
        "ticker": _tickers(tickers, required=False),
        "investorid": (investor_id or "").strip().upper(),
        "investorname": (investor_name or "").strip(),
        "securitytype": security_type,
    }
    filters = {k: v for k, v in filters.items() if v}
    if not (filters or start_date):
        raise InvalidRequestError(
            "Pass tickers, investor_id/investor_name, or a start_date quarter."
        )
    filters.update(date_range("date", start_date, end_date))
    value_column = "value" if dataset == "holdings" else "totalvalue"
    try:
        result = await fetch_table(
            ctx,
            SF3_DATASETS[dataset],
            filters=filters,
            limit=limit,
            sort_by=[("date", True), (value_column, True)],
        )
    except SubscriptionRequiredError as exc:
        raise SubscriptionRequiredError(
            f"{exc.message} {SF3_HINT}", code=exc.code, status=exc.status
        ) from None
    return to_tool_result(result)


# ---------------------------------------------------------- 10. 8-K events


async def _event_labels(ctx: Context) -> dict[str, str]:
    """EVENTCODES code -> title from SHARADAR/INDICATORS, cached for 24 hours."""
    key = _cache_key(ctx, "EVENTCODES")
    cached: dict[str, str] | None = _cache_get(key)
    if cached is not None:
        return cached
    read = await read_table(
        ctx,
        INDICATORS_TABLE,
        filters={"table": "EVENTCODES"},
        columns=["indicator", "title"],
        page_size=1000,
        validate=False,
    )
    labels = {
        str(r["indicator"]): str(r["title"])
        for r in read.records()
        if r.get("indicator") and r.get("title")
    }
    if labels:
        _cache_put(key, labels)
    return labels


async def ndl_get_company_events(
    ctx: Context,
    tickers: OptionalTickersArg = None,
    event_codes: Annotated[
        list[str] | None,
        Field(
            description="Keep filings with any of these 2-digit 8-K codes, e.g. "
            "['22'] (results of operations) or ['52'] (officer changes)."
        ),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get material corporate events reported on SEC Form 8-K, with decoded event names.

    Reads SHARADAR/EVENTS (filing date and 8-K item codes per ticker) and adds
    an `events` column with the code titles from SHARADAR/INDICATORS. Newest
    first; without tickers or a start_date, the 30 days up to end_date or
    today. A free key gets the full, current history for the sample tickers
    only.
    """
    symbols = _tickers(tickers, required=False)
    wanted = {c.strip() for c in event_codes or [] if c.strip()}
    bad = sorted(c for c in wanted if not re.fullmatch(r"\d{2}", c))
    if bad:
        raise InvalidRequestError(
            f"Event codes are 2-digit numbers such as '22' or '52', got: "
            f"{', '.join(bad)}. ndl_search_financial_metrics(table='EVENTCODES') "
            "lists them."
        )
    notes: list[str] = []
    if not symbols and not start_date:
        start_date = _recent_start(end_date)
        notes.append(
            f"No tickers or start_date given: showing the 30 days from {start_date}."
        )
    filters: dict[str, Any] = {"ticker": symbols} if symbols else {}
    filters.update(date_range("date", start_date, end_date))
    read = await read_table(
        ctx, EVENTS, filters=filters, columns=["ticker", "date", "eventcodes"]
    )
    labels = await _event_labels(ctx)
    i = read.column_names.index("eventcodes")
    rows: list[list[Any]] = []
    for row in read.rows:
        codes = [c for c in str(row[i] or "").split("|") if c]
        if not wanted or wanted.intersection(codes):
            rows.append([*row, "; ".join(labels.get(c, f"code {c}") for c in codes)])
    columns = [*read.columns, ColumnInfo(name="events", type="text")]
    rows = sort_rows_by([c.name for c in columns], rows, _NEWEST_FIRST)
    request = dict(read.request)
    if wanted:
        request["event_codes"] = sorted(wanted)
    result = build_result(
        ctx, read, rows, limit=limit, columns=columns, notes=notes, request=request
    )
    return to_tool_result(result)


# ------------------------------------------------- 11. analyst estimates


@dataclass(frozen=True)
class ZacksDataset:
    """One ZACKS table behind ndl_get_analyst_estimates."""

    code: str
    columns: str  # curated default, space-separated
    sort: tuple[tuple[str, bool], ...]  # (column, descending); a date comes first
    per_type_filter: bool  # per_type (A/Q) is filterable
    note: str

    @property
    def date_column(self) -> str | None:
        """The filterable date start/end apply to; None for current snapshots."""
        first = self.sort[0][0]
        return None if first == "ticker" else first


_UPCOMING = (("per_end_date", False), ("ticker", False), ("per_type", False))
_REPORTED = (("per_end_date", True), ("ticker", False))
_OBSERVED = (("obs_date", True), ("ticker", False))
_BY_TICKER = (("ticker", False),)
_PERIOD = "ticker comp_name per_end_date per_type"
ZACKS_DATASETS = {
    "eps_estimates": ZacksDataset(
        "ZACKS/EE",
        f"{_PERIOD} per_fisc_year per_fisc_qtr eps_mean_est eps_median_est "
        "eps_high_est eps_low_est eps_std_dev_est eps_cnt_est eps_pct_chg_est",
        _UPCOMING,
        True,
        "Consensus EPS (Zacks BNRI basis: before non-recurring items) for open "
        "fiscal periods; per_type A = annual, Q = quarterly. eps_pct_chg_est is "
        "the expected growth vs the same period a year earlier.",
    ),
    "sales_estimates": ZacksDataset(
        "ZACKS/SE",
        f"{_PERIOD} per_fisc_year per_fisc_qtr sales_mean_est sales_median_est "
        "sales_high_est sales_low_est sales_cnt_est sales_pct_chg_est_1m "
        "last_rev_date",
        _UPCOMING,
        True,
        "Consensus revenue estimates in millions of the reporting currency; "
        "per_type A = annual, Q = quarterly.",
    ),
    "eps_surprises": ZacksDataset(
        "ZACKS/ES",
        f"{_PERIOD} act_rpt_date eps_act eps_mean_est eps_amt_diff_surp "
        "eps_pct_diff_surp eps_cnt_est act_rpt_desc",
        _REPORTED,
        False,
        "Reported quarterly EPS vs the consensus before the report; "
        "eps_pct_diff_surp is the surprise in percent.",
    ),
    "sales_surprises": ZacksDataset(
        "ZACKS/SS",
        f"{_PERIOD} act_rpt_date sales_act sales_mean_est sales_amt_diff_surp "
        "sales_pct_diff_surp sales_cnt_est act_rpt_desc",
        _REPORTED,
        True,
        "Reported revenue (millions) vs the consensus before the report.",
    ),
    "eps_estimate_trends": ZacksDataset(
        "ZACKS/EET",
        f"{_PERIOD} eps_mean_est eps_mean_est_7d_ago eps_mean_est_30d_ago "
        "eps_mean_est_60d_ago eps_mean_est_90d_ago eps_cnt_est_rev_up_last_30d "
        "eps_cnt_est_rev_down_last_30d eps_cnt_est_rev_up_last_90d "
        "eps_cnt_est_rev_down_last_90d",
        _UPCOMING,
        True,
        "Consensus EPS now vs 7/30/60/90 days ago and the number of upward and "
        "downward analyst revisions.",
    ),
    "recommendations": ZacksDataset(
        "ZACKS/AR",
        "ticker comp_name rating_mean rating_mean_1m_ago rating_mean_3m_ago "
        "rating_cnt_strong_buys rating_cnt_buys rating_cnt_holds rating_cnt_sells "
        "rating_cnt_strong_sells tp_mean_est tp_median_est tp_high_est tp_low_est "
        "tp_cnt_est last_rev_date",
        _BY_TICKER,
        False,
        "Current broker ratings: rating_mean runs from 1 = Strong Buy to 5 = "
        "Strong Sell; tp_* are consensus 12-month price targets.",
    ),
    "rating_history": ZacksDataset(
        "ZACKS/RH",
        "ticker obs_date rating_mean_recom rating_cnt_strong_buys "
        "rating_cnt_mod_buys rating_cnt_holds rating_cnt_mod_sells "
        "rating_cnt_strong_sells",
        _OBSERVED,
        False,
        "Daily history of the consensus rating (1 = Strong Buy, 5 = Strong Sell) "
        "and rating counts.",
    ),
    "target_prices": ZacksDataset(
        "ZACKS/TP",
        "ticker obs_date tp_mean_est tp_median_est tp_high_est tp_low_est "
        "tp_std_dev_est tp_cnt_est tp_cnt_est_rev_up tp_cnt_est_rev_down",
        _OBSERVED,
        False,
        "History of consensus 12-month price targets (split-adjusted). The "
        "current target is in dataset 'recommendations'.",
    ),
    "long_term_growth": ZacksDataset(
        "ZACKS/LTG",
        "ticker comp_name ltg_mean_est ltg_high_est ltg_low_est ltg_cnt_est "
        "eps_mean_est_fwd12m eps_high_est_fwd12m eps_low_est_fwd12m",
        _BY_TICKER,
        False,
        "ltg_* is the consensus annual EPS growth rate expected over the next 3-5 "
        "years, in percent; eps_*_fwd12m sums the next four quarterly estimates.",
    ),
    "earnings_dates": ZacksDataset(
        "ZACKS/EA",
        "ticker comp_name exp_rpt_date_qr1 time_of_day_desc per_end_date_qr1 "
        "eps_mean_est_qr1 street_mean_est_qr1 exp_rpt_date_qr2 exp_rpt_date_fr1 "
        "per_end_date_qr0 eps_act_qr0 source_desc late_last_desc",
        (("exp_rpt_date_qr1", False), ("ticker", False)),
        False,
        "Next expected report date (exp_rpt_date_qr1) for the quarter ending "
        "per_end_date_qr1, with its EPS consensus; source_desc says whether the "
        "date is confirmed by the company or estimated.",
    ),
}
AnalystDataset = Literal[
    "eps_estimates",
    "sales_estimates",
    "eps_surprises",
    "sales_surprises",
    "eps_estimate_trends",
    "recommendations",
    "rating_history",
    "target_prices",
    "long_term_growth",
    "earnings_dates",
]


async def ndl_get_analyst_estimates(
    ctx: Context,
    tickers: TickersArg,
    dataset: Annotated[
        AnalystDataset,
        Field(description="recommendations: current ratings and price targets."),
    ] = "eps_estimates",
    period_type: Annotated[
        Literal["all", "annual", "quarterly"],
        Field(description="Annual, quarterly or both."),
    ] = "all",
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    columns: Annotated[
        str | list[str] | None,
        Field(description="Columns, or 'all' (default: a curated set)."),
    ] = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Get Zacks consensus estimates, surprises, ratings, price targets, report dates.

    recommendations and long_term_growth take no dates. Free key: about 30 large
    US companies; surprises, rating_history and target_prices cover one past
    year only.
    """
    spec = ZACKS_DATASETS[dataset]
    symbols = _tickers(tickers, required=True)
    if (start_date or end_date) and not spec.date_column:
        raise InvalidRequestError(
            f"dataset '{dataset}' is a current snapshot and takes no dates."
        )
    filters: dict[str, Any] = {"ticker": symbols}
    notes = [spec.note]
    if period_type != "all":
        if spec.per_type_filter:
            filters["per_type"] = "A" if period_type == "annual" else "Q"
        else:
            notes.append(f"period_type does not apply to '{dataset}' and was ignored.")
    if spec.date_column:
        filters.update(date_range(spec.date_column, start_date, end_date))
    result = await fetch_table(
        ctx,
        spec.code,
        filters=filters,
        columns=_column_list(columns, spec.columns.split(), ("ticker",)),
        limit=limit,
        sort_by=spec.sort,
        scan_size=5000 * len(symbols),
        notes=notes,
    )
    return to_tool_result(result)


# ------------------------------------------------------------------ prompt


def company_snapshot(
    ticker: Annotated[
        str,
        Field(description="US stock ticker, e.g. 'AAPL'.", max_length=20),
    ],
) -> str:
    """Build a one-page profile of a US company from the equities tools."""
    symbol = _tickers(ticker, required=True)[0]
    return f"""\
Build a concise company snapshot for {symbol} with the Nasdaq Data Link tools.

1. ndl_search_tickers(tickers="{symbol}"): name, exchange, sector, industry,
   market-cap scale, listing status and which Sharadar tables carry it.
2. ndl_get_fundamentals(tickers="{symbol}", dimension="MRY"): revenue, margins,
   net income, free cash flow, debt and returns for the latest years.
3. ndl_get_valuation_metrics(tickers="{symbol}") and
   ndl_get_stock_prices(tickers="{symbol}", security_type="stock", limit=30):
   valuation ratios and recent prices.
4. ndl_get_analyst_estimates(tickers="{symbol}", dataset=...) with
   "recommendations", "eps_estimates" and "earnings_dates".
5. ndl_get_corporate_actions(tickers="{symbol}", actions=["dividend", "split"])
   and ndl_get_company_events(tickers="{symbol}", limit=10).

Present a short profile, a table of key financials by year, valuation, analyst
view and upcoming dates. State the period each figure refers to. A free API key
only returns a fixed sample (about 30 large US companies, older dates for some
tables); say so when results are empty or old, and do not fill gaps with
estimates of your own.
"""


TOOLSET = Toolset(
    name="equities",
    description=(
        "US equities from Sharadar and Zacks: tickers, fundamentals, prices, estimates."
    ),
    tools=(
        ToolSpec(
            ndl_search_tickers,
            "Search US stock and fund tickers",
            tables=(TICKERS_TABLE,),
        ),
        ToolSpec(ndl_get_fundamentals, "Get company fundamentals", tables=(SF1,)),
        ToolSpec(
            ndl_search_financial_metrics,
            "Search Sharadar field definitions",
            tables=(INDICATORS_TABLE,),
        ),
        ToolSpec(
            ndl_get_stock_prices,
            "Get daily stock or fund prices",
            tables=tuple(_PRICE_TABLES.values()),
        ),
        ToolSpec(
            ndl_get_valuation_metrics, "Get daily valuation ratios", tables=(DAILY,)
        ),
        ToolSpec(ndl_get_corporate_actions, "Get corporate actions", tables=(ACTIONS,)),
        ToolSpec(
            ndl_get_sp500_constituents, "Get S&P 500 constituents", tables=(SP500,)
        ),
        ToolSpec(
            ndl_get_insider_transactions, "Get insider transactions", tables=(SF2,)
        ),
        ToolSpec(
            ndl_get_institutional_holdings,
            "Get 13F institutional holdings",
            tables=tuple(SF3_DATASETS.values()),
        ),
        ToolSpec(
            ndl_get_company_events,
            "Get 8-K corporate events",
            tables=(EVENTS, INDICATORS_TABLE),
        ),
        ToolSpec(
            ndl_get_analyst_estimates,
            "Get Zacks analyst estimates",
            tables=tuple(spec.code for spec in ZACKS_DATASETS.values()),
        ),
    ),
    prompts=(PromptSpec(company_snapshot, "Company snapshot"),),
    hints=("Company name to ticker: ndl_search_tickers.",),
)
