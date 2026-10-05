"""Nasdaq Fund Network Mutual Fund Reports (the NFN/MFR* tables).

Funds are keyed by ``fund_id`` and share classes by ``security_id`` (UUIDs); a
share class's ticker is ``nav_symbol`` in NFN/MFRSM. Some tables filter by only
one of the two ids (NFN/MFRSI and NFN/MFRPS take security_id only), so a report
given tickers or the other id first looks the share classes up in NFN/MFRSM.

A free key gets a fixed sample per table, and the samples do not line up:
MFRSM, MFRFM, MFRFI, MFRSI, MFRPS and MFRPH10 share about 30 funds, MFRPA and
MFRPM cover other funds, and MFRPH returns no rows. Lookups whose filters and
columns are fixed here skip the metadata request.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.client import MAX_PAGE_SIZE
from nasdaq_data_link_mcp_os.errors import (
    InvalidRequestError,
    NdlError,
    SubscriptionRequiredError,
)
from nasdaq_data_link_mcp_os.results import TableResult, fit_rows, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    EndDateArg,
    LimitArg,
    PromptSpec,
    StartDateArg,
    Toolset,
    ToolSpec,
    access_for,
    app_state,
    as_list,
    date_range,
    fetch_table,
    read_table,
)

FUND_MASTER = "NFN/MFRFM"
SECURITY_MASTER = "NFN/MFRSM"
HOLDINGS = "NFN/MFRPH"
BENCHMARKS = "NFN/MFRPB"

NIL_UUID = "00000000-0000-0000-0000-000000000000"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
CUSIP_RE = re.compile(r"^[0-9A-Z]{8}[0-9]$")
_WORD_RE = re.compile(r"[a-z0-9]+")
MAX_IDS = 25  # values per tickers / *_ids parameter
MAX_KEYS = 100  # ids in one report request (a fund can have 20+ share classes)
MAX_QUERY_LEN = 200
NAME_SCAN_PAGES = 4  # a subscription has ~30-40k share classes
BENCHMARK_LOOKUP_SECONDS = 2.0  # benchmark names are optional decoration

SM_COLUMNS = tuple(
    "security_id fund_id name nav_symbol ticker_symbol instrument_code "
    "inception_date final_date".split()
)
FM_COLUMNS = ("fund_id", "name", "investment_company_type", "termination_date")
INSTRUMENTS = {"O": "open-end fund", "C": "closed-end fund"}
# Report parameter -> the NFN/MFRSM column its values are matched against.
ID_COLUMNS = {
    "tickers": "nav_symbol",
    "security_ids": "security_id",
    "fund_ids": "fund_id",
}
FREE_SAMPLE_NOTE = (
    "With a free key NFN/MFRSM and NFN/MFRFM return a fixed sample of about 30 "
    "funds; other funds are not found."
)

# ------------------------------------------------------------------ reports

FUND_INFO_COLUMNS = tuple(
    "fund_id info_date family advisors objective strategy fye turnover_rate "
    "closed_to_new_inv closed_to_existing_inv benchmarks portfolio_managers "
    "assets_date tot_assets tot_liabs net_assets cef_mgmt_fee cef_op_exp "
    "ndw_fund_score ndw_investment_category ndw_investment_group websites "
    "edgar_prospectus_url".split()
)
TOP_HOLDING_COLUMNS = tuple(
    "fund_id date holding_index issuer_name title ticker figi_ticker cusip isin "
    "balance units cur_cd val_usd pct_val payoff_profile asset_cat_desc "
    "issuer_cat_desc inv_country is_debt is_derivative".split()
)
HOLDING_COLUMNS = (*TOP_HOLDING_COLUMNS, "debt_maturity_date", "debt_coupon_ann_rate")
PRICING_COLUMNS = tuple(
    "security_id pricing_type_id ref_date benchmark_id date last_price "
    "net_chg_1day ret_1day ret_1wk ret_1mo ret_3mo ret_ytd ret_1yr ret_3yr "
    "ret_5yr ret_10yr ret_inception hi_52wk date_hi_52wk lo_52wk date_lo_52wk "
    "yield_1yr".split()
)
NEWEST_FIRST = (("ref_date", True),)
LARGEST_FIRST = (("pct_val", True),)
BENCHMARKED = ("pricing", "performance")  # reports with a benchmark_id column


@dataclass(frozen=True)
class ReportSpec:
    table: str
    key: Literal["fund", "security", "benchmark"]
    date_column: str | None = None
    sort: tuple[tuple[str, bool], ...] = ()  # (column, descending), when keyed
    columns: tuple[str, ...] | None = None  # default subset; None = all columns
    note: str | None = None
    # Where else to look when the table is 403 or a free key's sample is empty.
    fallback: str | None = None

    @property
    def key_column(self) -> str:
        return f"{self.key}_id"


REPORTS: dict[str, ReportSpec] = {
    "fund_master": ReportSpec(
        FUND_MASTER,
        "fund",
        note="investment_company_type N-1A = open-end fund, N-2 = closed-end fund.",
    ),
    "fund_info": ReportSpec(
        "NFN/MFRFI",
        "fund",
        date_column="info_date",
        columns=FUND_INFO_COLUMNS,
        note="risks (long prospectus text) and the sponsor address are left out "
        "unless named in `columns`. tot_assets and net_assets are USD as of "
        "assets_date; turnover_rate is a fraction (1.0 = 100% a year).",
    ),
    "share_classes": ReportSpec(
        SECURITY_MASTER,
        "fund",
        note="nav_symbol is the share-class ticker; ticker_symbol is the exchange "
        "ticker of closed-end funds. instrument_code O = open-end, C = closed-end.",
    ),
    "fees": ReportSpec(
        "NFN/MFRSI",
        "security",
        date_column="info_date",
        note="Expense, fee and sales-charge columns are fractions (0.0099 = "
        "0.99%); net_expenses_over_assets is the expense ratio after waivers.",
    ),
    "pricing": ReportSpec(
        "NFN/MFRPS",
        "security",
        date_column="ref_date",
        sort=(*NEWEST_FIRST, ("pricing_type_id", False)),
        columns=PRICING_COLUMNS,
        note="One snapshot per ref_date. pricing_type_id 0 = NAV total return, "
        "1 = market-price total return, 2 = return of benchmark_id over the same "
        "windows. ret_* are fractions (0.05 = 5%) over windows ending on `date`.",
    ),
    "performance": ReportSpec(
        "NFN/MFRPA",
        "security",
        date_column="ref_date",
        sort=NEWEST_FIRST,
        note="Statistics versus benchmark_id over `period` (Y3, Y5, Y10) of daily "
        "returns before ref_date. total_return, std_dev, alpha and the drawdown "
        "columns are fractions; pricing_type_id 0 = NAV, 1 = market price.",
    ),
    "top_holdings": ReportSpec(
        "NFN/MFRPH10",
        "fund",
        date_column="date",
        sort=LARGEST_FIRST,
        columns=TOP_HOLDING_COLUMNS,
        note="The 10 largest positions at each fund's latest N-PORT report date. "
        "pct_val is percent of net assets (4.3 = 4.3%); val_usd is in USD.",
    ),
    "holdings": ReportSpec(
        HOLDINGS,
        "fund",
        date_column="date",
        sort=LARGEST_FIRST,
        columns=HOLDING_COLUMNS,
        note="N-PORT positions at each fund's latest report date (within the date "
        "range, if given), largest first. pct_val is percent of net assets.",
        fallback="top_holdings (NFN/MFRPH10) has the 10 largest positions.",
    ),
    "managers": ReportSpec(
        "NFN/MFRPM",
        "fund",
        date_column="date",
        sort=(("date", True), ("manager_index", False)),
        fallback="fund_info lists portfolio_managers.",
    ),
    "flows": ReportSpec(
        "NFN/MFRMF", "fund", fallback="fund_info has total and net assets."
    ),
    "monthly_returns": ReportSpec(
        "NFN/MFRMR",
        "security",
        fallback="pricing has 1-month to 10-year and year-to-date total returns.",
    ),
    "benchmarks": ReportSpec(
        BENCHMARKS,
        "benchmark",
        note="grp is the index family (BB = Bloomberg, SNP = S&P, ...); blended "
        "benchmarks combine several indexes.",
    ),
}

ReportName = Literal[
    "fund_master",
    "fund_info",
    "share_classes",
    "fees",
    "pricing",
    "performance",
    "top_holdings",
    "holdings",
    "managers",
    "flows",
    "monthly_returns",
    "benchmarks",
]

# One value, 'A,B' or a list; the schema declares all three (normalized by as_list).
ListArg = str | list[str] | None

# ------------------------------------------------------------------- models


class ShareClassInfo(BaseModel):
    security_id: str
    fund_id: str | None = None
    ticker: str | None = Field(default=None, description="NAV symbol (nav_symbol).")
    exchange_ticker: str | None = Field(
        default=None, description="Exchange ticker of a closed-end fund."
    )
    name: str | None = None
    instrument: str | None = Field(
        default=None, description="open-end fund or closed-end fund."
    )
    inception_date: str | None = None
    final_date: str | None = Field(
        default=None,
        description="Last trading date of a merged or liquidated share class.",
    )


class FundMatch(BaseModel):
    fund_id: str
    name: str | None = None
    investment_company_type: str | None = Field(
        default=None, description="N-1A (open-end mutual fund) or N-2 (closed-end)."
    )
    termination_date: str | None = None
    share_classes: list[ShareClassInfo] = Field(default_factory=list)


class FundSearchResult(BaseModel):
    """Funds and their share classes matching a ticker, name, CUSIP or id."""

    query: str
    matched_by: str = Field(
        description="How the query matched: ticker, cusip, security_id, fund_id, "
        "name or all (empty query)."
    )
    funds: list[FundMatch]
    fund_count: int = Field(description="Funds in `funds`.")
    share_class_count: int = Field(description="Share classes listed in `funds`.")
    has_more: bool = Field(description="True when more funds matched than shown.")
    access: str | None = Field(
        default=None,
        description="What a free API key gets: free, sample, subscription or unknown.",
    )
    notes: list[str] = Field(default_factory=list)


class FundReport(TableResult):
    """Rows of one Mutual Fund Reports table for the requested funds."""

    report: str = Field(description="Report that was read.")
    resolved: list[ShareClassInfo] | None = Field(
        default=None,
        description="Share classes the tickers or ids resolved to through NFN/MFRSM.",
    )
    benchmark_names: dict[str, str] | None = Field(
        default=None,
        description="benchmark_id -> name, for the ids NFN/MFRPB lists.",
    )


# ------------------------------------------------------------------ helpers


def _unique(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(v) for v in values if v))


def _codes(value: ListArg, param: str) -> list[str]:
    """Validated tickers (upper case) or UUIDs (lower case) of one parameter."""
    codes = as_list(value)
    pattern, kind = TICKER_RE, "a ticker such as 'LIBAX'"
    if param != "tickers":
        codes, pattern, kind = [c.lower() for c in codes], UUID_RE, "a UUID"
    bad = [c for c in codes if not pattern.match(c)]
    if bad:
        raise InvalidRequestError(
            f"{param}: {bad[0]!r} is not {kind}. ndl_search_mutual_funds finds "
            "tickers, fund_id and security_id values by fund name."
        )
    if len(codes) > MAX_IDS:
        raise InvalidRequestError(f"Pass at most {MAX_IDS} {param}.")
    return codes


def _share_class(row: dict[str, Any]) -> ShareClassInfo:
    code = row.get("instrument_code")
    return ShareClassInfo(
        security_id=str(row.get("security_id")),
        fund_id=row.get("fund_id"),
        ticker=row.get("nav_symbol"),
        exchange_ticker=row.get("ticker_symbol"),
        name=row.get("name"),
        instrument=INSTRUMENTS.get(code, code) if code else None,
        inception_date=row.get("inception_date"),
        final_date=row.get("final_date"),
    )


async def _lookup(
    ctx: Context,
    filters: dict[str, Any],
    code: str = SECURITY_MASTER,
    columns: Sequence[str] = SM_COLUMNS,
) -> list[dict[str, Any]]:
    """Master-table rows for fixed filter columns (no metadata request)."""
    read = await read_table(ctx, code, filters=filters, columns=columns, validate=False)
    return read.records()


async def _funds_of(ctx: Context, fund_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not fund_ids:
        return {}
    rows = await _lookup(ctx, {"fund_id": fund_ids}, FUND_MASTER, FM_COLUMNS)
    return {str(r["fund_id"]): r for r in rows}


def _exact_lookups(text: str) -> list[tuple[str, str]]:
    """(NFN/MFRSM column, value) pairs a one-word query is looked up by, in order."""
    lower, upper = text.lower(), text.upper()
    if UUID_RE.match(lower):
        return [("security_id", lower), ("fund_id", lower)]
    if CUSIP_RE.match(upper):
        return [("cusip", upper)]
    if TICKER_RE.match(upper) and len(upper) <= 6:  # longer words are names
        return [("nav_symbol", upper), ("ticker_symbol", upper)]
    return []


def _search_result(
    ctx: Context,
    query: str,
    matched_by: str,
    order: Sequence[str],
    funds: dict[str, dict[str, Any]],
    classes: Sequence[dict[str, Any]],
    notes: list[str],
    has_more: bool = False,
) -> CallToolResult:
    """Funds in ``order``, each with its share classes from ``classes``."""
    by_fund: dict[str, list[ShareClassInfo]] = {}
    for row in sorted(classes, key=lambda r: r.get("name") or ""):
        by_fund.setdefault(str(row.get("fund_id")), []).append(_share_class(row))
    matches = [
        FundMatch(
            fund_id=fund_id,
            **{k: funds.get(fund_id, {}).get(k) for k in FM_COLUMNS[1:]},
            share_classes=by_fund.get(fund_id, []),
        )
        for fund_id in order
    ]
    access = access_for(app_state(ctx), SECURITY_MASTER, None)
    if access == "sample":
        notes.append(FREE_SAMPLE_NOTE)
    return to_tool_result(
        FundSearchResult(
            query=query,
            matched_by=matched_by,
            funds=matches,
            fund_count=len(matches),
            share_class_count=sum(len(m.share_classes) for m in matches),
            has_more=has_more,
            access=access,
            notes=notes,
        )
    )


# -------------------------------------------------------------------- tools


async def ndl_search_mutual_funds(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            max_length=MAX_QUERY_LEN,
            description="A share-class ticker ('LIBAX'), words of a fund or "
            "share-class name ('columbia bond'), a CUSIP, or a fund_id/security_id "
            "UUID. Empty lists funds in name order.",
        ),
    ] = "",
    limit: Annotated[
        int, Field(ge=1, le=50, description="Maximum funds to return (default 10).")
    ] = 10,
) -> Annotated[CallToolResult, FundSearchResult]:
    """Find mutual funds and their share classes by ticker, name, CUSIP or id.

    Searches the Nasdaq Fund Network fund master (NFN/MFRFM) and share-class
    master (NFN/MFRSM). A ticker, CUSIP or id is an exact lookup; otherwise a
    fund matches when every word of the query appears in its fund or share-class
    name, ignoring case. Each fund comes with fund_id, name and type, and its
    share classes with security_id, ticker and inception date.

    The full tables cover US open-end and closed-end funds; a free key sees a
    fixed sample of about 30 funds. The tickers and ids feed
    ndl_get_mutual_fund_report.
    """
    text = query.strip()
    notes: list[str] = []
    lookups = _exact_lookups(text)
    for column, value in lookups:
        if classes := await _lookup(ctx, {column: value}):
            fund_ids = _unique(r.get("fund_id") for r in classes)
            funds = await _funds_of(ctx, fund_ids)
            matched_by = "ticker" if column.endswith("symbol") else column
            return _search_result(
                ctx, text, matched_by, fund_ids, funds, classes, notes
            )
    if lookups and lookups[0][0] == "security_id":
        notes.append(f"No fund or share class has the id {text.lower()}.")
        return _search_result(ctx, text, "fund_id", [], {}, [], notes)

    reads = [
        await read_table(
            ctx, code, columns=cols, max_pages=NAME_SCAN_PAGES, validate=False
        )
        for code, cols in ((FUND_MASTER, FM_COLUMNS), (SECURITY_MASTER, SM_COLUMNS))
    ]
    if any(read.next_cursor for read in reads):
        notes.append(
            f"Name search read the first {NAME_SCAN_PAGES * MAX_PAGE_SIZE:,} rows "
            "of each master table; a ticker or id lookup is exact."
        )
    funds = {str(r["fund_id"]): r for r in reads[0].records()}
    words = _WORD_RE.findall(text.lower())

    def hit(name: str | None) -> bool:
        return all(w in (name or "").lower() for w in words)

    hit_funds = {f for f, r in funds.items() if hit(r.get("name"))}
    classes = [
        r
        for r in reads[1].records()
        if r.get("fund_id") in hit_funds or hit(r.get("name"))
    ]
    class_names = {str(r.get("fund_id")): r.get("name") for r in reversed(classes)}
    lower = text.lower()

    def rank(fund_id: str) -> tuple[bool, bool, str, str]:
        """Exact name first, then names starting with the query, then A-Z."""
        name = funds.get(fund_id, {}).get("name") or class_names.get(fund_id) or ""
        name = name.lower()
        return (name != lower, not name.startswith(lower), name, fund_id)

    order = sorted(hit_funds | set(class_names), key=rank)
    if not order:
        notes.append(f"No fund or share class name contains every word of {text!r}.")
    matched_by = "name" if words else "all"
    return _search_result(
        ctx, text, matched_by, order[:limit], funds, classes, notes, len(order) > limit
    )


async def ndl_get_mutual_fund_report(
    ctx: Context,
    report: Annotated[
        ReportName,
        Field(
            description="fund_info: objective, assets; fees: expense ratios, loads; "
            "pricing: NAV, returns vs benchmark; performance: alpha, beta, Sharpe; "
            "holdings, top_holdings: N-PORT positions; flows: sales, redemptions."
        ),
    ],
    tickers: Annotated[
        ListArg,
        Field(description="Share-class tickers (nav_symbol), not names: 'LIBAX'."),
    ] = None,
    security_ids: Annotated[ListArg, Field(description="Share-class UUID(s).")] = None,
    fund_ids: Annotated[ListArg, Field(description="Fund UUID(s).")] = None,
    benchmark_ids: Annotated[ListArg, Field(description="Benchmark UUID(s).")] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    columns: Annotated[
        ListArg, Field(description="Columns to return, or 'all'.")
    ] = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, FundReport]:
    """Read a Nasdaq Fund Network mutual fund report (NFN/MFR*).

    Funds are exact tickers or ids from ndl_search_mutual_funds. Rows are
    newest first; holdings largest first, at the latest N-PORT date. A free
    key gets a different fixed sample per table, so some reports are empty for a
    fund; flows and monthly_returns need a subscription.
    """
    spec = REPORTS[report]
    raw = zip(ID_COLUMNS, (tickers, security_ids, fund_ids), strict=True)
    given = {param: codes for param, value in raw if (codes := _codes(value, param))}
    benchmark_list = _codes(benchmark_ids, "benchmark_ids")
    if len(given) > 1:
        raise InvalidRequestError(
            "Pass only one of tickers, security_ids or fund_ids "
            f"(got {', '.join(given)})."
        )
    if spec.key == "benchmark" and given:
        raise InvalidRequestError(
            "The benchmarks report is the benchmark dictionary; filter it with "
            "benchmark_ids. A share class's benchmark returns are in the pricing "
            "and performance reports."
        )
    if benchmark_list and report not in (*BENCHMARKED, "benchmarks"):
        raise InvalidRequestError(
            "benchmark_ids applies to the pricing, performance and benchmarks reports."
        )
    if (start_date or end_date) and not spec.date_column:
        dated = ", ".join(k for k, s in REPORTS.items() if s.date_column)
        raise InvalidRequestError(
            f"The {report} report has no date filter. Date ranges apply to: {dated}."
        )
    filters: dict[str, Any] = (
        date_range(spec.date_column, start_date, end_date) if spec.date_column else {}
    )

    notes: list[str] = []
    resolved: list[dict[str, Any]] | None = None
    keys = benchmark_list
    if spec.key != "benchmark":
        keys, resolved = await _report_keys(ctx, spec, given, notes)
        if benchmark_list:
            filters["benchmark_id"] = benchmark_list
    if keys:
        filters[spec.key_column] = keys
    latest: dict[str, str] = {}  # holdings: fund_id -> its latest report date
    if spec.table == HOLDINGS and keys:
        latest = await _latest_holding_dates(ctx, filters)
        if latest:
            filters = {"fund_id": list(latest), "date": sorted(set(latest.values()))}

    try:
        result = await fetch_table(
            ctx,
            spec.table,
            filters=filters,
            columns=_report_columns(spec, columns),
            limit=limit,
            sort_by=list(spec.sort) if keys else None,
            row_filter=(lambda r: latest.get(str(r.get("fund_id"))) == r.get("date"))
            if latest
            else None,
            notes=[spec.note] if spec.note else (),
        )
    except SubscriptionRequiredError as exc:
        if not spec.fallback:
            raise
        raise SubscriptionRequiredError(
            f"{exc.message} {spec.fallback}", code=exc.code, status=exc.status
        ) from None

    if not result.rows and spec.fallback and result.access == "sample":
        notes.append(spec.fallback)
    names = [c.name for c in result.columns]
    benchmark_names: dict[str, str] | None = None
    if report in BENCHMARKED and "benchmark_id" in names:
        index = names.index("benchmark_id")
        wanted = _unique(r[index] for r in result.rows if r[index] != NIL_UUID)
        if wanted:
            benchmark_names = await _benchmark_names(ctx, wanted, notes)

    out = FundReport(
        # The tool takes no cursor, so a page cursor would be a dead end.
        **result.model_dump(exclude={"next_cursor", "notes"}),
        notes=[*result.notes, *notes],
        report=report,
        resolved=None if resolved is None else [_share_class(r) for r in resolved],
        benchmark_names=benchmark_names,
    )
    return to_tool_result(fit_rows(out, app_state(ctx).settings.max_response_bytes))


async def _report_keys(
    ctx: Context, spec: ReportSpec, given: dict[str, list[str]], notes: list[str]
) -> tuple[list[str], list[dict[str, Any]] | None]:
    """Values for ``spec.key_column``; tickers and the other id go via NFN/MFRSM."""
    if not given:
        notes.append(
            "No fund or share class was given: rows are a slice of the table in "
            "Nasdaq's order."
        )
        return [], None
    [(param, values)] = given.items()
    column = ID_COLUMNS[param]
    if column == spec.key_column:
        return values, None
    rows = await _lookup(ctx, {column: values})
    found = {str(r.get(column)).casefold() for r in rows}
    missing = [v for v in values if v.casefold() not in found]
    if len(missing) == len(values):
        sample = access_for(app_state(ctx), SECURITY_MASTER, None) == "sample"
        raise InvalidRequestError(
            f"No share class in NFN/MFRSM has {column} {', '.join(values)}."
            + (" A free key sees only a sample of about 30 funds." if sample else "")
            + " ndl_search_mutual_funds finds funds by name."
        )
    if missing:
        notes.append(f"Not found in NFN/MFRSM: {', '.join(missing)}.")
    keys = _unique(r.get(spec.key_column) for r in rows)
    if len(keys) > MAX_KEYS:
        raise InvalidRequestError(
            f"The {param} cover {len(keys)} {spec.key_column} values; one report "
            f"reads at most {MAX_KEYS}. Pass fewer {param}."
        )
    return keys, rows


def _report_columns(spec: ReportSpec, columns: ListArg) -> list[str] | None:
    if columns is None:
        return list(spec.columns) if spec.columns else None
    wanted = as_list(columns, upper=False)
    if [c.lower() for c in wanted] in ([], ["all"]):
        return None
    required = [spec.key_column, *(["date"] if spec.table == HOLDINGS else [])]
    return list(dict.fromkeys([*required, *wanted]))


async def _latest_holding_dates(
    ctx: Context, filters: dict[str, Any]
) -> dict[str, str]:
    """Latest N-PORT report date per fund. Every report has holding_index 0."""
    probe = await read_table(
        ctx,
        HOLDINGS,
        filters={**filters, "holding_index": 0},
        columns=["fund_id", "date"],
        validate=False,
    )
    latest: dict[str, str] = {}
    for row in probe.records():
        fund, day = str(row.get("fund_id") or ""), str(row.get("date") or "")
        if fund and day > latest.get(fund, ""):
            latest[fund] = day
    return latest


async def _benchmark_names(
    ctx: Context, ids: list[str], notes: list[str]
) -> dict[str, str] | None:
    """Names of ``ids`` from NFN/MFRPB, given up after BENCHMARK_LOOKUP_SECONDS."""
    records: list[dict[str, Any]] = []
    try:
        with anyio.move_on_after(BENCHMARK_LOOKUP_SECONDS) as scope:
            read = await read_table(
                ctx,
                BENCHMARKS,
                filters={"benchmark_id": ids[:MAX_KEYS]},
                columns=("benchmark_id", "name"),
                validate=False,
            )
            records = read.records()
    except NdlError as exc:
        notes.append(f"Benchmark names unavailable: NFN/MFRPB failed ({exc.kind}).")
        return None
    if scope.cancelled_caught:
        notes.append(
            "Benchmark names skipped: NFN/MFRPB did not answer within "
            f"{BENCHMARK_LOOKUP_SECONDS:g} s."
        )
    names = {str(r["benchmark_id"]): str(r["name"]) for r in records if r.get("name")}
    return names or None


# ------------------------------------------------------------------ prompts


def fund_snapshot(
    fund: Annotated[
        str,
        Field(description="A mutual fund ticker or name, e.g. 'LIBAX'."),
    ],
) -> str:
    """Profile a mutual fund: objective, fees, returns vs benchmark, top holdings."""
    fund = " ".join(fund.split())
    if not fund or len(fund) > MAX_QUERY_LEN:
        raise MCPError(
            code=INVALID_PARAMS,
            message="`fund` takes a share-class ticker such as 'LIBAX' or a fund "
            f"name of at most {MAX_QUERY_LEN} characters.",
        )
    return (
        f"Profile the mutual fund {fund} with Nasdaq Fund Network data. Find it "
        "with ndl_search_mutual_funds, then call ndl_get_mutual_fund_report with "
        "its tickers or fund_ids for the fund_info (objective, family, net "
        "assets), fees (expense ratio, loads), pricing (latest total returns "
        "against its benchmark) and top_holdings reports. Show fractions as "
        "percentages, and say which figures are missing because a free key only "
        "sees a sample."
    )


ALL_TABLES = tuple(dict.fromkeys(spec.table for spec in REPORTS.values()))

TOOLSET = Toolset(
    name="funds",
    description="Nasdaq Fund Network mutual fund and closed-end fund reports "
    "(NFN/MFR*): fund search, fees, returns, holdings, managers.",
    tools=(
        ToolSpec(
            ndl_search_mutual_funds,
            "Search mutual funds",
            tables=(FUND_MASTER, SECURITY_MASTER),
        ),
        ToolSpec(
            ndl_get_mutual_fund_report, "Get a mutual fund report", tables=ALL_TABLES
        ),
    ),
    prompts=(PromptSpec(fund_snapshot, "Mutual fund snapshot"),),
    hints=("Mutual fund tickers and names: ndl_search_mutual_funds.",),
)
