"""Commodities: CFTC Commitments of Traders, JODI energy, OPEC, LME stocks, WASDE.

All tables here are free with an API key, and most are no longer updated by Nasdaq:
the CFTC tables end in June 2026, JODI in December 2024, LME in July 2024, WASDE
with the February 2024 report and OPEC in January 2024. Tools return the newest
rows first; the shared result builder adds a note when a table is stale.

Inputs are codes or exact names; anything else fails with substring candidates.
Bundled: ``data/commodities_cot_contracts.json`` (CFTC contract list, public
domain) and ``data/commodities_codes.json`` (JODI and LME codes, our own labels).
WASDE table codes are read live from WASDE/METADATA.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from importlib import resources
from itertools import product as cartesian
from typing import Annotated, Any, Literal, TypeVar

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
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
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    fetch_table,
    read_table,
)

COT_TABLES: dict[str, str] = {
    "disaggregated": "QDL/FON",
    "legacy": "QDL/LFON",
    "concentration": "QDL/FCR",
    "index_traders": "QDL/CITS",
}
JODI_TABLE = "QDL/JODI"
OPEC_TABLE = "QDL/OPEC"
LME_TABLE = "QDL/LME"
WASDE_DATA = "WASDE/DATA"
WASDE_METADATA = "WASDE/METADATA"
COT_FILE = "commodities_cot_contracts.json"
CODES_FILE = "commodities_codes.json"

COT_CODE_RE = re.compile(r"^\d{3}[0-9A-Z+]{3}$")
WASDE_CODE_RE = re.compile(r"^[A-Z][A-Z_]*_\d{2}$")
ISO3_RE = re.compile(r"^[A-Z]{3}$")
_WORD_RE = re.compile(r"[a-z0-9&+]+")
# WASDE footnote marks, standing alone: 'World  3/', 'Per Capita 2/ 3/', 'Loss /2'.
_FOOTNOTE_RE = re.compile(r"(?<!\S)(?:\d{1,2}/|/\d{1,2})(?!\S)")
# WASDE labels quoted in an error: plain text of modest length.
_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .,&()'/$%+-]{0,79}$")

# Wide snapshots are fetched for one date only: one item x location of LME data
# spans ~2,400 rows and one JODI code x country ~280 rows, so beyond these many
# series the newest rows would not fit in one 10,000-row scan.
LME_MAX_SERIES = 4
JODI_MAX_SERIES = 30
WASDE_MAX_TABLES = 3

M = TypeVar("M", bound=TableResult)


# ------------------------------------------------------------- shared helpers


@lru_cache(maxsize=2)
def _load(name: str) -> dict[str, Any]:
    text = (
        resources.files("nasdaq_data_link_mcp_os")
        .joinpath(f"data/{name}")
        .read_text(encoding="utf-8")
    )
    data: dict[str, Any] = json.loads(text)
    return data


def _key(text: Any) -> str:
    """Name comparison key: 'World  3/' -> 'world', 'U.S.' -> 'us', 'WTI-PHYSICAL'
    -> 'wti physical'. Lower case, words only, no WASDE footnote marks or dots."""
    text = _FOOTNOTE_RE.sub(" ", str(text or "")).replace(".", "")
    return " ".join(_WORD_RE.findall(text.lower()))


def _clean(text: Any) -> str:
    """A WASDE label without footnote marks or repeated spaces."""
    return " ".join(_FOOTNOTE_RE.sub(" ", str(text or "")).split())


def _unknown(
    what: str, value: str, options: Mapping[str, str], fallback: str
) -> InvalidRequestError:
    """Error naming up to 5 ``options`` (display label -> searched text) whose text
    contains ``value`` (case-insensitive), or ``fallback`` when none does."""
    needle = " ".join(value.split()).casefold()
    hits = [k for k, text in options.items() if needle and needle in text.casefold()]
    more = f" and {len(hits) - 5} more" if len(hits) > 5 else ""
    found = f"Candidates: {'; '.join(hits[:5])}{more}." if hits else fallback
    return InvalidRequestError(f"No {what} matches {value!r}. {found}")


def _compact(value: Any) -> Any:
    """Write whole-number floats as ints (contracts, tonnes) to save tokens."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def _number(value: Any) -> Any:
    """Parse a numeric text cell; markers such as 'x' and None become None."""
    try:
        return _compact(float(str(value).strip().replace(",", "")))
    except ValueError:
        return None


def _difference(a: Any, b: Any) -> Any:
    if not isinstance(a, int | float) or not isinstance(b, int | float):
        return None
    return _compact(round(float(a) - float(b), 6))


def _cell(row: Sequence[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _column(result: TableResult, name: str) -> list[Any]:
    """Values of one column in ``result.rows`` (empty if the column is absent)."""
    names = [c.name for c in result.columns]
    if name not in names:
        return []
    at = names.index(name)
    return [_cell(row, at) for row in result.rows]


def _reshape(
    result: TableResult,
    *,
    drop: Sequence[str] = (),
    rename: Mapping[str, str] | None = None,
    convert: Mapping[str, Callable[[Any], Any]] | None = None,
    nets: bool = False,
) -> TableResult:
    """Drop, rename and convert columns; with ``nets``, append ``X_net`` = ``X_longs``
    - ``X_shorts`` for every such pair (bar total_reportable, the mirror of
    non_reportable). Converted columns become ``double``; whole-number floats are
    written as ints."""
    names = [c.name for c in result.columns]
    keep = [i for i, name in enumerate(names) if name not in drop]
    rename = rename or {}
    convert = convert or {}
    columns = [
        ColumnInfo(
            name=rename.get(names[i], names[i]),
            type="double" if names[i] in convert else result.columns[i].type,
        )
        for i in keep
    ]
    out = [c.name for c in columns]
    pairs = [
        (f"{name[:-6]}_net", i, out.index(f"{name[:-6]}_shorts"))
        for i, name in enumerate(out)
        if nets
        and name.endswith("_longs")
        and f"{name[:-6]}_shorts" in out
        and name != "total_reportable_longs"
    ]
    columns += [ColumnInfo(name=new, type="double") for new, _, _ in pairs]
    rows: list[list[Any]] = []
    for row in result.rows:
        values = []
        for i in keep:
            fn = convert.get(names[i])
            values.append(_compact(fn(_cell(row, i)) if fn else _cell(row, i)))
        values += [_difference(values[a], values[b]) for _, a, b in pairs]
        rows.append(values)
    return result.model_copy(update={"columns": columns, "rows": rows})


def _finish(
    ctx: Context, model: type[M], result: TableResult, **extra: Any
) -> CallToolResult:
    """Build the typed result and re-apply the response size budget."""
    built = model.model_validate({**result.model_dump(), **extra})
    fitted = fit_rows(built, app_state(ctx).settings.max_response_bytes)
    return to_tool_result(fitted)


async def _newest(
    ctx: Context, table: str, filters: Mapping[str, Any], *, column: str = "date"
) -> str | None:
    """Newest ``column`` value of rows matching fixed ``filters`` (one page)."""
    probe = await fetch_table(
        ctx,
        table,
        filters=filters,
        columns=[column],
        limit=1,
        sort_by=column,
        descending=True,
        validate=False,
    )
    value = probe.rows[0][0] if probe.rows and probe.rows[0] else None
    return None if value is None else str(value)


async def _latest_only(
    ctx: Context, table: str, filters: dict[str, Any], key: str, series: Sequence[str]
) -> list[str]:
    """Restrict a wide request without dates to its newest date, in place.

    The date is the newest of the first of up to 3 series that has rows: not
    every series exists everywhere (no primary aluminium is stored in Dubai).
    Returns the note to add.
    """
    scope = {k: v for k, v in filters.items() if k != key}
    for candidate in series[:3]:
        latest = await _newest(ctx, table, {**scope, key: candidate})
        if latest:
            filters["date"] = latest
            return [
                "Many series requested without dates: showing the latest date only. "
                "start_date gives a history; fewer series narrow the request."
            ]
    return []


# ======================================================================= COT

CotReport = Literal["disaggregated", "legacy", "concentration", "index_traders"]
CotMeasure = Literal[
    "positions", "changes", "percent_of_open_interest", "trader_counts"
]
CotCrop = Literal["all", "old", "other"]

_CROP = {"all": "ALL", "old": "OLD", "other": "OTR"}
_COT_NOTES = {
    "positions": "Values are numbers of contracts; market_participation is total "
    "open interest.",
    "changes": "Values are week-over-week changes in contracts; "
    "market_participation is the change in open interest.",
    "percent_of_open_interest": "Values are percentages of open interest; "
    "market_participation is 100.",
    "trader_counts": "Values are numbers of reportable traders; market_participation "
    "is the total number of reportable traders. Non-reportable traders are not "
    "counted (null).",
    "concentration": "Values are percentages of open interest held by the 4 and 8 "
    "largest traders; gross counts all positions, net nets each trader's longs "
    "against shorts.",
    "index_traders": "Futures and options combined. index_trader_* are commodity "
    "index traders (source columns longs/shorts); commercial and non-commercial "
    "figures exclude them.",
}


class CotContract(BaseModel):
    code: str = Field(description="CFTC contract market code.")
    market: str | None = None
    exchange: str | None = None
    commodity: str | None = None
    reports: list[str] | None = Field(
        default=None, description="Reports holding this contract (as of the list)."
    )


class CotResult(TableResult):
    """Weekly CFTC Commitments of Traders rows for one contract, newest first."""

    contract: CotContract
    report: str = Field(description="disaggregated, legacy, concentration, ...")
    type_code: str = Field(description="Value of the table's `type` column read.")


@lru_cache(maxsize=1)
def _contracts() -> dict[str, CotContract]:
    """Bundled CFTC contracts by code."""
    return {
        item["code"]: CotContract.model_validate(item)
        for item in _load(COT_FILE)["contracts"]
    }


@lru_cache(maxsize=1)
def _contracts_by_market() -> dict[str, CotContract]:
    return {_key(c.market): c for c in _contracts().values()}


def _resolve_contract(query: str) -> CotContract:
    """A contract by code (listed or not) or by exact CFTC market name."""
    code = query.strip().upper()
    if COT_CODE_RE.match(code):
        return _contracts().get(code) or CotContract(code=code)
    found = _contracts_by_market().get(_key(query))
    if found is not None:
        return found
    raise _unknown(
        "CFTC contract",
        query,
        {
            f"{c.market} ({c.code})": f"{c.code} {c.market} {c.commodity}"
            for c in _contracts().values()
        },
        "Pass a 6-character CFTC contract market code or an exact CFTC market "
        "name, e.g. GOLD (088691), WTI-PHYSICAL (067651), E-MINI S&P 500 "
        "(13874A), UST 10Y NOTE (043602).",
    )


def _cot_type_code(report: str, measure: str, include_options: bool, crop: str) -> str:
    """The `type` value of the QDL COT tables: F_ALL, FO_L_OLD_OI, CITS_CHG, ..."""
    if report == "concentration" and measure != "positions":
        raise InvalidRequestError(
            "report='concentration' only has measure='positions' (shares of open "
            "interest held by the largest 4 and 8 traders)."
        )
    if crop != "all" and (measure == "changes" or report == "index_traders"):
        raise InvalidRequestError(
            "Week-over-week changes and the index-trader report have no old/other "
            "crop split; use crop='all'."
        )
    if report == "index_traders":
        prefix = "CITS"  # futures and options combined
    else:
        legacy = "" if report == "disaggregated" else "_L"
        prefix = ("FO" if include_options else "F") + legacy
    if measure == "changes":
        return f"{prefix}_CHG"
    if report == "concentration":
        return f"{prefix}_{_CROP[crop]}_CR"
    suffix = {"percent_of_open_interest": "_OI", "trader_counts": "_NT"}.get(
        measure, ""
    )
    return f"{prefix}_{_CROP[crop]}{suffix}"


def _cot_notes(report: str, measure: str, crop: str) -> list[str]:
    if report == "concentration":
        return [_COT_NOTES[report]]
    notes = [_COT_NOTES[measure]]
    if measure != "trader_counts":
        notes.append("*_net columns are longs minus shorts, added by this server.")
    if report == "index_traders":
        notes.append(_COT_NOTES[report])
    if crop != "all":
        notes.append(
            "Old/other crop splits only differ for contracts with crop years; others "
            "show everything as old crop."
        )
    return notes


async def ndl_get_cot_report(
    ctx: Context,
    contract: Annotated[
        str,
        Field(
            description="6-character CFTC contract code or exact CFTC market name, "
            "e.g. '088691' or 'GOLD'."
        ),
    ],
    report: Annotated[
        CotReport | None,
        Field(
            description="Default: disaggregated (physical commodities) if available, "
            "else legacy (all contracts). concentration: top 4/8 traders; "
            "index_traders: 13 farm markets."
        ),
    ] = None,
    measure: Annotated[
        CotMeasure, Field(description="changes = week over week.")
    ] = "positions",
    include_options: Annotated[
        bool, Field(description="Futures and options combined.")
    ] = False,
    crop: Annotated[
        CotCrop, Field(description="Crop-year split (farm markets).")
    ] = "all",
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: Annotated[
        int, Field(ge=1, le=1000, description="Maximum weekly rows.")
    ] = 52,
) -> Annotated[CallToolResult, CotResult]:
    """Weekly CFTC Commitments of Traders positions for one futures market.

    Reads QDL/FON, QDL/LFON, QDL/FCR or QDL/CITS (per `report`): Tuesday as-of
    dates, newest first, with longs-minus-shorts `*_net` columns. Free with an
    API key; ends with the 2026-06-09 report.
    """
    entry = _resolve_contract(contract)
    listed = entry.reports is not None
    reports = entry.reports or []
    if report is None:
        report = "disaggregated" if "disaggregated" in reports else "legacy"
    if listed and report not in reports:
        raise InvalidRequestError(
            f"{entry.market} ({entry.code}) has no {report} report, only "
            f"{', '.join(reports)}. The disaggregated report covers physical "
            "commodities (financial futures are in legacy); index_traders covers 13 "
            "agricultural contracts."
        )
    type_code = _cot_type_code(report, measure, include_options, crop)
    notes = _cot_notes(report, measure, crop)
    if not listed:
        notes.insert(
            0,
            f"Contract code {entry.code} is not in the bundled CFTC list (contracts "
            f"active on {_load(COT_FILE)['as_of']}); its market name is unknown.",
        )
    result = await fetch_table(
        ctx,
        COT_TABLES[report],
        filters={
            "contract_code": entry.code,
            "type": type_code,
            **date_range("date", start_date, end_date),
        },
        limit=limit,
        sort_by="date",
        descending=True,
        notes=notes,
    )
    result = _reshape(
        result,
        drop=("contract_code", "type"),
        rename={"longs": "index_trader_longs", "shorts": "index_trader_shorts"},
        nets=measure != "trader_counts",
    )
    if not result.rows:
        result.notes.append(
            f"No {report} rows for {entry.code} with type {type_code} in this window."
        )
    return _finish(
        ctx, CotResult, result, contract=entry, report=report, type_code=type_code
    )


def cot_positioning_review(
    contract: Annotated[
        str,
        Field(description="CFTC code or exact market name, e.g. '067651' or 'GOLD'."),
    ],
) -> str:
    """Review speculative positioning in one futures market from CFTC COT data."""
    return (
        f"Review trader positioning in {contract} futures using ndl_get_cot_report. "
        "First read one year of weekly positions with the default report, then the "
        "same window with measure='percent_of_open_interest'. Report the latest net "
        "position of money managers (or non-commercials in the legacy report), its "
        "change over 4 and 13 weeks, where it sits within the one-year range, and "
        "the open-interest trend. Give the as-of date of the newest row and mention "
        "that Nasdaq's CFTC tables end in June 2026."
    )


# ====================================================================== JODI

JodiUnit = Literal["kbd", "kb", "kt", "kl", "conversion_factor", "mcm", "tj"]

# Crude-side products (crude oil, NGL, other primary, total crude) have the
# crude-side flows, refined products the product-side ones.
_PRIMARY_PRODUCTS = frozenset({"CR", "NG", "OC", "TC"})
_PRIMARY_FLOWS = frozenset({"PR", "OS", "DU", "RI"})
_SECONDARY_FLOWS = frozenset({"RO", "RE", "IT", "DE"})


class JodiResult(TableResult):
    """Monthly JODI oil and gas statistics, newest first."""

    countries: list[str] = Field(description="ISO 3166 alpha-3 codes read.")
    codes: dict[str, str] = Field(
        default_factory=dict,
        description="Meaning of each JODI code in `rows`: product | flow | unit. "
        "Units: kbd thousand barrels/day, kb thousand barrels, kt thousand tonnes, "
        "kl thousand kilolitres, mcm million cubic metres, tj terajoules.",
    )


def _jodi(part: str) -> dict[str, str]:
    """Our names for one kind of JODI code part (products, oil_flows, ...) by code.

    Oil code = product + flow + unit (CRPRKD); gas code = unit + flow (GCPR).
    """
    names: dict[str, str] = _load(CODES_FILE)["jodi"][part]
    return names


def _jodi_code_of(part: str, name: str | None) -> list[str]:
    """Codes of ``part`` called ``name``; every code for None."""
    return [code for code, n in _jodi(part).items() if name in (None, n)]


def _jodi_label(code: str) -> str:
    """'CRPRKD' -> 'crude_oil | production | kbd'; '' if no such series exists."""
    if len(code) == 4:
        gas = [_jodi("gas_flows").get(code[2:]), _jodi("gas_units").get(code[:2])]
        names = ["natural_gas", *gas]
    elif len(code) == 6 and code[2:4] not in (
        _SECONDARY_FLOWS if code[:2] in _PRIMARY_PRODUCTS else _PRIMARY_FLOWS
    ):
        names = [
            _jodi("products").get(code[:2]),
            _jodi("oil_flows").get(code[2:4]),
            _jodi("oil_units").get(code[4:]),
        ]
    else:
        return ""
    found = [n for n in names if n]
    return " | ".join(found) if len(found) == len(names) else ""


def _choice(value: str | None) -> str | None:
    """'Closing stocks' -> 'closing_stocks'; empty -> None."""
    return _key(value).replace(" ", "_") or None


def _jodi_codes(product: str | None, flow: str | None, unit: str | None) -> list[str]:
    """JODI codes for product x flow x unit; None means every value.

    ``product`` also takes 'oil' (every oil product) and 'natural_gas'.
    """
    products = _jodi("products")
    if product not in (None, "oil", "natural_gas", *products.values()):
        raise InvalidRequestError(
            f"Unknown JODI product {product!r}. Products: "
            f"{', '.join(products.values())}, oil (all of them) and natural_gas."
        )
    oil_flows, gas_flows = _jodi("oil_flows").values(), _jodi("gas_flows").values()
    if flow not in (None, *oil_flows, *gas_flows):
        raise InvalidRequestError(
            f"Unknown JODI flow {flow!r}. Oil flows: {', '.join(oil_flows)}. Gas "
            f"flows: {', '.join(gas_flows)}."
        )
    codes: list[str] = []
    if product != "natural_gas" and unit not in ("mcm", "tj"):
        wanted = None if product == "oil" else product
        for p, f in cartesian(
            _jodi_code_of("products", wanted), _jodi_code_of("oil_flows", flow)
        ):
            # Stock levels and changes have no per-day figure (JODI writes 'x').
            default = "kb" if f in ("CS", "SC") else "kbd"
            code = p + f + _jodi_code_of("oil_units", unit or default)[0]
            if _jodi_label(code):
                codes.append(code)
    if product in (None, "natural_gas") and unit in (None, "mcm", "tj"):
        prefix = _jodi_code_of("gas_units", unit or "mcm")[0]
        codes.extend(prefix + f for f in _jodi_code_of("gas_flows", flow))
    if not codes:
        raise InvalidRequestError(
            f"No JODI series for product={product!r}, flow={flow!r}, unit={unit!r}. "
            "mcm and tj are gas units. Oil flows production, from_other_sources, "
            "direct_use and refinery_intake exist for crude_oil, ngl, other_primary "
            "and total_crude only; refinery_output, receipts, interproduct_transfers "
            "and demand for refined products only."
        )
    return codes


def _jodi_raw_codes(codes: str | list[str]) -> list[str]:
    wanted = as_list(codes)
    unknown = [c for c in wanted if not _jodi_label(c)]
    if unknown or not wanted:
        raise InvalidRequestError(
            f"Unknown JODI code(s): {', '.join(unknown) or '(none given)'}. Oil "
            "codes are product + flow + unit (CRPRKD = crude oil production in "
            "kb/d); gas codes are GC (mcm) or GT (TJ) + flow (GCDO = gas demand). "
            "Or use product/flow/unit."
        )
    return wanted


def _countries(countries: str | list[str]) -> list[str]:
    codes = as_list(countries)
    bad = [c for c in codes if not ISO3_RE.match(c)]
    if bad or not codes:
        raise InvalidRequestError(
            "`countries` takes ISO 3166 alpha-3 codes such as USA, SAU, RUS, CHN; "
            f"got {', '.join(repr(c) for c in bad) or 'none'}."
        )
    return codes


async def ndl_get_jodi_energy_data(
    ctx: Context,
    countries: Annotated[
        str | list[str],
        Field(description="ISO 3166 alpha-3 codes: 'USA' or ['SAU', 'RUS']."),
    ],
    product: Annotated[
        str | None,
        Field(
            description="crude_oil, gasoline, gas_diesel, jet_fuel, natural_gas, "
            "oil (all oil products), ... Default: all."
        ),
    ] = None,
    flow: Annotated[
        str | None,
        Field(
            description="production, demand, imports, exports, closing_stocks, ... "
            "Default: all."
        ),
    ] = None,
    unit: Annotated[
        JodiUnit | None, Field(description="Default kbd (oil stocks: kb), gas mcm.")
    ] = None,
    codes: Annotated[
        str | list[str] | None,
        Field(description="Raw JODI codes, e.g. 'CRPRKD' (crude production, kb/d)."),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum rows.")] = 100,
) -> Annotated[CallToolResult, JodiResult]:
    """Monthly oil and gas production, demand, trade and stocks by country (JODI).

    Reads QDL/JODI: ~100 countries, monthly from 2002, newest first. Over 30
    series without dates return the latest month only. Free with an API key;
    Nasdaq's copy ends at 2024-12.
    """
    iso3 = _countries(countries)
    if codes is not None:
        series = _jodi_raw_codes(codes)
    else:
        series = _jodi_codes(_choice(product), _choice(flow), unit)
    filters: dict[str, Any] = {
        "country": iso3,
        "code": series,
        **date_range("date", start_date, end_date),
    }
    notes = [
        "assessment is JODI's data-quality flag: 1 reasonable comparability, "
        "2 use with caution, 3 not assessed."
    ]
    if not (start_date or end_date) and len(series) * len(iso3) > JODI_MAX_SERIES:
        notes += await _latest_only(ctx, JODI_TABLE, filters, "code", series)
    result = await fetch_table(
        ctx,
        JODI_TABLE,
        filters=filters,
        columns=["date", "country", "code", "value", "notes"],
        limit=limit,
        sort_by=[("date", True), "country", "code"],
        notes=notes,
    )
    missing = sum(
        1 for v in _column(result, "value") if v is not None and _number(v) is None
    )
    result = _reshape(
        result,
        drop=("country",) if len(iso3) == 1 else (),
        rename={"notes": "assessment"},
        convert={"value": _number},
    )
    if missing:
        result.notes.append(
            f"{missing} value(s) were not numeric in the source ('x' marks a figure "
            "that does not apply, e.g. stocks in kb/d) and are null."
        )
    if not result.rows:
        result.notes.append(
            "No JODI rows matched. Check the country codes and dates; some "
            "countries report oil only or stopped reporting gas."
        )
    labels = {c: _jodi_label(c) for c in series if c in set(_column(result, "code"))}
    return _finish(ctx, JodiResult, result, countries=iso3, codes=labels)


# ====================================================================== OPEC


async def ndl_get_opec_basket_price(
    ctx: Context,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """Daily OPEC Reference Basket crude oil price in US dollars per barrel.

    Reads QDL/OPEC, a single daily series from 2003-01-02, newest first. Free
    with an API key, but Nasdaq stopped updating it: the last price is from
    2024-01-25. Later crude oil data: volumes in ndl_get_jodi_energy_data (to
    2024-12) and futures positioning in ndl_get_cot_report (to 2026-06).
    """
    result = await fetch_table(
        ctx,
        OPEC_TABLE,
        filters=date_range("date", start_date, end_date),
        limit=limit,
        sort_by="date",
        descending=True,
        notes=["OPEC Reference Basket price in US dollars per barrel."],
    )
    return to_tool_result(_reshape(result, rename={"value": "price_usd_per_barrel"}))


# ======================================================================= LME

_LME_ALIASES = {"aluminium": "PA", "aluminum": "PA", "aluminum alloy": "AA"}


class LmeResult(TableResult):
    """Daily LME warehouse stock levels in metric tonnes (not prices), newest first."""

    location: str = Field(description="Location code read ('ALL' = total).")
    location_name: str | None = None
    items: dict[str, str] = Field(
        default_factory=dict, description="Meaning of each item_code in `rows`."
    )


def _lme_item_label(code: str) -> str:
    lme = _load(CODES_FILE)["lme"]
    if code in lme["items"]:
        return str(lme["items"][code])
    for parent, subs in lme["sub_items"].items():
        if code in subs:
            return f"sub-category of {lme['items'][parent]} ({parent})"
    return "sub-category (parent metal unknown)"


def _resolve_lme_items(metals: str | list[str] | None, breakdown: bool) -> list[str]:
    lme = _load(CODES_FILE)["lme"]
    items: dict[str, str] = lme["items"]
    names = {_key(label): code for code, label in items.items()} | _LME_ALIASES
    subs: dict[str, list[str]] = lme["sub_items"]
    known = {*items, *(s for codes in subs.values() for s in codes)}
    known.update(lme["unassigned_items"])
    codes = []
    for raw in as_list(metals, upper=False):
        code = names.get(_key(raw)) or raw.strip().upper()
        if code not in known:
            listing = {f"{label} ({c})": f"{c} {label}" for c, label in items.items()}
            raise _unknown(
                "LME metal",
                raw,
                listing,
                f"Metals: {'; '.join(listing)}. Sub-category codes such as NIFC "
                "are accepted too. QDL/LME holds warehouse stocks of these base "
                "metals only.",
            )
        codes.append(code)
    if not codes:  # None or an empty list: every metal
        codes = list(items)
    if breakdown:
        codes = [c for code in codes for c in [code, *subs.get(code, [])]]
    return list(dict.fromkeys(codes))


def _resolve_lme_location(location: str) -> str:
    locations: dict[str, str] = _load(CODES_FILE)["lme"]["locations"]
    raw = location.strip() or "ALL"
    if raw.upper() in locations:
        return raw.upper()
    for code, city in locations.items():
        if _key(city) == _key(raw):
            return code
    listing = {f"{city} ({code})": f"{code} {city}" for code, city in locations.items()}
    raise _unknown("LME location", raw, listing, f"Locations: {'; '.join(listing)}.")


async def ndl_get_lme_warehouse_stocks(
    ctx: Context,
    metals: Annotated[
        str | list[str] | None,
        Field(
            description="Metal names or LME codes: copper (CU), aluminium (PA), "
            "aluminium alloy (AA), NASAAC (NA), nickel (NI), lead (PB), zinc (ZI), "
            "tin (TN), cobalt (CO), or sub-codes like NIFC. Default: all nine."
        ),
    ] = None,
    location: Annotated[
        str,
        Field(
            description="Warehouse location code or city, e.g. 'NRO' or 'Rotterdam'. "
            "Default 'ALL', the sum of every location."
        ),
    ] = "ALL",
    breakdown: Annotated[
        bool,
        Field(description="Add each metal's sub-category codes, which sum to it."),
    ] = False,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, LmeResult]:
    """Daily LME warehouse stock levels in tonnes by metal and location; no prices.

    Reads QDL/LME, which holds stocks, not prices: opening and closing stock,
    tonnes delivered in and out, and open (live warrant) versus cancelled
    tonnage for 9 base metals at 32 LME locations plus their total, from
    2015-01-02. Without dates, 1-4 metals return recent history and more return
    the latest day only. Free with an API key; frozen since 2024-07 (last day
    2024-07-30).
    """
    codes = _resolve_lme_items(metals, breakdown)
    loc = _resolve_lme_location(location)
    filters: dict[str, Any] = {
        "item_code": codes,
        "country_code": loc,
        **date_range("date", start_date, end_date),
    }
    notes = [
        "Warehouse stocks in metric tonnes, not prices. closing_stock = "
        "opening_stock + delivered_in - delivered_out = open_tonnage + "
        "cancelled_tonnage (cancelled warrants are metal booked for removal).",
    ]
    if not (start_date or end_date) and len(codes) > LME_MAX_SERIES:
        notes += await _latest_only(ctx, LME_TABLE, filters, "item_code", codes)
    result = await fetch_table(
        ctx,
        LME_TABLE,
        filters=filters,
        limit=limit,
        sort_by=[("date", True), "item_code"],
        notes=notes,
    )
    result = _reshape(result, rename={"country_code": "location"})
    if not result.rows:
        result.notes.append(
            "No rows: the metal may hold no stock at this location, or the dates "
            "fall outside 2015-01-02..2024-07-30."
        )
    return _finish(
        ctx,
        LmeResult,
        result,
        location=loc,
        location_name=_load(CODES_FILE)["lme"]["locations"].get(loc),
        items={c: _lme_item_label(c) for c in codes},
    )


# ===================================================================== WASDE

_REGION_ALIASES = {
    "us": "united states",
    "usa": "united states",
    "uk": "united kingdom",
    "eu": "european union",
}


class WasdeTable(BaseModel):
    code: str
    name: str | None = None
    units: str | None = None


class WasdeResult(TableResult):
    """Rows of USDA WASDE report tables for one report month."""

    report_month: str = Field(description="WASDE report month read (YYYY-MM).")
    tables: list[WasdeTable] = Field(description="Report tables returned.")


async def _wasde_tables(ctx: Context, month: str) -> dict[str, WasdeTable]:
    """The tables of one report by code, from WASDE/METADATA.

    Only well-formed codes are kept, so odd values never reach error messages.
    """
    listing = await fetch_table(
        ctx,
        WASDE_METADATA,
        filters={"report_month": month},
        columns=["code", "name", "units"],
        limit=200,
        validate=False,
    )
    return {
        str(r[0]): WasdeTable(code=str(r[0]), name=r[1], units=r[2])
        for r in listing.rows
        if len(r) >= 3 and WASDE_CODE_RE.match(str(r[0]))
    }


def _wasde_pick(query: str, tables: Mapping[str, WasdeTable], month: str) -> list[str]:
    wanted = as_list(query)
    for code in wanted or [query]:
        if code not in tables:
            raise _unknown(
                f"table code in the {month} WASDE report",
                code,
                {
                    f"{t.code} ({_clean(t.name)})": f"{t.code} {t.name}"
                    for t in tables.values()
                },
                f"Tables: {', '.join(sorted(tables))}.",
            )
    if len(wanted) > WASDE_MAX_TABLES:
        raise InvalidRequestError(
            f"At most {WASDE_MAX_TABLES} WASDE tables per call; got {len(wanted)}."
        )
    return wanted


async def ndl_get_wasde_data(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description="WASDE table code(s) of the report, up to 3 comma-separated, "
            "e.g. 'CORN_US_12'; an unknown code returns the matching codes."
        ),
    ],
    report_month: Annotated[
        str | None,
        Field(
            description="Report month YYYY-MM, 2010-08 to 2024-02 with gaps "
            "(default: the latest).",
            pattern=r"^\d{4}-\d{2}$",
        ),
    ] = None,
    region: Annotated[
        str | None,
        Field(
            description="Region name as written in the table, e.g. 'United States' "
            "or 'World'; US, UK and EU work too."
        ),
    ] = None,
    item: Annotated[
        str | None,
        Field(
            description="Item name as written in the table, e.g. 'Ending Stocks' or "
            "'Production'."
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=1000, description="Maximum rows to return (default 1000)."),
    ] = 1000,
) -> Annotated[CallToolResult, WasdeResult]:
    """USDA World Agricultural Supply and Demand Estimates (WASDE) report tables.

    Reads tables of one report from WASDE/DATA, with their names from
    WASDE/METADATA (45 tables per report covering grains, oilseeds, cotton,
    sugar, livestock, dairy): supply and use items by region, marketing year
    and estimate month. Projection years show the prior and current month's
    estimates as separate `period` rows.

    Free with an API key. Monthly reports from 2010-08; Nasdaq stopped at the
    2024-02 report.
    """
    newest = functools.partial(_newest, ctx, WASDE_METADATA, {}, column="report_month")
    month = report_month or await newest() or ""
    tables = await _wasde_tables(ctx, month) if month else {}
    if not tables:
        raise InvalidRequestError(
            f"No WASDE report for {month or 'any month'}. Reports run from 2010-08 "
            f"to {await newest()} with some months missing."
        )
    chosen = _wasde_pick(query, tables, month)
    # One 10,000-row page holds every row of the (at most 3) tables, so the
    # local filters see all of them rather than only the first `limit`.
    read = await read_table(
        ctx, WASDE_DATA, filters={"code": chosen, "report_month": month}
    )
    rows = read.rows
    wanted = [
        (c, t) for c, t in (("region", region), ("item", item)) if t and t.strip()
    ]
    for column, text in wanted:
        at = read.column_names.index(column)
        key = _key(text)
        key = _REGION_ALIASES.get(key, key) if column == "region" else key
        kept = [row for row in rows if _key(_cell(row, at)) == key]
        if rows and not kept:
            cleaned = {_clean(_cell(row, at)) for row in rows}
            labels = sorted(filter(_LABEL_RE.match, cleaned), key=str.lower)
            raise _unknown(
                f"{column} in {', '.join(chosen)}",
                text,
                {label: label for label in labels},
                f"{column.capitalize()}s: {'; '.join(labels[:40])}.",
            )
        rows = kept
    note = "region/item are not filterable; rows were matched by exact name locally."
    result = build_result(ctx, read, rows, limit=limit, notes=[note] if wanted else [])
    drop = ["report_month"]
    if len(chosen) == 1:
        drop.append("code")
    drop.extend(
        column
        for column in ("min_value", "max_value")
        if all(v is None for v in _column(result, column))
    )
    result = _reshape(result, drop=drop)
    if not result.rows:
        result.notes.append(f"No rows for these tables in the {month} report.")
    return _finish(
        ctx,
        WasdeResult,
        result,
        report_month=month,
        tables=[tables[c] for c in chosen],
    )


TOOLSET = Toolset(
    name="commodities",
    description=(
        "Commodities: CFTC Commitments of Traders, JODI energy, OPEC basket price, "
        "LME warehouse stocks, USDA WASDE."
    ),
    tools=(
        ToolSpec(
            ndl_get_cot_report,
            "CFTC Commitments of Traders report",
            tables=tuple(COT_TABLES.values()),
        ),
        ToolSpec(
            ndl_get_jodi_energy_data,
            "JODI oil and gas statistics",
            tables=(JODI_TABLE,),
        ),
        ToolSpec(
            ndl_get_opec_basket_price,
            "OPEC basket crude price",
            tables=(OPEC_TABLE,),
        ),
        ToolSpec(
            ndl_get_lme_warehouse_stocks,
            "LME warehouse metal stocks",
            tables=(LME_TABLE,),
        ),
        ToolSpec(
            ndl_get_wasde_data,
            "USDA WASDE supply and demand",
            tables=(WASDE_DATA, WASDE_METADATA),
        ),
    ),
    prompts=(PromptSpec(cot_positioning_review, "COT positioning review"),),
)
