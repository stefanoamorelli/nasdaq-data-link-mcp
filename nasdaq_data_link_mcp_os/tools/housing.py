"""US housing: Zillow home values, rents, inventory and sales (ZILLOW/*), free.

ZILLOW/DATA holds one value per ``indicator_id``, ``region_id`` and date. Only
``indicator_id`` and ``region_id`` can be filtered (a date filter returns 422), so
each requested series is read whole and the date range is applied here.

ndl_get_zillow_data takes region ids and indicator ids (or exact indicator
names); the two search tools find them. Region search is a prefix range on the
``region`` column of ZILLOW/REGIONS (``region.gte`` / ``region.lt``). Nasdaq
compares those ignoring case, spaces and punctuation, so 'Austin TX' finds both
'Austin, TX' (metro) and 'Austin;TX;...' (city); a comma in a range value is
read as a list and rejected, so commas are sent as spaces. Indicator names come
live from the 56-row ZILLOW/INDICATORS table, kept for a day per API client.
"""

from __future__ import annotations

import re
import time
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, get_args

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.client import NasdaqDataLinkClient
from nasdaq_data_link_mcp_os.errors import InvalidRequestError, UpstreamError
from nasdaq_data_link_mcp_os.results import (
    ColumnInfo,
    TableResult,
    fit_rows,
    to_tool_result,
)
from nasdaq_data_link_mcp_os.tools._common import (
    EndDateArg,
    LimitArg,
    PromptSpec,
    StartDateArg,
    TableRead,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    read_table,
)

DATA_TABLE = "ZILLOW/DATA"
REGIONS_TABLE = "ZILLOW/REGIONS"
INDICATORS_TABLE = "ZILLOW/INDICATORS"

RegionType = Literal["state", "metro", "county", "city", "zip", "neighborhood"]
REGION_TYPES: tuple[str, ...] = get_args(RegionType)
_TO_API = {"neighborhood": "neigh"}  # region type -> Zillow's spelling
_FROM_API = {api: ours for ours, api in _TO_API.items()}
_TYPE_ORDER = {t: i for i, t in enumerate(REGION_TYPES)}  # larger areas first

# Region types with data, by indicator category (our checks of ZILLOW/DATA).
_COVERAGE: dict[str, tuple[str, ...]] = {
    "Home values": REGION_TYPES,
    "Rentals": ("metro", "zip"),
    "Inventory and sales": ("metro",),
}
_TIERS = frozenset({"ZATT", "ZABT"})  # top/bottom tier: no ZIPs or neighborhoods

MAX_REGIONS = 10  # 10 weekly series of ~900 rows fit in one 10,000-row page
MAX_DATA_PAGES = 2
INDICATORS_TTL_SECONDS = 24 * 3600.0
_REGION_ID_RE = re.compile(r"^\d{1,7}$")
_METRO_STATE_RE = re.compile(r",\s*([A-Z]{2}(?:-[A-Z]{2})*)$")

_clock = time.monotonic  # replaced in tests


# ------------------------------------------------------------------ models


class ZillowRegion(BaseModel):
    region_id: str = Field(
        description="Zillow region id, as ndl_get_zillow_data takes."
    )
    region_type: str = Field(
        description="state, metro, county, city, zip or neighborhood."
    )
    name: str
    state: str | None = Field(
        default=None,
        description="State code; metros spanning states list each, e.g. 'NY-NJ-PA'.",
    )
    parents: list[str] | None = Field(
        default=None,
        description="Larger areas Zillow records for the region (metro, city, "
        "county), in Zillow's order.",
    )
    match: str | None = Field(
        default=None,
        description="exact (the name, with or without its state) or prefix.",
    )


class RegionSearchResult(BaseModel):
    """Zillow regions whose name starts with the query, exact names first."""

    query: str
    region_type: str | None = None
    results: list[ZillowRegion]
    result_count: int
    total_matches: int
    has_more: bool
    notes: list[str] = Field(default_factory=list)


class ZillowIndicator(BaseModel):
    indicator_id: str
    name: str
    category: str = Field(description="Home values, Rentals or Inventory and sales.")
    frequency: str = Field(description="monthly, or weekly (dated on Saturdays).")
    region_types: list[str] = Field(
        description="Region types with data for this indicator in ZILLOW/DATA."
    )


class IndicatorListResult(BaseModel):
    """Zillow indicators available in ZILLOW/DATA."""

    indicators: list[ZillowIndicator]
    result_count: int
    notes: list[str] = Field(default_factory=list)


class ZillowSeries(BaseModel):
    region_id: str
    region_type: str
    region: str = Field(description="Region label.")
    rows: int = Field(description="Rows in the requested date range, before `limit`.")
    available_from: str | None = Field(
        default=None, description="First date of this series in ZILLOW/DATA."
    )
    available_to: str | None = Field(
        default=None, description="Last date of this series in ZILLOW/DATA."
    )
    latest_date: str | None = Field(
        default=None, description="Newest date in the requested range."
    )
    latest_value: float | None = None


class ZillowDataResult(TableResult):
    """Rows of one Zillow indicator (date, region_id, value), newest first."""

    indicator: ZillowIndicator
    series: list[ZillowSeries] = Field(
        description="One entry per requested region, in request order."
    )


# ------------------------------------------------------------------ regions


def _key(text: str) -> str:
    """Text without case, spaces or punctuation, as Nasdaq compares ranges."""
    return re.sub(r"[\W_]+", "", text).casefold()


@dataclass(frozen=True)
class Region:
    region_id: str
    region_type: str
    name: str
    state: str | None = None
    parents: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        if self.region_type in ("state", "metro") or not self.state:
            return self.name
        return f"{self.name}, {self.state}"

    def is_named(self, query: str) -> bool:
        """The query is the name, with or without its state ('Austin TX')."""
        name = _key(self.name)
        base = _key(self.name.rsplit(",", 1)[0])  # metros: 'Austin, TX'
        return _key(query) in {name, base, name + _key(self.state or "")}

    def model(self, match: str | None = None) -> ZillowRegion:
        return ZillowRegion(
            region_id=self.region_id,
            region_type=self.region_type,
            name=self.name,
            state=self.state,
            parents=list(self.parents) or None,
            match=match,
        )


def parse_region(region_id: Any, region_type: Any, raw: Any) -> Region:
    """Split a ZILLOW/REGIONS row into name, state and parent areas.

    Rows look like 'Austin;TX;Austin-Round Rock-Georgetown, TX;Travis County'
    (some use '; '); 'nan' marks a missing part and ZIP codes lost their
    leading zeros ('8904' is 08904).
    """
    rid, text = str(region_id), str(raw or "")
    kind = _FROM_API.get(str(region_type or ""), str(region_type or ""))
    parts = [p.strip() for p in text.split(";")]
    parts = [p for p in parts if p and p.lower() != "nan"] or [text or rid]
    name, rest = parts[0], parts[1:]
    if kind == "metro":
        match = _METRO_STATE_RE.search(name)
        return Region(rid, kind, name, match.group(1) if match else None)
    state = None
    if rest and re.fullmatch(r"[A-Z]{2}", rest[0]):
        state, rest = rest[0], rest[1:]
    if kind == "zip" and name.isdigit():
        name = name.zfill(5)
    return Region(rid, kind, name, state, tuple(rest))


def _require_columns(read: TableRead, names: tuple[str, ...]) -> None:
    if not set(names) <= set(read.column_names):
        raise UpstreamError(f"{read.code} returned unexpected columns.")


def _regions(read: TableRead) -> list[Region]:
    _require_columns(read, ("region_id", "region_type", "region"))
    return [
        parse_region(r["region_id"], r["region_type"], r["region"])
        for r in read.records()
        if _REGION_ID_RE.match(str(r["region_id"]))
    ]


def upper_bound(prefix: str) -> str | None:
    """Smallest string above every string that starts with ``prefix``.

    Trailing 'z', '9' and punctuation are dropped first so the bound stays a
    letter or digit whatever the collation does with symbols; the range may
    then be a little wider than the prefix.
    """
    stem = prefix.rstrip()
    while stem and (stem[-1] in "zZ9" or not stem[-1].isalnum()):
        stem = stem[:-1]
    if not stem:
        return None
    return stem[:-1] + chr(ord(stem[-1]) + 1)


# --------------------------------------------------------------- indicators


def _indicator(record: dict[str, Any]) -> ZillowIndicator:
    indicator_id = str(record["indicator_id"]).strip().upper()
    category = " ".join(str(record["category"] or "").split())
    types = _COVERAGE.get(category, REGION_TYPES)
    if indicator_id in _TIERS:
        types = types[:4]
    weekly = category == "Inventory and sales" and indicator_id.endswith("W")
    return ZillowIndicator(
        indicator_id=indicator_id,
        name=" ".join(str(record["indicator"] or indicator_id).split()),
        category=category,
        frequency="weekly" if weekly else "monthly",
        region_types=list(types),
    )


# One entry per API client, so separate servers (and tests) never share state.
_INDICATORS: weakref.WeakKeyDictionary[
    NasdaqDataLinkClient, tuple[float, tuple[ZillowIndicator, ...]]
] = weakref.WeakKeyDictionary()


async def load_indicators(ctx: Context) -> tuple[ZillowIndicator, ...]:
    """The ZILLOW/INDICATORS rows, read live and kept for a day."""
    client = app_state(ctx).client
    cached = _INDICATORS.get(client)
    if cached is not None and _clock() - cached[0] < INDICATORS_TTL_SECONDS:
        return cached[1]
    read = await read_table(
        ctx,
        INDICATORS_TABLE,
        columns=["indicator_id", "indicator", "category"],
        page_size=1000,
        use_cache=False,
        validate=False,
    )
    _require_columns(read, ("indicator_id", "indicator", "category"))
    order = list(_COVERAGE)  # Nasdaq returns the rows in no stable order
    indicators = tuple(
        sorted(
            (_indicator(r) for r in read.records() if r["indicator_id"]),
            key=lambda i: (
                order.index(i.category) if i.category in order else len(order),
                i.indicator_id,
            ),
        )
    )
    if not indicators:  # never keep an empty list for a day
        raise UpstreamError(f"Nasdaq returned no {INDICATORS_TABLE} rows; retry.")
    _INDICATORS[client] = (_clock(), indicators)
    return indicators


def _matching(
    indicators: Sequence[ZillowIndicator], text: str
) -> list[ZillowIndicator]:
    """Indicators whose id, name or category contain every word of ``text``."""
    words = text.casefold().split()
    return [
        i
        for i in indicators
        if all(w in f"{i.indicator_id} {i.name} {i.category}".casefold() for w in words)
    ]


def resolve_indicator(
    indicators: Sequence[ZillowIndicator], text: str
) -> ZillowIndicator:
    """The indicator with this id or exact name (case and punctuation aside)."""
    key = _key(text)
    for indicator in indicators:
        if key in (_key(indicator.indicator_id), _key(indicator.name)):
            return indicator
    close = "; ".join(
        f"{i.indicator_id} ({i.name})" for i in _matching(indicators, text)[:5]
    )
    raise InvalidRequestError(
        f"{text!r} is not a Zillow indicator id or name."
        + (f" Containing those words: {close}." if close else "")
        + " ndl_search_zillow_indicators lists the ids."
    )


# ----------------------------------------------------------------- helpers


def _round(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 2) if abs(number) >= 1 else round(number, 4)


_DATA_COLUMNS = [
    ColumnInfo(name="date", type="Date"),
    ColumnInfo(name="region_id", type="text"),
    ColumnInfo(name="value", type="double"),
]


# ------------------------------------------------------------------- tools


async def ndl_search_zillow_regions(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=100,
            description="Start of the region name as Zillow spells it, optionally "
            "followed by the state code ('Austin, TX', 'Saint Louis'), or a ZIP "
            "code ('78701').",
        ),
    ],
    region_type: Annotated[
        RegionType | None,
        Field(
            description="Only regions of this type. The national series is the "
            "metro 'United States'."
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum results.")] = 20,
) -> Annotated[CallToolResult, RegionSearchResult]:
    """Find Zillow region ids (state, metro, county, city, ZIP, neighborhood) by name.

    Searches ZILLOW/REGIONS (about 89,000 regions, free) for names that start
    with the query, ignoring case and punctuation. Exact names rank first, then
    larger areas. Results carry the region_id that ndl_get_zillow_data takes,
    the type, the state and the larger areas Zillow lists for the region.

    One place often exists at several levels (city, metro, county), each with
    its own id. Metros have every indicator (home values, rents, inventory and
    sales), ZIP codes home values and rents, other levels home values only.
    """
    text = " ".join(query.replace(",", " ").split())
    prefix = text.lstrip("0") if text.isdigit() else text  # ZIPs lost their 0s
    if len(_key(prefix)) < 2:
        raise InvalidRequestError(
            f"{query!r} is too short; give at least two letters or digits."
        )
    filters = {"region.gte": prefix}
    upper = upper_bound(prefix)
    if upper:
        filters["region.lt"] = upper
    if region_type:
        filters["region_type"] = _TO_API.get(region_type, region_type)
    read = await read_table(ctx, REGIONS_TABLE, filters=filters, validate=False)
    regions = _regions(read)
    if text.isdigit():  # '8904' also reads ZIP codes 89040 to 89049
        regions = [r for r in regions if r.name.startswith(text)]
    ranked = sorted(
        ((r, "exact" if r.is_named(text) else "prefix") for r in regions),
        key=lambda hit: (
            hit[1] != "exact",
            _TYPE_ORDER.get(hit[0].region_type, 9),
            len(hit[0].name),
            hit[0].name,
            int(hit[0].region_id),
        ),
    )
    notes: list[str] = []
    if read.next_cursor:
        notes.append(
            f"More than {len(read.rows):,} regions start with {text!r}; only "
            "those were ranked. Give more of the name or a region_type."
        )
    if not ranked:
        notes.append(
            f"No region name starts with {text!r}; names match from their start, "
            "as Zillow spells them (St. and Saint differ)."
        )
    return to_tool_result(
        RegionSearchResult(
            query=query,
            region_type=region_type,
            results=[r.model(match) for r, match in ranked[:limit]],
            result_count=min(len(ranked), limit),
            total_matches=len(ranked),
            has_more=len(ranked) > limit,
            notes=notes,
        )
    )


async def ndl_search_zillow_indicators(
    ctx: Context,
    query: Annotated[
        str | None,
        Field(
            max_length=100,
            description="Words that must all appear in the id, name or category, "
            "e.g. 'condo' or 'sale price weekly'. Without them all are listed.",
        ),
    ] = None,
    category: Annotated[
        Literal["all", "home_values", "rentals", "inventory_and_sales"],
        Field(description="Only indicators in this category."),
    ] = "all",
    region_type: Annotated[
        RegionType | None,
        Field(description="Only indicators that cover this region type."),
    ] = None,
) -> Annotated[CallToolResult, IndicatorListResult]:
    """Search the 56 Zillow indicators by keyword, category or region type.

    Home values (ZHVI: all homes, single-family, condo, top and bottom tier,
    1 to 5+ bedrooms), rents (ZORI) and inventory and sales (sale and list
    prices, for-sale inventory, days to pending, price cuts, monthly and
    weekly). Reads the free ZILLOW/INDICATORS table, kept for a day; each result
    lists the region types that have data.
    """
    indicators: list[ZillowIndicator] = list(await load_indicators(ctx))
    notes: list[str] = []
    if query and query.strip():
        indicators = _matching(indicators, query)
        if not indicators:
            notes.append(f"No indicator id, name or category contains {query!r}.")
    if category != "all":
        indicators = [
            i for i in indicators if i.category.lower().replace(" ", "_") == category
        ]
    if region_type:
        indicators = [i for i in indicators if region_type in i.region_types]
    notes.append(
        "Home value series end 2025-01-31 for metros, ZIP codes and the United "
        "States (metro 102001) and 2025-06-30 for other regions; rents end "
        "2022-07-31; inventory and sales (metros only) end in early 2025. Nasdaq "
        "no longer updates ZILLOW/DATA."
    )
    return to_tool_result(
        IndicatorListResult(
            indicators=indicators, result_count=len(indicators), notes=notes
        )
    )


async def ndl_get_zillow_data(
    ctx: Context,
    indicator: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="Indicator id ('ZALL' is home values, all homes) or exact "
            "name, from ndl_search_zillow_indicators.",
        ),
    ],
    regions: Annotated[
        str | list[str],
        Field(
            description="Up to 10 region ids from ndl_search_zillow_regions, e.g. "
            "'394355' or ['9', '102001'].",
        ),
    ],
    region_type: Annotated[
        RegionType | None,
        Field(description="When set, every region id must be of this type."),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, ZillowDataResult]:
    """Get Zillow home values, rents, inventory or sales for up to 10 US regions.

    Reads ZILLOW/DATA (free; last updated July 2025): date, region_id, value
    rows, newest first, and a summary per region. Regions are ids, not names:
    ndl_search_zillow_regions finds them, and ndl_search_zillow_indicators lists
    indicator ids and the region types each covers.
    """
    date_range("date", start_date, end_date)  # validates format and order
    ids = as_list(regions, upper=False)
    bad = [i for i in ids if not _REGION_ID_RE.match(i)]
    if bad or not ids:
        raise InvalidRequestError(
            "regions takes Zillow region ids (digits)"
            + (f"; not ids: {', '.join(repr(b) for b in bad)}" if bad else "")
            + ". ndl_search_zillow_regions finds them by place name or ZIP code."
        )
    if len(ids) > MAX_REGIONS:
        raise InvalidRequestError(
            f"{len(ids)} regions requested; the limit is {MAX_REGIONS} per call."
        )
    ind = resolve_indicator(await load_indicators(ctx), indicator)
    lookup = await read_table(
        ctx, REGIONS_TABLE, filters={"region_id": ids}, page_size=100, validate=False
    )
    known = {r.region_id: r for r in _regions(lookup)}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise InvalidRequestError(
            f"Unknown Zillow region_id(s): {', '.join(unknown)}. "
            "ndl_search_zillow_regions finds ids by place name or ZIP code."
        )
    wrong = [
        known[i] for i in ids if region_type and known[i].region_type != region_type
    ]
    if wrong:
        raise InvalidRequestError(
            f"region_type is {region_type}, but "
            + ", ".join(f"{r.region_id} is a {r.region_type}" for r in wrong)
            + "."
        )

    read = await read_table(
        ctx,
        DATA_TABLE,
        filters={"indicator_id": ind.indicator_id, "region_id": ids},
        columns=["region_id", "date", "value"],
        max_pages=MAX_DATA_PAGES,
    )
    _require_columns(read, ("region_id", "date", "value"))
    by_region: dict[str, list[tuple[str, Any]]] = {rid: [] for rid in ids}
    for rec in read.records():
        by_region.setdefault(str(rec["region_id"]), []).append(
            (str(rec["date"])[:10], rec["value"])
        )

    notes: list[str] = []
    series: list[ZillowSeries] = []
    rows: list[list[Any]] = []
    for rid in ids:
        region = known[rid]
        points = sorted(by_region[rid], key=lambda p: p[0], reverse=True)
        window = [
            (d, v)
            for d, v in points
            if (not start_date or d >= start_date) and (not end_date or d <= end_date)
        ]
        if not points:
            covers = ind.region_types
            notes.append(
                f"No {ind.indicator_id} data for region_id {rid}"
                + (
                    f": {ind.indicator_id} covers only {', '.join(covers)} regions."
                    if region.region_type not in covers
                    else "."
                )
            )
        elif not window:
            notes.append(
                f"region_id {rid} has no rows in the requested dates; its series "
                "entry gives the dates available."
            )
        rows += [[d, rid, _round(v)] for d, v in window]
        series.append(
            ZillowSeries(
                region_id=rid,
                region_type=region.region_type,
                region=region.label,
                rows=len(window),
                available_from=points[-1][0] if points else None,
                available_to=points[0][0] if points else None,
                latest_date=window[0][0] if window else None,
                latest_value=_round(window[0][1]) if window else None,
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)  # stable: request order per date
    request = {
        "indicator_id": ind.indicator_id,
        "region_id": ",".join(ids),
        "start_date": start_date,
        "end_date": end_date,
        "sort": "date desc",
    }
    table = build_result(
        ctx,
        read,
        rows,
        limit=limit,
        columns=_DATA_COLUMNS,
        notes=notes,
        request={k: v for k, v in request.items() if v is not None},
    )
    result = ZillowDataResult(**dict(table), indicator=ind, series=series)
    return to_tool_result(fit_rows(result, app_state(ctx).settings.max_response_bytes))


def zillow_housing_snapshot(
    place: Annotated[
        str,
        Field(
            description="US place: a state, metro, county, city, neighborhood or "
            "ZIP code, e.g. 'Austin, TX' or '78701'."
        ),
    ],
) -> str:
    """Summarize a US housing market from Zillow data on Nasdaq Data Link."""
    return (
        f"Summarize the housing market in {place} using the Zillow tools.\n"
        "1. Find the region ids with ndl_search_zillow_regions; note the place "
        "itself and its metro.\n"
        "2. Home values: ndl_get_zillow_data with indicator ZALL for the place "
        "and its metro, limit 36.\n"
        "3. Rents: RSNA for the metro or ZIP (rents end 2022-07).\n"
        "4. Market activity for the metro: SSAM (median sale price), ISAM "
        "(inventory), NSAM (median days to pending), CSAM (share of listings with "
        "a price cut).\n"
        "5. Report the latest levels and the year-over-year changes with the "
        "dates they refer to. Zillow data on Nasdaq stops in 2025, so present it "
        "as historical, not current."
    )


TOOLSET = Toolset(
    name="housing",
    description="US housing from Zillow (free): home values, rents, inventory and "
    "sales by state, metro, county, city, ZIP and neighborhood, 1996 to mid-2025.",
    tools=(
        ToolSpec(
            ndl_search_zillow_regions, "Search Zillow regions", tables=(REGIONS_TABLE,)
        ),
        ToolSpec(
            ndl_get_zillow_data,
            "Get Zillow housing data",
            tables=(DATA_TABLE, REGIONS_TABLE, INDICATORS_TABLE),
        ),
        ToolSpec(
            ndl_search_zillow_indicators,
            "Search Zillow housing indicators",
            tables=(INDICATORS_TABLE,),
        ),
    ),
    prompts=(PromptSpec(zillow_housing_snapshot, "Zillow housing snapshot"),),
)
