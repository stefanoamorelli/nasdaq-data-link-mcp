"""World Bank World Development Indicators (WB/DATA and WB/METADATA), free.

WB/DATA holds one value per indicator (``series_id``), economy (``country_code``)
and year. Only ``series_id`` and ``country_code`` can be filtered, so year ranges
are applied here after the rows are read. Countries resolve from the bundled
World Bank list of the 265 WB/DATA codes (217 economies, 48 aggregates) by code,
ISO2 code, exact World Bank name or a short alias map. Indicator names come from
WB/METADATA, whose 1,484 rows are downloaded once and kept for 24 hours.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import weakref
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.client import MAX_PAGE_SIZE, NasdaqDataLinkClient
from nasdaq_data_link_mcp_os.errors import InvalidRequestError, UpstreamError
from nasdaq_data_link_mcp_os.results import (
    ColumnInfo,
    TableResult,
    fit_rows,
    to_tool_result,
)
from nasdaq_data_link_mcp_os.tools._common import (
    EndYearOrDateArg,
    LimitArg,
    PromptSpec,
    StartYearOrDateArg,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    period_bounds,
    read_table,
)

DATA_TABLE = "WB/DATA"
METADATA_TABLE = "WB/METADATA"
DATA_COLUMNS = ("series_id", "country_code", "country_name", "year", "value")
LAST_YEAR = 2023  # latest year in WB/DATA (refreshed by Nasdaq on 2025-08-23)
MAX_INDICATORS = 10
MAX_COUNTRIES = 30
MAX_PAGES = 3
METADATA_TTL_SECONDS = 24 * 3600.0
SORT_ORDER = "year desc, then indicators and countries in the order requested"
SEARCH_TOOL = "ndl_search_world_bank_indicators"
PROFILE_SERIES = tuple(
    "NY.GDP.MKTP.CD NY.GDP.MKTP.KD.ZG NY.GDP.PCAP.CD FP.CPI.TOTL.ZG SL.UEM.TOTL.ZS "
    "SP.POP.TOTL SP.DYN.LE00.IN BN.CAB.XOKA.GD.ZS NE.EXP.GNFS.ZS "
    "GC.DOD.TOTL.GD.ZS".split()
)
# Widely used series, listed first among equally good search matches.
HEADLINE_SERIES = frozenset(PROFILE_SERIES) | frozenset(
    "NY.GDP.MKTP.PP.CD NY.GNP.PCAP.CD SL.UEM.1524.ZS SI.POV.GINI SI.POV.DDAY "
    "NE.IMP.GNFS.ZS BX.KLT.DINV.WD.GD.ZS EN.ATM.CO2E.PC FR.INR.RINR PA.NUS.FCRF "
    "SE.ADT.LITR.ZS IT.NET.USER.ZS SP.DYN.TFRT.IN SP.URB.TOTL.IN.ZS "
    "GC.TAX.TOTL.GD.ZS".split()
)

_clock = time.monotonic  # replaced in tests
_WORD_RE = re.compile(r"[a-z0-9]+")
_SERIES_ID_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")

# ---------------------------------------------------------------- countries


def name_key(text: str) -> str:
    """Case-, accent- and punctuation-insensitive form of a name or code."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = plain.encode("ascii", "ignore").decode().replace("&", " and ")
    return " ".join(_WORD_RE.findall(re.sub(r"[.']", "", plain)))


@dataclass(frozen=True)
class Economy:
    code: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.code} ({self.name})"


@dataclass(frozen=True)
class CountryIndex:
    """WB/DATA economies by code, ISO2 code, World Bank name and alias."""

    economies: dict[str, Economy]
    index: dict[str, str]  # name_key -> code
    ambiguous: dict[str, tuple[str, ...]]

    def resolve(self, text: str) -> Economy:
        key = name_key(text)
        if not key:
            raise InvalidRequestError("A country value is empty.")
        if key in self.index:
            return self.economies[self.index[key]]
        if key in self.ambiguous:
            options = ", ".join(self.economies[c].label for c in self.ambiguous[key])
            raise InvalidRequestError(
                f"Country {text!r} is ambiguous: {options}. Pass one of these codes."
            )
        hits = list(dict.fromkeys(c for k, c in self.index.items() if key in k))
        found = ", ".join(self.economies[c].label for c in hits[:5])
        raise InvalidRequestError(
            f"Unknown country {text!r}."
            + (f" Names or codes containing it: {found}." if found else "")
            + " Countries are ISO3 or ISO2 codes, World Bank aggregate codes (WLD, "
            "EUU, EMU, HIC) or exact World Bank names ('Korea, Rep.')."
        )

    def values(self, value: str | Sequence[str]) -> list[str]:
        """List items, or comma-separated parts of a value that is not one name."""
        items = [value] if isinstance(value, str) else list(value)
        parts: list[str] = []
        for item in items:
            whole = "," not in item or name_key(item) in self.index
            parts.extend([item] if whole else item.split(","))
        return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _read_json(name: str) -> dict[str, Any]:
    path = resources.files("nasdaq_data_link_mcp_os").joinpath(f"data/{name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)  # noqa: S101 - bundled file
    return data


@lru_cache(maxsize=1)
def country_index() -> CountryIndex:
    raw: dict[str, dict[str, str]] = _read_json("wb_economies.json")["economies"]
    extra = _read_json("world_bank_aliases.json")
    index: dict[str, str] = {}
    for code, item in raw.items():
        for text in (code, item.get("iso2"), item["name"]):
            if text:
                index.setdefault(name_key(text), code)
    for alias, code in extra["aliases"].items():
        index.setdefault(name_key(alias), code)
    return CountryIndex(
        economies={code: Economy(code, item["name"]) for code, item in raw.items()},
        index=index,
        ambiguous={name_key(k): tuple(v) for k, v in extra["ambiguous"].items()},
    )


# --------------------------------------------------------------- indicators


def _word_set(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(text.lower()))


@dataclass(frozen=True)
class Indicator:
    series_id: str
    name: str
    description: str
    # Words of the name before '(' (what is measured), of the rest of the name
    # (unit, scope) and of the definition.
    words: tuple[frozenset[str], frozenset[str], frozenset[str]]

    @classmethod
    def build(cls, series_id: str, name: str, description: str) -> Indicator:
        head, _, tail = name.partition("(")
        sets = (_word_set(head), _word_set(tail), _word_set(description))
        return cls(series_id, name, description, sets)

    def snippet(self, size: int = 200) -> str | None:
        text = " ".join(self.description.split())
        if not text:
            return None
        first = text.split(". ")[0].rstrip(".") + "."
        if len(first) <= size:
            return first
        return text[: size - 1].rsplit(" ", 1)[0] + "…"


def rank_indicators(
    indicators: Sequence[Indicator], query: str, limit: int
) -> list[Indicator]:
    """The ``limit`` best matches: exact series_id, series_id prefix, then query
    words in the measured quantity (3), unit (2) or definition (1). Ties go to
    headline series, then shorter names."""
    raw = " ".join(query.lower().split())
    words = _word_set(raw)
    scored: list[tuple[int, Indicator]] = []
    for ind in indicators:
        sid = ind.series_id.lower()
        score = 1000 if sid == raw else 100 if "." in raw and sid.startswith(raw) else 0
        subject, unit, desc = ind.words
        for word in words:
            score += 3 if word in subject else 2 if word in unit else int(word in desc)
        if score:
            scored.append((score, ind))
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].series_id not in HEADLINE_SERIES,
            len(item[1].name),
            item[1].series_id,
        )
    )
    return [ind for _, ind in scored[:limit]]


@dataclass
class _IndicatorCache:
    by_id: dict[str, Indicator] = field(default_factory=dict)  # lower-case ids
    loaded_at: float | None = None
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    def fresh(self) -> bool:
        return self.loaded_at is not None and (
            _clock() - self.loaded_at < METADATA_TTL_SECONDS
        )


# One cache per API client, so separate servers (and tests) never share state.
_CACHES: weakref.WeakKeyDictionary[NasdaqDataLinkClient, _IndicatorCache] = (
    weakref.WeakKeyDictionary()
)


def _cache_for(ctx: Context) -> _IndicatorCache:
    return _CACHES.setdefault(app_state(ctx).client, _IndicatorCache())


async def load_indicators(ctx: Context) -> list[Indicator]:
    """All WB/METADATA rows, downloaded once and kept for 24 hours."""
    cache = _cache_for(ctx)
    async with cache.lock:
        if not cache.fresh():
            read = await read_table(
                ctx,
                METADATA_TABLE,
                columns=("series_id", "name", "description"),
                max_pages=MAX_PAGES,
                use_cache=False,
                validate=False,
            )
            by_id = {
                str(r["series_id"]).lower(): Indicator.build(
                    str(r["series_id"]),
                    str(r.get("name") or r["series_id"]),
                    str(r.get("description") or ""),
                )
                for r in read.records()
                if r.get("series_id")
            }
            if not by_id:  # never cache an empty list for a day
                raise UpstreamError(
                    "Nasdaq returned no WB/METADATA rows; retry shortly."
                )
            cache.by_id, cache.loaded_at = by_id, _clock()
        return list(cache.by_id.values())


def _unknown_series(value: str, indicators: Sequence[Indicator]) -> str:
    needle = value.lower()
    hits = sorted(
        (
            i
            for i in indicators
            if needle in i.series_id.lower() or needle in i.name.lower()
        ),
        key=lambda i: (len(i.name), i.series_id),
    )
    found = "; ".join(f"{i.series_id} ({i.name})" for i in hits[:5])
    return f"{value!r} is not a WB/METADATA series_id" + (
        f"; series containing it: {found}." if found else "."
    )


async def resolve_indicators(ctx: Context, values: Sequence[str]) -> list[IndicatorRef]:
    """The WB/METADATA series named by ``values`` (series_ids in any case)."""
    cache = _cache_for(ctx)
    ids = [v for v in values if _SERIES_ID_RE.match(v)]
    known: dict[str, tuple[str, str]] = {}
    if cache.fresh():
        hits = [cache.by_id[i.lower()] for i in ids if i.lower() in cache.by_id]
        known = {i.series_id.lower(): (i.series_id, i.name) for i in hits}
    elif ids:
        read = await read_table(
            ctx,
            METADATA_TABLE,
            filters={"series_id": ids},
            columns=("series_id", "name"),
            page_size=100,
            validate=False,
        )
        for r in read.records():
            if r.get("series_id"):
                sid = str(r["series_id"])
                known[sid.lower()] = (sid, str(r.get("name") or sid))
    unknown = [v for v in values if v.lower() not in known]
    if unknown:
        indicators = await load_indicators(ctx)
        raise InvalidRequestError(
            " ".join(_unknown_series(v, indicators) for v in unknown)
            + f" Indicators are series_ids such as NY.GDP.MKTP.CD; {SEARCH_TOOL} "
            "finds them by keyword."
        )
    refs: dict[str, IndicatorRef] = {}
    for value in values:
        sid, name = known[value.lower()]
        refs.setdefault(sid, IndicatorRef(series_id=sid, name=name))
    return list(refs.values())


# ------------------------------------------------------------------- models


class IndicatorMatch(BaseModel):
    series_id: str = Field(description="Value for ndl_get_world_bank_data.")
    name: str
    description: str | None = Field(
        default=None, description="First sentence of the World Bank definition."
    )


class IndicatorSearchResult(BaseModel):
    """World Bank indicators matching a query, best first."""

    query: str
    results: list[IndicatorMatch]
    result_count: int
    indicators_searched: int = Field(description="Indicators in WB/METADATA.")
    table: str = METADATA_TABLE
    notes: list[str] = Field(default_factory=list)


class IndicatorRef(BaseModel):
    series_id: str
    name: str


class CountryRef(BaseModel):
    given: str = Field(description="Country as passed in `countries`.")
    code: str = Field(description="World Bank code sent to WB/DATA.")
    name: str


class SeriesCoverage(BaseModel):
    series_id: str
    country_code: str
    first_year: int
    last_year: int
    years: int = Field(description="Number of years with a value.")


class WorldBankData(TableResult):
    """World Bank indicator values: one row per indicator, country and year."""

    indicators: list[IndicatorRef] = Field(
        default_factory=list, description="Requested series and their names."
    )
    countries: list[CountryRef] = Field(
        default_factory=list, description="How each requested country was resolved."
    )
    coverage: list[SeriesCoverage] = Field(
        default_factory=list,
        description="Years with data per indicator and country, before the year "
        "filter and `limit`.",
    )


# -------------------------------------------------------------------- tools


async def ndl_search_world_bank_indicators(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="Keywords or a series_id, e.g. 'GDP', 'CO2 emissions per "
            "capita', 'NY.GDP.MKTP.CD' or an id prefix like 'SI.POV'.",
        ),
    ],
    limit: Annotated[
        int, Field(ge=1, le=50, description="Maximum indicators to return.")
    ] = 10,
) -> Annotated[CallToolResult, IndicatorSearchResult]:
    """Find World Bank indicator series_ids by keyword (GDP, inflation, literacy, CO2).

    Ranks the 1,484 World Development Indicators in WB/METADATA (free for any API
    key) by keyword matches in the name first and the definition second; an exact
    series_id comes first. The list is downloaded once and reused for 24 hours.
    The series_id values are the input of ndl_get_world_bank_data.
    """
    indicators = await load_indicators(ctx)
    matches = rank_indicators(indicators, query, limit)
    notes = []
    if not matches:
        notes.append(
            "No indicator name or definition contains these words. Broader terms "
            "such as 'GDP', 'population' or 'unemployment' match more series."
        )
    return to_tool_result(
        IndicatorSearchResult(
            query=query,
            results=[
                IndicatorMatch(
                    series_id=m.series_id, name=m.name, description=m.snippet()
                )
                for m in matches
            ],
            result_count=len(matches),
            indicators_searched=len(indicators),
            notes=notes,
        )
    )


IndicatorsArg = Annotated[
    str | list[str],
    Field(
        description=f"Up to {MAX_INDICATORS} series_ids such as 'NY.GDP.MKTP.CD' "
        "(a list or a comma-separated string).",
    ),
]
CountriesArg = Annotated[
    str | list[str],
    Field(
        description=f"Up to {MAX_COUNTRIES} ISO3/ISO2 codes, World Bank aggregate "
        "codes or exact World Bank names ('ITA', 'KR', 'WLD', 'Euro area').",
    ),
]


async def ndl_get_world_bank_data(
    ctx: Context,
    indicators: IndicatorsArg,
    countries: CountriesArg,
    start_date: StartYearOrDateArg = None,
    end_date: EndYearOrDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, WorldBankData]:
    """Get yearly World Bank indicator values for countries and aggregates (WB/DATA).

    World Development Indicators, free for any API key: 1960-2023 for 217
    economies and 48 aggregates (World, regions, income groups, EU, Euro area);
    some series (poverty, debt) end earlier. Nasdaq refreshed the table in August
    2025. IMF projections past 2023: ndl_get_imf_weo_data.

    Indicators are series_ids (ndl_search_world_bank_indicators finds them by
    keyword). Dates filter by year. Rows run newest year first, then in the order
    given, so `limit` keeps the latest years; `coverage` gives the years with
    data per pair.
    """
    state = app_state(ctx)
    lo, hi = period_bounds(start_date, end_date)
    first = int(lo[:4]) if lo else None
    last = int(hi[:4]) if hi else None
    index = country_index()
    series_values = as_list(indicators, upper=False)
    country_values = index.values(countries)
    for kind, given, cap in (
        ("indicators", series_values, MAX_INDICATORS),
        ("countries", country_values, MAX_COUNTRIES),
    ):
        if not given:
            raise InvalidRequestError(f"`{kind}` is empty.")
        if len(given) > cap:
            raise InvalidRequestError(
                f"{len(given)} {kind} requested; the maximum is {cap} per call."
            )
    resolved: dict[str, CountryRef] = {}
    for value in country_values:
        economy = index.resolve(value)
        resolved.setdefault(
            economy.code, CountryRef(given=value, code=economy.code, name=economy.name)
        )
    series = await resolve_indicators(ctx, series_values)
    read = await read_table(
        ctx,
        DATA_TABLE,
        filters={
            "series_id": [s.series_id for s in series],
            "country_code": list(resolved),
        },
        columns=DATA_COLUMNS,
        page_size=MAX_PAGE_SIZE,
        max_pages=MAX_PAGES,
    )
    raw_rows: list[list[Any]] = [
        [r.get(c) for c in DATA_COLUMNS] for r in read.records()
    ]

    def pair(sid: Any, code: Any) -> tuple[str, str]:
        return str(sid).lower(), str(code).upper()

    # (series, country) pairs in the order requested, and the years with data.
    pairs = {pair(s.series_id, c): (s.series_id, c) for s in series for c in resolved}
    order = {key: i for i, key in enumerate(pairs)}
    spans: dict[tuple[str, str], list[int]] = {}
    for sid, code, _name, year, value in raw_rows:
        if isinstance(year, int) and value is not None:
            span = spans.setdefault(pair(sid, code), [year, year, 0])
            span[:] = [min(span[0], year), max(span[1], year), span[2] + 1]
    lo_year, hi_year = first or 0, last or 9999
    rows = [r for r in raw_rows if isinstance(r[3], int) and lo_year <= r[3] <= hi_year]
    rows.sort(key=lambda r: (-r[3], order.get(pair(r[0], r[1]), len(order))))

    notes: list[str] = []
    if first or last:
        if first and last:
            span_text = f"{first}-{last}"
        else:
            span_text = f"{first} or later" if first else f"{last} or earlier"
        notes.append(
            f"WB/DATA cannot be filtered by year: {len(raw_rows)} rows were read "
            f"and {len(rows)} fall in {span_text}."
        )
    latest = max((s[1] for s in spans.values()), default=None)
    wanted_until = max(first or 0, last or 0)
    if latest and wanted_until > latest:
        notes.append(f"The latest year with data for this request is {latest}.")
    if wanted_until > LAST_YEAR and "macro" in state.toolsets:
        notes.append(
            f"IMF estimates and projections past {LAST_YEAR}: ndl_get_imf_weo_data."
        )
    missing = [
        f"{sid} for {code}" for k, (sid, code) in pairs.items() if k not in spans
    ]
    if missing:
        more = f" and {len(missing) - 10} more" if len(missing) > 10 else ""
        notes.append(f"No values in WB/DATA for {', '.join(missing[:10])}{more}.")

    request = {k: v for k, v in read.request.items() if k != "columns"}
    request["sort"] = SORT_ORDER
    request |= {
        k: v for k, v in (("start_date", start_date), ("end_date", end_date)) if v
    }
    types = {c.name: c.type for c in read.columns}
    base = build_result(
        ctx,
        read,
        rows,
        limit=limit,
        columns=[ColumnInfo(name=c, type=types.get(c)) for c in DATA_COLUMNS],
        notes=notes,
        request=request,
    )
    result = WorldBankData(
        **dict(base),
        indicators=series,
        countries=list(resolved.values()),
        coverage=[
            SeriesCoverage(
                series_id=sid,
                country_code=code,
                first_year=spans[k][0],
                last_year=spans[k][1],
                years=spans[k][2],
            )
            for k, (sid, code) in pairs.items()
            if k in spans
        ],
    )
    # build_result fitted the rows alone; refit with the coverage lists included.
    return to_tool_result(fit_rows(result, state.settings.max_response_bytes))


# ------------------------------------------------------------------- prompt


def country_economic_profile(
    country: Annotated[
        str,
        Field(
            description="Country or aggregate: ISO3 or ISO2 code or World Bank name, "
            "e.g. 'ITA', 'BR' or 'Euro area'."
        ),
    ],
) -> str:
    """Economic profile of a country from World Bank indicators, set against World."""
    try:
        economy = country_index().resolve(country)
    except InvalidRequestError as error:
        # MCPError reaches the user; the SDK hides other exceptions' messages.
        raise MCPError(code=INVALID_PARAMS, message=str(error)) from error
    codes = [economy.code] if economy.code == "WLD" else [economy.code, "WLD"]
    return (
        f"Write a short economic profile of {economy.name} ({economy.code}) from "
        "World Bank data.\n\n"
        f"1. Call ndl_get_world_bank_data with countries={codes}, "
        f"indicators={list(PROFILE_SERIES)}, start_date='2014' and limit=300.\n"
        "2. For each indicator give the latest value with its year, the direction "
        "over the decade, and the World figure for the same year where present.\n"
        "3. Cover growth, prices, labour market, external position, public debt "
        "and demographics in a few sentences each.\n"
        f"WB/DATA ends in {LAST_YEAR} and some series stop earlier, so state the "
        "year next to every figure and say when an indicator has no data. Other "
        f"topics (poverty, education, energy) can be found with {SEARCH_TOOL}."
    )


TOOLSET = Toolset(
    name="world_bank",
    description="World Bank World Development Indicators (WB/DATA, WB/METADATA), free.",
    tools=(
        ToolSpec(
            ndl_search_world_bank_indicators,
            "Search World Bank indicators",
            tables=(METADATA_TABLE,),
        ),
        ToolSpec(
            ndl_get_world_bank_data,
            "Get World Bank indicator data",
            tables=(DATA_TABLE, METADATA_TABLE),
        ),
    ),
    prompts=(PromptSpec(country_economic_profile, "Country economic profile"),),
    hints=("Country statistics: ndl_get_world_bank_data (actuals to 2023).",),
)
