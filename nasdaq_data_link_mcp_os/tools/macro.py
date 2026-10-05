"""Macro series: IMF World Economic Outlook (QDL/ODA), ICE BofA bond indices (QDL/ML).

Both tables are free and frozen. QDL/ODA holds the IMF World Economic Outlook of
April 2023 (Nasdaq loaded it on 2023-10-31); QDL/ML holds 27 daily ICE BofA
corporate bond index series that end on 2025-02-27.

``data/macro_imf_concepts.json`` lists common WEO concept codes, the IMF group
codes and the WEO economy codes; ``data/macro_bond_series.json`` lists the QDL/ML
codes. Both carry labels written for this project. Country names come from the
world_bank toolset's data files, read only.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.query import check_date
from nasdaq_data_link_mcp_os.results import (
    ColumnInfo,
    TableResult,
    fit_rows,
    to_tool_result,
)
from nasdaq_data_link_mcp_os.tools._common import (
    EndDateArg,
    EndYearOrDateArg,
    LimitArg,
    StartDateArg,
    StartYearOrDateArg,
    Toolset,
    ToolSpec,
    app_state,
    as_list,
    build_result,
    date_range,
    fetch_table,
    get_metadata,
    period_bounds,
    read_table,
)

ODA = "QDL/ODA"
ML = "QDL/ML"
MAX_WEO_SERIES = 30
ROWS_PER_WEO_SERIES = 60  # 1980-2028 is 49 annual rows
WEO_EDITION = "April 2023"
WEO_LOADED = "2023-10-31"  # when Nasdaq loaded that edition into QDL/ODA
# In the April 2023 WEO, years after 2022 are IMF estimates or projections for
# most series; a few economies report with a longer lag.
WEO_LAST_ACTUAL = "2022"
CODE_RE = re.compile(r"^[A-Z0-9_]+$")

COUNTRY_HEADLINE: tuple[str, ...] = (
    "NGDPD",
    "NGDP_RPCH",
    "NGDPDPC",
    "PCPIPCH",
    "LUR",
    "GGXCNL_NGDP",
    "GGXWDG_NGDP",
    "BCA_NGDPD",
)
GROUP_HEADLINE: tuple[str, ...] = (
    "NGDPD",
    "NGDP_RPCH",
    "PCPIPCH",
    "GGXCNL_NGDP",
    "GGXWDG_NGDP",
    "BCA_NGDPD",
)
WORLD_HEADLINE: tuple[str, ...] = (
    "NGDPD",
    "NGDP_RPCH",
    "PCPIPCH",
    "TRADEPCH",
    "POILAPSP",
)
# World Bank codes that the IMF writes differently.
WB_TO_WEO = {
    "XKX": "UVK",
    "PSE": "WBG",
    "WLD": "WORLD",
    "EUU": "EU",
    "EMU": "EUROAREA",
    "LCN": "WE",
    "SSF": "SSA",
}


def _load_json(name: str) -> dict[str, Any]:
    path = resources.files("nasdaq_data_link_mcp_os").joinpath(f"data/{name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"data/{name} is not a JSON object")
    return data


def _shared_json(name: str) -> dict[str, Any]:
    """A world_bank data file; without it only codes and group names resolve."""
    try:
        return _load_json(name)
    except FileNotFoundError:
        return {}


def _norm(text: str) -> str:
    """Case-, accent- and punctuation-insensitive form of a name."""
    text = unicodedata.normalize("NFKD", text.replace("&", " and "))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _candidates(raw: str, labels: dict[str, str]) -> list[str]:
    """Up to five 'CODE (label)' whose code or label contains ``raw``."""
    needle = _norm(raw)
    if not needle:
        return []
    hits = [
        f"{code} ({label})"
        for code, label in labels.items()
        if needle in _norm(code) or needle in _norm(label)
    ]
    return hits[:5]


# ------------------------------------------------------------ IMF WEO data


@dataclass(frozen=True)
class Weo:
    concepts: dict[str, dict[str, Any]]
    groups: dict[str, str]
    economies: frozenset[str]
    codes: dict[str, str]  # ISO2 and World Bank codes -> WEO area code
    names: dict[str, str]  # normalized name -> WEO area code
    labels: dict[str, str]  # WEO area code -> name

    def is_area(self, code: str) -> bool:
        return code in self.groups or code in self.economies

    def find_area(self, raw: str) -> str | None:
        code = raw.strip().upper()
        if self.is_area(code):
            return code
        return self.codes.get(code) or self.names.get(_norm(raw))

    def resolve_area(self, raw: str) -> str:
        code = self.find_area(raw)
        if code:
            return code
        near = _candidates(raw, self.labels)
        hint = f" Names containing it: {'; '.join(near)}." if near else ""
        groups = ", ".join(f"{c} ({n})" for c, n in self.groups.items())
        raise InvalidRequestError(
            f"{raw.strip()!r} in `countries` is not a QDL/ODA economy or group, nor "
            f"an exact country name.{hint} QDL/ODA has 196 economies (ISO3 or ISO2 "
            f"codes such as USA, US) and the IMF groups {groups}."
        )

    def resolve_areas(self, value: str | Sequence[str] | None) -> list[str]:
        """A list, or one string: a single name ('Korea, Rep.') or 'A, B'."""
        if value is None:
            return []
        if isinstance(value, str):
            items = [value] if self.find_area(value) else value.split(",")
        else:
            items = list(value)
        return list(dict.fromkeys(self.resolve_area(v) for v in items if v.strip()))

    def concept_labels(self) -> dict[str, str]:
        return {code: item["label"] for code, item in self.concepts.items()}

    def resolve_concepts(self, value: str | Sequence[str] | None) -> list[str]:
        """Concept codes, upper-cased; codes outside the list pass through."""
        values = as_list(value, upper=False)
        for raw in values:
            if not CODE_RE.match(raw.upper()):
                near = _candidates(raw, self.concept_labels())
                hint = f" Concepts containing it: {'; '.join(near)}." if near else ""
                raise InvalidRequestError(
                    f"{raw!r} in `indicators` is not a WEO concept code (such as "
                    f"NGDP_RPCH or PCPIPCH).{hint}"
                )
        return list(dict.fromkeys(v.upper() for v in values))

    def split_series(self, raw: str) -> tuple[str, str]:
        """'USA_NGDPD' -> ('USA', 'NGDPD'); group codes may hold underscores."""
        code = raw.strip().upper()
        groups = sorted(self.groups, key=len, reverse=True)
        area = next((g for g in groups if code.startswith(g + "_")), code[:3])
        concept = code[len(area) + 1 :]
        if (
            CODE_RE.match(code)
            and code[len(area) : len(area) + 1] == "_"
            and concept
            and self.is_area(area)
        ):
            return area, concept
        raise InvalidRequestError(
            f"Unknown QDL/ODA series code {raw!r}: series codes are "
            "<economy>_<concept> or <group>_<concept> (USA_NGDPD, FAD_G7_NGDP_RPCH); "
            "concept codes alone go in `indicators`."
        )


@lru_cache(maxsize=1)
def weo() -> Weo:
    raw = _load_json("macro_imf_concepts.json")
    groups: dict[str, str] = dict(raw["groups"])
    economies = frozenset(raw["economies"])
    known = economies | set(groups)
    labels = dict(groups)
    names = {_norm(label): code for code, label in groups.items()}
    codes = dict(WB_TO_WEO)

    def add(name: str | None, code: str) -> None:
        code = WB_TO_WEO.get(code, code)
        if name and code in known:
            names.setdefault(_norm(name), code)

    for name, code in raw["aliases"].items():
        add(name, code)
        labels.setdefault(code, name)
    for wb_code, item in (
        _shared_json("wb_economies.json").get("economies") or {}
    ).items():
        code = WB_TO_WEO.get(wb_code, wb_code)
        # The World Bank's SSA excludes high-income economies: not the IMF's SSA.
        if code not in known or wb_code in groups:
            continue
        add(item.get("name"), code)
        labels.setdefault(code, item.get("name") or code)
        if item.get("iso2"):
            codes[str(item["iso2"]).upper()] = code
    wb_aliases = _shared_json("world_bank_aliases.json").get("aliases") or {}
    for name, wb_code in wb_aliases.items():
        add(name, wb_code)
    return Weo(
        concepts=dict(raw["concepts"]),
        groups=groups,
        economies=economies,
        codes=codes,
        names=names,
        labels=labels,
    )


class WeoSeries(BaseModel):
    indicator: str = Field(
        description="QDL/ODA series code <area>_<concept>, as in `series_codes`."
    )
    area: str = Field(description="ISO3 economy code or IMF group code.")
    area_name: str | None = Field(default=None, description="Economy or group name.")
    concept: str = Field(description="WEO concept code, as in `indicators`.")
    label: str | None = Field(default=None, description="What the concept measures.")
    unit: str | None = Field(default=None, description="Unit of `value`.")


class WeoResult(TableResult):
    """Annual IMF World Economic Outlook values with the meaning of each series."""

    series: list[WeoSeries] = Field(
        default_factory=list,
        description="Area, label and unit of each series requested.",
    )


def _weo_pairs(
    w: Weo,
    countries: str | list[str] | None,
    indicators: str | list[str] | None,
    series_codes: str | list[str] | None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve the arguments into (area, concept) pairs plus notes."""
    notes: list[str] = []
    pairs = [w.split_series(code) for code in as_list(series_codes)]
    areas = w.resolve_areas(countries)
    concepts = w.resolve_concepts(indicators)
    if areas or concepts or not pairs:
        moved = False
        for area in areas or ["WORLD"]:
            if area == "WORLD":
                headline = WORLD_HEADLINE
            else:
                headline = GROUP_HEADLINE if area in w.groups else COUNTRY_HEADLINE
            for concept in concepts or headline:
                world_only = w.concepts.get(concept, {}).get("world_only", False)
                moved = moved or (world_only and area != "WORLD")
                pairs.append(("WORLD" if world_only else area, concept))
        if moved:
            notes.append(
                "Commodity prices and world trade are published only under WORLD, "
                "so WORLD_<code> was read for them."
            )
        if not concepts:
            notes.append(
                "No indicator given: returning headline concepts ("
                + ", ".join(dict.fromkeys(c for _, c in pairs))
                + "); `indicators` selects others."
            )
    pairs = list(dict.fromkeys(pairs))
    if len(pairs) > MAX_WEO_SERIES:
        raise InvalidRequestError(
            f"{len(pairs)} series requested; the limit is {MAX_WEO_SERIES} per "
            "call. Pass fewer countries or indicators."
        )
    return pairs, notes


def _gap_notes(
    w: Weo, pairs: list[tuple[str, str]], names: list[str], rows: list[list[Any]]
) -> list[str]:
    """Name the series with no rows, or whose rows all lack a value."""
    i_ind, i_val = names.index("indicator"), names.index("value")
    has_value: dict[str, bool] = {}
    for row in rows:
        has_value[row[i_ind]] = has_value.get(row[i_ind], False) or (
            row[i_val] is not None
        )
    codes = [f"{a}_{c}" for a, c in pairs]
    empty = [c for c in codes if c in has_value and not has_value[c]]
    missing = [(a, c) for a, c in pairs if f"{a}_{c}" not in has_value]
    notes = []
    if empty:
        notes.append(
            "No values in this date range for: " + ", ".join(empty) + ". The IMF "
            "does not publish these for that economy or group."
        )
    if missing:
        note = "No rows in this date range for: " + ", ".join(
            f"{a}_{c}" for a, c in missing
        )
        unknown = list(dict.fromkeys(c for _, c in missing if c not in w.concepts))
        if unknown:
            near = [h for c in unknown for h in _candidates(c, w.concept_labels())]
            note += (
                ". Concept codes outside the common list are not checked: "
                + ", ".join(unknown)
                + ". "
                + (
                    "Common concepts containing them: " + "; ".join(near[:5])
                    if near
                    else "Common concepts: " + ", ".join(w.concepts)
                )
            )
        notes.append(note + ".")
    return notes


async def ndl_get_imf_weo_data(
    ctx: Context,
    indicators: Annotated[
        str | list[str] | None,
        Field(
            description="WEO concept codes such as NGDP_RPCH (real GDP growth). "
            "Default: headline set.",
        ),
    ] = None,
    countries: Annotated[
        str | list[str] | None,
        Field(
            description="ISO3/ISO2 codes, exact country names or IMF groups "
            "(FAD_G7). Default: WORLD.",
        ),
    ] = None,
    start_date: StartYearOrDateArg = None,
    end_date: EndYearOrDateArg = None,
    include_projections: Annotated[
        bool | None,
        Field(
            description="Years after 2022 (IMF estimates): true always, false "
            "never, default only with end_date.",
        ),
    ] = None,
    series_codes: Annotated[
        str | list[str] | None,
        Field(description="QDL/ODA codes such as USA_NGDPD."),
    ] = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, WeoResult]:
    """Get IMF World Economic Outlook annual data (GDP, growth, inflation, debt).

    QDL/ODA (free): the April 2023 WEO, 1980-2028, for 196 economies, 13 IMF
    groups and commodity prices (under WORLD). `projected` flags years after
    2022. ndl_get_world_bank_data has World Bank actuals.
    """
    w = weo()
    lo, hi = period_bounds(start_date, end_date)
    pairs, notes = _weo_pairs(w, countries, indicators, series_codes)
    # None: projections only when end_date is given; False: never; True: always.
    cut = include_projections is False or (include_projections is None and not hi)
    if cut and lo is not None and lo[:4] > WEO_LAST_ACTUAL:
        if include_projections is False:
            raise InvalidRequestError(
                f"start_date {start_date} is after {WEO_LAST_ACTUAL}, the last year "
                f"of reported data in the {WEO_EDITION} WEO, and include_projections "
                "is false, so no row can match."
            )
        cut = False
        notes.append(
            f"start_date is after {WEO_LAST_ACTUAL}, so IMF estimates and "
            "projections are returned."
        )
    if cut:
        hi = min(hi or "9999", f"{WEO_LAST_ACTUAL}-12-31")
        notes.append(
            f"Projections excluded: rows end in {WEO_LAST_ACTUAL}. "
            "include_projections=true adds IMF estimates and projections to 2028."
        )
    codes = [f"{a}_{c}" for a, c in pairs]
    read = await read_table(
        ctx,
        ODA,
        filters={"indicator": codes, **date_range("date", lo, hi)},
        page_size=ROWS_PER_WEO_SERIES * len(codes),
    )

    names, rows, columns = read.column_names, read.rows, read.columns
    if {"indicator", "date", "value"} <= set(names):
        i_ind, i_date = names.index("indicator"), names.index("date")
        order = {code: i for i, code in enumerate(codes)}
        rows = sorted(rows, key=lambda r: order.get(r[i_ind], len(order)))
        rows.sort(key=lambda r: str(r[i_date] or ""), reverse=True)
        rows = [[*r, str(r[i_date] or "")[:4] > WEO_LAST_ACTUAL] for r in rows]
        columns = [*columns, ColumnInfo(name="projected", type="boolean")]
        if not read.next_cursor:
            notes.extend(_gap_notes(w, pairs, names, rows))

    refreshed = (read.metadata.refreshed_at if read.metadata else None) or ""
    if refreshed and not refreshed.startswith(WEO_LOADED):
        edition = (
            f"Nasdaq reloaded QDL/ODA on {refreshed[:10]}, after the {WEO_EDITION} "
            f"WEO; `projected` (years after {WEO_LAST_ACTUAL}) follows that edition "
            "and may be out of date."
        )
    else:
        edition = (
            f"IMF WEO {WEO_EDITION} edition. `projected` marks years after "
            f"{WEO_LAST_ACTUAL}: IMF estimates or projections for most series (a "
            "few economies' last reported year is earlier)."
        )
    notes.insert(0, edition)

    result = build_result(ctx, read, rows, limit=limit, columns=columns, notes=notes)
    series = [
        WeoSeries(
            indicator=f"{area}_{concept}",
            area=area,
            area_name=w.labels.get(area),
            concept=concept,
            label=w.concepts.get(concept, {}).get("label"),
            unit=w.concepts.get(concept, {}).get("unit"),
        )
        for area, concept in pairs
    ]
    final = WeoResult(**result.model_dump(), series=series)
    return to_tool_result(fit_rows(final, app_state(ctx).settings.max_response_bytes))


# ------------------------------------------------------------ ICE BofA (ML)


@dataclass(frozen=True)
class Bonds:
    series: dict[str, dict[str, str]]
    last_date: str
    refreshed: str

    def resolve(self, value: str | Sequence[str] | None) -> list[str]:
        """Series codes, case-insensitive; anything else is an error."""
        codes: list[str] = []
        for raw in as_list(value, upper=False):
            if raw.upper() not in self.series:
                labels = {c: s["label"] for c, s in self.series.items()}
                near = _candidates(raw, labels)
                listed = near or [f"{c} ({label})" for c, label in labels.items()]
                raise InvalidRequestError(
                    f"Unknown QDL/ML series code {raw!r} in `series`. "
                    f"{'Series containing it' if near else 'Series'}: "
                    f"{'; '.join(listed)}."
                )
            codes.append(raw.upper())
        return list(dict.fromkeys(codes))


@lru_cache(maxsize=1)
def bonds() -> Bonds:
    raw = _load_json("macro_bond_series.json")
    return Bonds(
        series=dict(raw["series"]),
        last_date=str(raw["last_date"]),
        refreshed=str(raw["nasdaq_refreshed_at"]),
    )


class BondSeriesInfo(BaseModel):
    series_code: str = Field(description="ICE BofA series code (FRED-style id).")
    label: str = Field(description="Market, rating and measure.")
    unit: str = Field(description="percent, or index level for total-return series.")
    first_date: str = Field(description="First observation in QDL/ML.")


class BondIndexResult(TableResult):
    """Daily ICE BofA bond index values; the `rate` column holds each series' unit."""

    series: list[BondSeriesInfo] = Field(
        default_factory=list, description="What each series_code in `rows` measures."
    )


def _anchor_date(
    refreshed_at: str | None, last_date: str, end_date: str | None
) -> date:
    """Latest date worth reading back from: end_date capped at the table's end.

    The table's end is its refresh date, or the bundled last observation when
    the metadata has none, and never later than today.
    """
    today = datetime.now(UTC).date()
    table_end = today
    for candidate in (refreshed_at, last_date):
        try:
            table_end = min(date.fromisoformat((candidate or "")[:10]), today)
            break
        except ValueError:
            continue
    if end_date:
        return min(date.fromisoformat(check_date("end_date", end_date)[:10]), table_end)
    return table_end


async def ndl_get_bond_index_yields(
    ctx: Context,
    series: Annotated[
        str | list[str] | None,
        Field(
            description="ICE BofA series codes, e.g. BAMLH0A0HYM2 (US high-yield "
            "spread), BAMLC0A4CBBBEY (BBB yield). Default: all 27.",
        ),
    ] = None,
    start_date: StartDateArg = None,
    end_date: EndDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, BondIndexResult]:
    """Get ICE BofA corporate bond index yields, spreads and returns (ends 2025-02-27).

    Reads QDL/ML (free; Nasdaq no longer updates it): 27 daily ICE BofA index
    series under their FRED codes from 1996-12-31 (emerging markets 1998-12-31):
    US investment grade overall and AAA to BBB, US high yield overall and BB to
    CCC, emerging-market corporates. Yields and option-adjusted spreads are
    percent; total-return series are index levels. Without `series` and
    `start_date`, returns the latest value of every series on or before
    `end_date`, with its label. Rows are newest first.
    """
    state = app_state(ctx)
    table = bonds()
    codes = table.resolve(series)
    snapshot = not codes and start_date is None
    selected = codes or list(table.series)

    metadata = await get_metadata(state, ML)
    refreshed_at = metadata.refreshed_at if metadata else None
    anchor = _anchor_date(refreshed_at, table.last_date, end_date)
    start = start_date
    if snapshot:
        start = (anchor - timedelta(days=14)).isoformat()
    elif start is None:
        # Enough business days for `limit` rows per series, without a full scan.
        wanted = limit or state.settings.default_limit
        days = int(wanted / len(selected) * 7 / 5) + 10
        start = (anchor - timedelta(days=days)).isoformat()
    # An explicit start_date reads forward with no implied end; the default
    # windows are anchored on the table's last refresh.
    end = end_date if start_date else (end_date or anchor.isoformat())
    filters: dict[str, Any] = dict(date_range("date", start, end))
    if codes:
        filters["series_code"] = codes
    notes: list[str] = []
    if (refreshed_at or "").startswith(table.refreshed):
        notes.append(
            f"QDL/ML is no longer updated: its last observation is {table.last_date}."
        )
    notes.append(
        "Effective yields and spreads are percent; total-return series (codes "
        "ending TRIV) are index levels stored in the `rate` column."
    )
    result = await fetch_table(
        ctx,
        ML,
        filters=filters,
        limit=state.settings.max_limit if snapshot else limit,
        sort_by="date",
        descending=True,
        scan_size=40 * len(selected) if snapshot else 10_000,
        notes=notes,
    )
    payload = result.model_dump()
    names = [c.name for c in result.columns]
    index = names.index("series_code") if "series_code" in names else 0
    if snapshot:
        latest: dict[str, list[Any]] = {}
        for row in result.rows:
            latest.setdefault(row[index], row)
        rows = [latest[c] for c in table.series if c in latest]
        payload.update(rows=rows, row_count=len(rows), has_more=False)
        payload["notes"].append(f"Latest value of each series on or before {end}.")
    if not payload["rows"]:
        payload["notes"].append(
            f"No observations from {start} to {end or 'today'}; QDL/ML starts on "
            f"1996-12-31 and Nasdaq last refreshed it on "
            f"{(refreshed_at or table.refreshed)[:10]}."
        )
    returned = {row[index] for row in payload["rows"] if len(row) > index}
    info = [
        BondSeriesInfo(series_code=code, **item)
        for code, item in table.series.items()
        if code in codes or (not codes and code in returned)
    ]
    final = BondIndexResult(**payload, series=info)
    return to_tool_result(fit_rows(final, state.settings.max_response_bytes))


TOOLSET = Toolset(
    name="macro",
    description=(
        "Macro series: IMF World Economic Outlook (April 2023 edition, annual to "
        "2028) and ICE BofA corporate bond index yields (daily, ending 2025-02-27)."
    ),
    tools=(
        ToolSpec(
            ndl_get_imf_weo_data, "Get IMF World Economic Outlook data", tables=(ODA,)
        ),
        ToolSpec(
            ndl_get_bond_index_yields, "Get ICE BofA bond index yields", tables=(ML,)
        ),
    ),
    hints=("IMF projections: ndl_get_imf_weo_data (include_projections=true).",),
)
