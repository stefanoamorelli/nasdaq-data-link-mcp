"""Crypto: Bitfinex daily prices and Bitcoin on-chain metrics.

Both tables are free and have not been updated since June 2026. Codes are
checked against bundled code lists, so a typo gets candidate codes back instead
of an empty result.

Nasdaq returns rows unsorted and both tables hold years of daily rows per code.
One request reads every code over a recent window sized from ``limit``. A code
with fewer rows than its share (gaps, thin trading, a pair or metric that
stopped) is read again on its own over the whole requested range: one page
(10,000 rows) holds a code's full daily history.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta
from functools import lru_cache
from importlib import resources
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.results import TableResult, fit_rows, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    EndDateArg,
    LimitArg,
    StartDateArg,
    TableRead,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    get_metadata,
    read_table,
)

BITFINEX = "QDL/BITFINEX"
BCHAIN = "QDL/BCHAIN"
MAX_PAIRS = 20
# The first read covers ceil(rows per code * 1.4) + 14 days, enough for codes
# with missing days (BCHAIN skips up to 1 day in 5 since mid-2025).
WINDOW_FACTOR = 1.4
WINDOW_PAD_DAYS = 14
MAX_REREADS = 5
# A code whose newest row is this much older than the table's is reported.
ENDED_AFTER_DAYS = 31
_SEPARATORS = re.compile(r"[\s/\-_:.]+")


class MetricInfo(BaseModel):
    label: str
    unit: str | None = None


def _load(name: str) -> dict[str, Any]:
    text = (
        resources.files("nasdaq_data_link_mcp_os")
        .joinpath(f"data/{name}")
        .read_text(encoding="utf-8")
    )
    data: dict[str, Any] = json.loads(text)
    return data


@lru_cache(maxsize=1)
def _pairs() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(current, ended) Bitfinex pair codes."""
    raw = _load("crypto_bitfinex_pairs.json")
    return tuple(raw["current"]), tuple(raw["ended"])


@lru_cache(maxsize=1)
def _metrics() -> tuple[dict[str, MetricInfo], tuple[str, ...]]:
    """(code -> label and unit, discontinued codes) for QDL/BCHAIN."""
    raw = _load("crypto_bchain_metrics.json")
    info = {code: MetricInfo(**m) for code, m in raw["metrics"].items()}
    return info, tuple(raw["discontinued"])


# ------------------------------------------------------------ resolution


def _unknown(
    kind: str, text: str, query: str, labels: Mapping[str, str], fallback: str
) -> InvalidRequestError:
    """Error listing up to 5 codes whose code or label contains ``query``."""
    needle = query.casefold()
    found = [
        f"{code} ({label})" if label else code
        for code, label in labels.items()
        if needle and (needle in code.casefold() or needle in label.casefold())
    ][:5]
    hint = f"Matching codes: {', '.join(found)}." if found else fallback
    return InvalidRequestError(f"Unknown {kind} {text!r}. {hint}")


def resolve_pairs(values: Sequence[str]) -> list[str]:
    """Bitfinex codes for 'BTCUSD', 'btc/usd' or 'BTC-USD' (exact codes only)."""
    current, ended = _pairs()
    known = dict.fromkeys((*current, *ended), "")
    out: list[str] = []
    for text in values:
        code = _SEPARATORS.sub("", text).upper()
        if code not in known:
            raise _unknown(
                "Bitfinex pair",
                text,
                code,
                known,
                f"Pairs with rows up to June 2026: {', '.join(current)}. Codes join "
                "two Bitfinex symbols; Bitfinex writes USDT as UST and USDC as UDC.",
            )
        out.append(code)
    return list(dict.fromkeys(out))


def resolve_metrics(values: Sequence[str]) -> list[str]:
    """QDL/BCHAIN codes for exact codes; 'all' means every current metric."""
    info, discontinued = _metrics()
    current = [c for c in info if c not in discontinued]
    labels = {c: f"{m.label}, {m.unit}" if m.unit else m.label for c, m in info.items()}
    out: list[str] = []
    for text in values:
        code = text.strip().upper()
        if code == "ALL":
            out += current
        elif code in info:
            out.append(code)
        else:
            raise _unknown(
                "blockchain metric",
                text,
                text.strip(),
                labels,
                "Current codes: "
                + "; ".join(f"{c} ({labels[c]})" for c in current)
                + f". Discontinued: {', '.join(discontinued)}.",
            )
    return list(dict.fromkeys(out))


# ------------------------------------------------------------ reading


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _by_code(read: TableRead, codes: Sequence[str]) -> dict[str, list[list[Any]]]:
    """Rows of each code in ``codes``, newest first."""
    out: dict[str, list[list[Any]]] = {c: [] for c in codes}
    if not read.rows:
        return out
    names = read.column_names
    code_at, date_at = names.index("code"), names.index("date")
    for row in read.rows:
        key = str(row[code_at]).upper()
        if key in out:
            out[key].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: str(r[date_at]), reverse=True)
    return out


async def _read_newest(
    ctx: Context,
    table: str,
    codes: Sequence[str],
    *,
    start: str | None,
    end: str | None,
    limit: int | None,
    columns: Sequence[str] | None = None,
) -> tuple[TableRead, bool, list[str]]:
    """The newest rows of each code, newest first, with ``limit`` shared.

    Returns a TableRead holding the selected rows, whether more rows matched,
    and notes about the read.
    """
    state = app_state(ctx)
    settings = state.settings
    dates = date_range("date", start, end)  # validates format and order
    limit = max(1, min(limit or settings.default_limit, settings.max_limit))
    per_code = math.ceil(limit / len(codes))
    metadata = await get_metadata(state, table)
    table_end = _day(metadata.refreshed_at if metadata else None)
    anchor = min([d for d in (table_end, _day(end)) if d] or [date.today()])
    days = math.ceil(per_code * WINDOW_FACTOR) + WINDOW_PAD_DAYS
    lower = (anchor - timedelta(days=days)).isoformat()
    windowed = start is None or lower > start
    filters: dict[str, Any] = {"code": list(codes), **dates}
    if windowed:
        filters["date.gte"] = lower
    # Filters and columns are built here from validated values.
    first = await read_table(
        ctx, table, filters=filters, columns=columns, validate=False
    )
    reads = [first]
    by_code = _by_code(first, codes)
    short = [c for c in codes if windowed and len(by_code[c]) < per_code]
    reread = short[:MAX_REREADS]
    for code in reread:
        again = await read_table(
            ctx,
            table,
            filters={"code": code, **dates},
            columns=columns,
            validate=False,
        )
        reads.append(again)
        by_code[code] = _by_code(again, [code])[code]

    notes: list[str] = []
    if short[MAX_REREADS:]:
        notes.append(
            f"{', '.join(short[MAX_REREADS:])} had fewer rows than requested since "
            f"{lower}; ask for them separately to see older rows."
        )
    truncated = any(r.next_cursor for r in reads)
    if truncated:
        notes.append(
            "A read matched more than 10,000 rows, so some rows may be missing. "
            "Narrow the date range."
        )
    complete = [c for c in codes if not windowed or c in reread]
    empty = [c for c in complete if not by_code[c]]
    if empty:
        scope = " in the requested dates" if start or end else ""
        notes.append(f"No rows for {', '.join(empty)}{scope}.")
    date_at = first.column_names.index("date")
    if table_end and (not end or end >= table_end.isoformat()):
        for code in codes:
            newest = _day(str(by_code[code][0][date_at])) if by_code[code] else None
            if newest and (table_end - newest).days > ENDED_AFTER_DAYS:
                notes.append(
                    f"{code} has no rows after {newest}; the table runs to {table_end}."
                )

    # Grouped in code order; the stable sort keeps that order within a date.
    selected = [row for code in codes for row in by_code[code][:per_code]]
    selected.sort(key=lambda r: str(r[date_at]), reverse=True)
    has_more = (
        truncated
        or len(selected) > limit
        or any(len(by_code[c]) > per_code for c in codes)
        # Older rows may exist before the window these codes were read over.
        or len(complete) < len(codes)
    )
    if has_more and selected:
        more = (
            f", or raise limit (max {settings.max_limit})"
            if limit < settings.max_limit
            else ""
        )
        notes.append(
            f"Showing up to {per_code} of the newest rows per code, newest first. "
            f"For older rows, pass an end_date before the oldest date shown for a "
            f"code{more}."
        )
    request = {**first.request, "code": ",".join(codes)}
    if len(reads) > 1:
        request["api_calls"] = len(reads)
    combined = replace(
        first,
        metadata=metadata,
        rows=selected[:limit],
        request=request,
        next_cursor=None,
    )
    return combined, has_more, notes


# ------------------------------------------------------------------- tools


class BlockchainMetricsResult(TableResult):
    """Daily Bitcoin network metrics, one row per code and date, newest first."""

    metrics: dict[str, MetricInfo] = Field(
        default_factory=dict, description="Label and unit of each returned code."
    )


PairsArg = Annotated[
    str | list[str],
    Field(
        description="Up to 20 Bitfinex pair codes, e.g. 'BTCUSD' or ['ETHUSD', "
        "'ETHBTC']; case and separators ('btc/usd') are ignored. Bitfinex writes "
        "USDT as UST and USDC as UDC."
    ),
]
PriceFieldsArg = Annotated[
    list[Literal["high", "low", "mid", "last", "bid", "ask", "volume"]] | None,
    Field(description="Columns to return besides code and date (default: all)."),
]
MetricsArg = Annotated[
    str | list[str],
    Field(
        description="QDL/BCHAIN metric codes such as MKPRU (price) or ['HRATE', "
        "'DIFF']; 'all' selects the 23 metrics that ran until June 2026."
    ),
]


async def ndl_get_crypto_prices(
    ctx: Context,
    pairs: PairsArg,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    fields: PriceFieldsArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Daily Bitfinex crypto prices (last, bid, ask, mid, high, low, volume) by pair.

    Reads QDL/BITFINEX, free with any API key: one row per pair and day, newest
    first. High, low and volume cover 24 hours; volume is in the base asset and
    prices in the second one (BTCUSD in US dollars, ETHBTC in bitcoin). With
    several pairs `limit` is shared between them.

    Nasdaq has not updated the table since 2026-06-22. 44 pairs have rows up to
    then (BTCUSD since 2014); about 850 pairs that left the feed earlier stay
    readable (e.g. SOLUSD). Bitcoin network data is in ndl_get_blockchain_metrics.
    """
    requested = as_list(pairs, upper=False)
    if not requested:
        raise InvalidRequestError("Pass at least one pair, e.g. 'BTCUSD'.")
    codes = resolve_pairs(requested)
    if len(codes) > MAX_PAIRS:
        raise InvalidRequestError(
            f"{len(codes)} pairs requested; the limit is {MAX_PAIRS} per call."
        )
    read, has_more, notes = await _read_newest(
        ctx,
        BITFINEX,
        codes,
        start=start_date,
        end=end_date,
        limit=limit,
        columns=list(dict.fromkeys(["code", "date", *fields])) if fields else None,
    )
    return to_tool_result(
        build_result(
            ctx, read, limit=limit, notes=notes, has_more=has_more, count_note=False
        )
    )


async def ndl_get_blockchain_metrics(
    ctx: Context,
    metrics: MetricsArg,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, BlockchainMetricsResult]:
    """Daily Bitcoin network metrics: price, hash rate, difficulty, fees, transactions.

    Reads QDL/BCHAIN (blockchain.com data), free with any API key: one value per
    metric and day since January 2009, as rows of (code, date, value), newest
    first; the result's `metrics` field gives each code's label and unit. With
    several metrics `limit` is shared between them, so metrics='all' with
    limit=23 returns the latest value of each.

    Nasdaq has not updated the table since 2026-06-23, and some days are missing
    (up to 1 in 5 since mid-2025). Ten discontinued codes (e.g. BCDDE) stay
    readable. Exchange prices of other coins are in ndl_get_crypto_prices.
    """
    requested = as_list(metrics, upper=False)
    if not requested:
        raise InvalidRequestError("Pass at least one metric, e.g. 'MKPRU'.")
    codes = resolve_metrics(requested)
    read, has_more, notes = await _read_newest(
        ctx, BCHAIN, codes, start=start_date, end=end_date, limit=limit
    )
    result = build_result(
        ctx, read, limit=limit, notes=notes, has_more=has_more, count_note=False
    )
    info = _metrics()[0]
    model = BlockchainMetricsResult(
        **result.model_dump(), metrics={c: info[c] for c in codes}
    )
    return to_tool_result(fit_rows(model, app_state(ctx).settings.max_response_bytes))


TOOLSET = Toolset(
    name="crypto",
    description="Crypto: Bitfinex daily prices and Bitcoin on-chain metrics (free).",
    tools=(
        ToolSpec(
            ndl_get_crypto_prices, "Get Bitfinex crypto prices", tables=(BITFINEX,)
        ),
        ToolSpec(
            ndl_get_blockchain_metrics,
            "Get Bitcoin blockchain metrics",
            tables=(BCHAIN,),
        ),
    ),
)
