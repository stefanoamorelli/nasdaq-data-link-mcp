"""Nasdaq datasets: retail trading activity, ticker changes, Equities 360."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult
from pydantic import Field

from nasdaq_data_link_mcp_os.errors import (
    InvalidRequestError,
    SubscriptionRequiredError,
)
from nasdaq_data_link_mcp_os.query import sort_rows_by
from nasdaq_data_link_mcp_os.results import ColumnInfo, TableResult, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    SCAN_MAX_PAGES,
    AppState,
    EndDateArg,
    LimitArg,
    OptionalTickersArg,
    PromptSpec,
    StartDateArg,
    TableRead,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    fetch_table,
    get_metadata,
    read_table,
)

RTAT10 = "NDAQ/RTAT10"
RTAT = "NDAQ/RTAT"
TICKER_CHANGES = "NDAQ/TC"
RTAT_ORDER = [("date", True), ("activity", True)]
RTAT_SAMPLE_NOTE = (
    "A free key's NDAQ/RTAT sample is 7 rows dated 2016-01-15: pass start_date and "
    "end_date 2016-01-15 to read it, or use dataset='rtat10' for current free data."
)
# NDAQ/TC uses 1980-01-01 as the start of each FIGI's symbol history.
TC_ORDER = [("date", True), ("symbol", False)]
TC_HISTORY_MAX_FIGIS = 100  # FIGIs in the one history lookup (keeps the URL short)
TC_HISTORY_COLUMNS = ("previous_symbol", "next_symbol", "next_date")

E360_TABLES = {
    "statistics": "NDAQ/STAT",
    "fundamentals_summary": "NDAQ/FS",
    "fundamentals_details": "NDAQ/FD",
    "balance_sheet": "NDAQ/BS",
    "income_statement": "NDAQ/IS",
    "cash_flow": "NDAQ/CF",
    "reference_data": "NDAQ/RD",
    "corporate_actions": "NDAQ/CA",
}
E360_FUNDAMENTALS = {"NDAQ/FS", "NDAQ/FD", "NDAQ/BS", "NDAQ/IS", "NDAQ/CF"}
# NDAQ/FD has 70 columns; this subset keeps default answers compact. The
# misspelling 'debttoassests' is the live column name.
FD_DEFAULT_COLUMNS = tuple(
    "calendardate symbol dimension reportperiod revenue gp grossmargin opinc ebit "
    "ebitda ebitdamargin netinc eps shareswadil ncfo capex freecashflow cashneq "
    "debtc debtnc equity liabilities roic ev evebitda divyield debttoassests".split()
)

_FIGI_RE = re.compile(r"^[A-Z0-9]{12}$")

# ----------------------------------------------------------------- helpers


def _limit(state: AppState, limit: int | None) -> int:
    """The row limit build_result will apply."""
    settings = state.settings
    return max(1, min(limit or settings.default_limit, settings.max_limit))


async def _default_start(
    state: AppState, code: str, end_date: str | None, days: int
) -> str:
    """``days`` before end_date or the table's last refresh (not today, so a
    table Nasdaq stops updating still returns rows)."""
    if end_date:
        anchor = date.fromisoformat(end_date)
    else:
        metadata = await get_metadata(state, code)
        refreshed = (metadata.refreshed_at if metadata else None) or ""
        try:
            anchor = date.fromisoformat(refreshed[:10])
        except ValueError:
            anchor = datetime.now(UTC).date()
    return (anchor - timedelta(days=days)).isoformat()


async def _latest_rtat_date(ctx: Context) -> str | None:
    """Latest trading date in NDAQ/RTAT10 (free), which shares dates with NDAQ/RTAT."""
    since = await _default_start(app_state(ctx), RTAT10, None, 14)
    read = await read_table(
        ctx,
        RTAT10,
        filters={"date.gte": since},
        columns=["date"],
        page_size=500,
        validate=False,
    )
    return max((str(r[0])[:10] for r in read.rows if r[0]), default=None)


def _top10_note(
    read: TableRead, tickers: list[str], latest: str | None, dated: bool
) -> str | None:
    """Say when requested tickers are absent from RTAT10's recent top 10 lists."""
    newest: dict[str, str] = {}
    for record in read.records():
        ticker, day = str(record["ticker"]).upper(), str(record["date"])[:10]
        newest[ticker] = max(day, newest.get(ticker, day))
    parts = [
        f"{t} last appeared in the daily top 10 on {newest[t]} (latest trading "
        f"day {latest})"
        for t in tickers
        if latest and t in newest and newest[t] < latest
    ]
    missing = [t for t in tickers if t not in newest]
    if missing:
        where = "in the requested dates" if dated else "on any day"
        parts.append(f"{', '.join(missing)}: not in the daily top 10 {where}")
    return (
        "; ".join(parts) + "; RTAT10 lists only each day's top 10." if parts else None
    )


async def _symbol_chains(ctx: Context, figis: list[str]) -> dict[str, list[Any]]:
    """Each FIGI's (date, symbol) history from NDAQ/TC, oldest first."""
    read = await read_table(
        ctx,
        TICKER_CHANGES,
        filters={"figi": figis},
        columns=["date", "symbol", "figi"],
        validate=False,
    )
    chains: dict[str, list[Any]] = defaultdict(list)
    for r in read.records():
        chains[str(r["figi"])].append((str(r["date"]), str(r["symbol"])))
    return {figi: sorted(chain) for figi, chain in chains.items()}


def _neighbours(chain: list[Any], day: str) -> list[str | None]:
    """previous_symbol, next_symbol and next_date around ``day``."""
    previous = next((s for d, s in reversed(chain) if d < day), None)
    following = next(((s, d) for d, s in chain if d > day), (None, None))
    return [previous, *following]


def _e360_hint(state: AppState) -> str:
    """Free-key alternatives, naming only tools this server has enabled."""
    if "equities" in state.toolsets:
        return (
            "Free-key alternatives: ndl_search_tickers (company reference data, "
            "free) and ndl_get_fundamentals (Sharadar fundamentals, free sample)."
        )
    return (
        "Free-key alternatives: SHARADAR/TICKERS (company reference data, free) and "
        "SHARADAR/SF1 (fundamentals, free sample) through ndl_query_table."
    )


# ------------------------------------------------------------------- tools


async def ndl_get_retail_trading_activity(
    ctx: Context,
    tickers: OptionalTickersArg = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    dataset: Annotated[
        Literal["rtat10", "rtat"],
        Field(description="rtat10: free daily top 10; rtat: premium full universe."),
    ] = "rtat10",
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Daily retail activity share and net sentiment for US tickers (Nasdaq RTAT).

    rtat10 (NDAQ/RTAT10, free for any key): each trading day's 10 tickers with the
    largest share of retail dollar volume, from 2016 to the previous trading day.
    rtat (NDAQ/RTAT): every covered ticker; without an RTAT subscription, only a
    fixed 7-row sample dated 2016-01-15.

    `activity` is the ticker's share (0-1) of the day's retail dollar volume;
    `sentiment` (-100 to +100) is retail net buying minus selling over 10 trading
    days. A ticker absent from RTAT10 on a day was outside that day's top 10; notes
    give each requested ticker's last top-10 day. Newest day first, then by
    activity; without dates, the most recent days (rtat without tickers: the
    latest day).
    """
    state = app_state(ctx)
    code = RTAT10 if dataset == "rtat10" else RTAT
    symbols = as_list(tickers)
    want = _limit(state, limit)
    filters: dict[str, Any] = {"ticker": symbols} if symbols else {}
    filters.update(date_range("date", start_date, end_date))
    notes: list[str] = []
    if not symbols and not start_date:
        if dataset == "rtat10":
            # Ten rows per trading day; 1.5 calendar days per trading day + holidays.
            days = math.ceil(math.ceil(want / 10) * 1.5) + 10
            start = await _default_start(state, code, end_date, days)
            filters["date.gte"] = start
            notes.append(f"No start_date given: read rows dated {start} or later.")
        elif not end_date and (latest := await _latest_rtat_date(ctx)):
            filters["date"] = latest
            notes.append(f"No dates given: showing the latest trading day, {latest}.")
    read = await read_table(ctx, code, filters=filters, max_pages=SCAN_MAX_PAGES)
    rows = sort_rows_by(read.column_names, read.rows, RTAT_ORDER)
    if symbols and dataset == "rtat10" and read.next_cursor is None:
        latest = None if end_date else await _latest_rtat_date(ctx)
        note = _top10_note(read, symbols, latest, dated=bool(start_date or end_date))
        if note:
            notes.append(note)
    if dataset == "rtat" and not rows:
        notes.append(RTAT_SAMPLE_NOTE)
    request = {**read.request, "sort_by": "date desc, activity desc"}
    return to_tool_result(
        build_result(ctx, read, rows, limit=want, notes=notes, request=request)
    )


async def ndl_get_ticker_changes(
    ctx: Context,
    tickers: Annotated[
        str | list[str] | None,
        Field(
            description="Ticker or list of tickers; each matches every FIGI that "
            "has used it."
        ),
    ] = None,
    figis: Annotated[
        str | list[str] | None,
        Field(description="FIGIs (12 characters, e.g. 'BBG000MM2P62'): one or a list."),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    resolve_history: Annotated[
        bool,
        Field(
            description="Add previous_symbol, next_symbol and next_date (one extra "
            "request)."
        ),
    ] = True,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """US ticker symbol changes and new listings, keyed by FIGI (NDAQ/TC, free, daily).

    A row means the security `figi` traded as `symbol` from `date` on;
    resolve_history adds the same FIGI's previous_symbol, next_symbol and
    next_date. Rows dated 1980-01-01 are the baseline symbol, not changes; a FIGI
    with no earlier row is a new listing. Newest first; without filters, the last
    90 days. A ticker matches every FIGI that has used it, so a reused ticker
    shows each holder (FB: Meta until 2022-06-09, another security since 2025).
    """
    state = app_state(ctx)
    symbols = as_list(tickers)
    figi_list = as_list(figis)
    bad = [f for f in figi_list if not _FIGI_RE.match(f)]
    if bad:
        raise InvalidRequestError(
            f"Not a FIGI: {', '.join(bad)}. FIGIs are 12 letters and digits, e.g. "
            "BBG000MM2P62."
        )
    want = _limit(state, limit)
    filters: dict[str, Any] = {"symbol": symbols, "figi": figi_list}
    filters = {k: v for k, v in filters.items() if v}
    filters.update(date_range("date", start_date, end_date))
    notes: list[str] = []
    if not (symbols or figi_list or start_date):
        start = await _default_start(state, TICKER_CHANGES, end_date, 90)
        filters["date.gte"] = start
        notes.append(
            f"No tickers, figis or start_date given: showing changes dated {start} "
            "or later."
        )
    read = await read_table(ctx, TICKER_CHANGES, filters=filters)
    rows = sort_rows_by(read.column_names, read.rows, TC_ORDER)
    columns: list[ColumnInfo] | None = None
    if resolve_history and rows:
        names = read.column_names
        i_date, i_figi = names.index("date"), names.index("figi")
        shown = list(dict.fromkeys(str(r[i_figi]) for r in rows[:want]))
        if len(shown) > TC_HISTORY_MAX_FIGIS:
            notes.append(
                f"previous/next symbols cover the first {TC_HISTORY_MAX_FIGIS} of "
                f"{len(shown)} FIGIs only."
            )
        chains = await _symbol_chains(ctx, shown[:TC_HISTORY_MAX_FIGIS])
        rows = [
            [*r, *_neighbours(chains.get(str(r[i_figi]), []), str(r[i_date]))]
            for r in rows
        ]
        columns = [
            *read.columns,
            *(ColumnInfo(name=n, type="text") for n in TC_HISTORY_COLUMNS),
        ]
    request = {**read.request, "sort_by": "date desc, symbol asc"}
    result = build_result(
        ctx, read, rows, limit=want, columns=columns, notes=notes, request=request
    )
    return to_tool_result(result)


async def ndl_get_equities360(
    ctx: Context,
    dataset: Annotated[
        Literal[
            "statistics",
            "fundamentals_summary",
            "fundamentals_details",
            "balance_sheet",
            "income_statement",
            "cash_flow",
            "reference_data",
            "corporate_actions",
        ],
        Field(description="Table to read."),
    ],
    tickers: Annotated[
        str | list[str] | None,
        Field(description="Tickers or FIGIs (12 characters): one or a list."),
    ] = None,
    dimension: Annotated[
        Literal["MRQ", "MRY", "MRT"] | None,
        Field(
            description="Fundamentals only: MRQ quarter, MRY year, MRT trailing 12 "
            "months."
        ),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    contra_tickers: Annotated[
        str | list[str] | None,
        Field(
            description="corporate_actions only: the other party's ticker, e.g. "
            "an acquirer."
        ),
    ] = None,
    columns: Annotated[
        list[str] | None,
        Field(
            description="Columns (default all; fundamentals_details: 27 of 70). "
            "['all'] for every column."
        ),
    ] = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Nasdaq Equities 360 company data; needs a paid subscription (no free sample).

    Free-key alternatives: ndl_search_tickers and ndl_get_fundamentals.
    statistics: market cap, P/E, 52-week range, yield. The five fundamentals
    datasets: by calendardate and dimension, from 2008. reference_data: exchange,
    sector, industry. corporate_actions: splits, mergers, dividends. Dates filter
    calendardate or the action date; dated rows come newest first.
    """
    state = app_state(ctx)
    code = E360_TABLES[dataset]
    items = as_list(tickers)
    figi_list = [v for v in items if _FIGI_RE.match(v)]
    symbols = [v for v in items if v not in figi_list]
    if symbols and figi_list:
        raise InvalidRequestError(
            "Pass tickers or FIGIs, not both: Nasdaq would return only rows matching "
            "a ticker and a FIGI at once."
        )
    # A dimension, date or contra ticker on a table without that column fails the
    # shared filter check, which lists the table's filters.
    fundamentals = code in E360_FUNDAMENTALS
    date_column = "calendardate" if fundamentals else "date"
    filters: dict[str, Any] = {
        "symbol": symbols,
        "figi": figi_list,
        "contrasymbol": as_list(contra_tickers),
        "dimension": dimension,
    }
    filters = {k: v for k, v in filters.items() if v}
    filters.update(date_range(date_column, start_date, end_date))
    notes: list[str] = []
    wanted = [c.strip().lower() for c in columns or [] if c.strip()]
    selected: list[str] | None = None
    if columns is None and dataset == "fundamentals_details":
        selected = list(FD_DEFAULT_COLUMNS)
        notes.append(
            f"Showing {len(selected)} of {code}'s columns; pass columns=['all'] or "
            "column names for more."
        )
    elif wanted and "all" not in wanted:
        # The primary key stays in front so rows remain identifiable.
        entry = state.catalog.get(code)
        selected = list(dict.fromkeys([*(entry.primary_key if entry else ()), *wanted]))
    identified = bool(symbols or figi_list or "contrasymbol" in filters)
    actions = dataset == "corporate_actions"
    sort_by = date_column if (fundamentals and identified) or actions else None
    if actions and not identified and not start_date:
        start = await _default_start(state, code, end_date, 30)
        filters["date.gte"] = start
        notes.append(
            f"No tickers or dates given: showing actions dated {start} or later."
        )
    elif not identified and not actions:
        notes.append(
            f"No tickers given: rows are in Nasdaq's order; ndl_query_table on "
            f"{code} pages through all of them."
        )
    try:
        result = await fetch_table(
            ctx,
            code,
            filters=filters,
            columns=selected,
            limit=limit,
            sort_by=sort_by,
            descending=True,
            notes=notes,
        )
    except SubscriptionRequiredError as exc:
        raise SubscriptionRequiredError(
            f"{exc.message} {_e360_hint(state)}", code=exc.code, status=exc.status
        ) from None
    # Paging belongs to ndl_query_table; this tool has no cursor argument.
    return to_tool_result(result.model_copy(update={"next_cursor": None}))


# ----------------------------------------------------------------- prompts


def retail_sentiment_brief(
    tickers: Annotated[
        str,
        Field(
            description="Optional comma-separated tickers to focus on, e.g. "
            "'TSLA,NVDA'. Empty covers the market-wide daily top 10."
        ),
    ] = "",
    days: Annotated[
        str,
        Field(description="Number of recent trading days to cover, 1-60 (default 5)."),
    ] = "5",
) -> str:
    """Brief on recent retail trading activity and sentiment from Nasdaq RTAT10."""
    try:
        n_days = int(days.strip() or "5")
    except ValueError:
        n_days = 0
    if not 1 <= n_days <= 60:
        # MCPError reaches the user; the SDK hides other exceptions' messages.
        raise MCPError(
            code=INVALID_PARAMS,
            message=f"days must be a whole number from 1 to 60, got {days!r}.",
        )
    focus = as_list(tickers)
    steps = [
        "Write a short retail-sentiment brief from Nasdaq's Retail Trading Activity "
        "Tracker (NDAQ/RTAT10).",
        f"1. Call ndl_get_retail_trading_activity with limit={n_days * 10} and no "
        f"tickers or dates to get the daily top 10 for the last {n_days} trading "
        "days.",
    ]
    if focus:
        steps.append(
            f"2. Call it again with tickers={focus} and no dates. Its rows are the "
            "days those tickers made the top 10, newest first, and its notes say "
            "when a ticker missing from the latest day last appeared. A missing day "
            "means the ticker was not in that day's top 10, not zero activity."
        )
    steps.append(
        f"{len(steps)}. Report the latest trading date covered, which tickers led "
        "retail activity and how persistent they were, and notable sentiment "
        "readings or shifts. `activity` is the share of all retail dollar volume "
        "(0-1); `sentiment` runs from -100 to +100 and reflects retail net buying "
        "minus selling over the last 10 trading days. Cite the numbers, keep it "
        "under 200 words, and do not present it as investment advice."
    )
    return "\n".join(steps)


TOOLSET = Toolset(
    name="nasdaq",
    description=(
        "Nasdaq datasets: retail trading activity, ticker changes, Equities 360."
    ),
    tools=(
        ToolSpec(
            ndl_get_retail_trading_activity,
            "Get retail trading activity",
            tables=(RTAT10, RTAT),
        ),
        ToolSpec(
            ndl_get_ticker_changes,
            "Get ticker symbol changes",
            tables=(TICKER_CHANGES,),
        ),
        ToolSpec(
            ndl_get_equities360,
            "Get Equities 360 company data",
            tables=tuple(E360_TABLES.values()),
        ),
    ),
    prompts=(PromptSpec(retail_sentiment_brief, "Retail sentiment brief"),),
    hints=("Symbol changes for all US tickers: ndl_get_ticker_changes.",),
)
