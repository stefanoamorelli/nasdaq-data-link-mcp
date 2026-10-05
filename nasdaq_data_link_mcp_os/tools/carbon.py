"""Carbon removal certificates (Puro.earth CORC) published by Nasdaq.

Nasdaq's Carbon Removal Data-CORC product (BUWP) republishes the Puro.earth
registry. Six of its seven tables are free and refreshed daily, and each holds
fewer than 10,000 rows, so a read takes every row that matches the server-side
filters, applies the remaining filters locally and sorts the result (Nasdaq
returns rows unsorted).

Two quirks of the tables shape the filtering:

- Nasdaq splits filter values on commas. Some facility names ("Carbon Cycle,
  001, Rieden, DE") and the versioned methodology names of FAFD and SYVW
  ("Biochar, 2022") contain one, so facilities are filtered by ``facility_id``
  and versioned methodologies are matched locally on their base name.
- Durability categories are spelled "CORC100+" in FAFD and "CORC 100+" in the
  other tables; both spellings are sent or compared.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.errors import InvalidRequestError, UpstreamError
from nasdaq_data_link_mcp_os.query import sort_rows_by
from nasdaq_data_link_mcp_os.results import TableResult, fit_rows, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    EndYearOrDateArg,
    LimitArg,
    StartYearOrDateArg,
    TableRead,
    Toolset,
    ToolSpec,
    app_state,
    build_result,
    date_range,
    period_bounds,
    read_table,
)

FACILITIES = "NDAQ/FAFD"
_FAFD_COLUMNS = "facility facility_id country region methodology durability_category"

Methodology = Literal[
    "Biochar",
    "Carbonated Materials",
    "Enhanced Rock Weathering",
    "Geologically stored carbon",
    "Soil Amendment",
    "Terrestrial Storage of Biomass",
    "Wooden Building Elements",
]
Durability = Literal["CORC", "CORC 20+", "CORC 100+", "CORC 1000+"]
TransactionType = Literal["Issuance", "Transfer", "Retirement", "Withdrawal"]
Region = Literal[
    "Africa", "Asia", "Europe", "North America", "Oceania", "South America"
]
DatasetName = Literal[
    "facility_volumes",
    "methodology_volumes",
    "retirements",
    "transactions",
    "registry_view",
    "reference_prices",
]

# Nasdaq's spelling of three countries, keyed by common short forms.
_COUNTRY_ALIASES = {
    "us": "united states of america",
    "usa": "united states of america",
    "united states": "united states of america",
    "uk": "united kingdom",
    "great britain": "united kingdom",
    "serbia": "republic of serbia",
}
_ID_LIST_RE = re.compile(r"^\d+(\s*,\s*\d+)+$")
# Month labels of NDAQ/TRAN (premium; format unpublished): 2025-03[-01], 202503,
# 03/2025, Mar 2025 or March 2025.
_MONTH_FORMS = (
    re.compile(r"(?P<y>\d{4})(?:[-/.](?P<m>\d{1,2})\b|(?P<mm>\d{2})$)"),
    re.compile(r"(?P<m>\d{1,2})[-/.](?P<y>\d{4})$"),
    re.compile(r"(?P<name>[a-z]{3})[a-z]*\.?,?\s+(?P<y>\d{4})$"),
)
_MONTH_NAMES = "jan feb mar apr may jun jul aug sep oct nov dec".split()

Test = Callable[[dict[str, Any]], bool]


class FacilityMatch(BaseModel):
    query: str
    facility_id: str
    facility: str | None = None


class MethodologyDoc(BaseModel):
    methodology: str
    version: str | None = None
    url: str


class CarbonResult(TableResult):
    """Rows from one table of Nasdaq's Carbon Removal Data-CORC product."""

    matched_facilities: list[FacilityMatch] | None = Field(
        default=None, description="Facilities that `facilities` resolved to."
    )
    methodology_docs: list[MethodologyDoc] | None = Field(
        default=None, description="Puro.earth methodology documents of the rows shown."
    )


@dataclass(frozen=True)
class _Dataset:
    code: str
    params: str  # optional filters the dataset accepts
    server: str  # of those, the ones sent to Nasdaq (names separated by spaces)
    time: Literal["date", "year", "month"]  # column start/end_date apply to
    sort: tuple[tuple[str, bool], ...]  # (column, descending), major first
    holder: str = ""  # column that `account_holder` searches
    hidden: tuple[str, ...] = ()
    drop_zero: bool = False  # leave out rows whose volume_* columns are all 0
    note: str | None = None


_NEWEST_BY_VOLUME = (("year", True), ("volume_issued_net_vintage", True))

DATASETS: dict[str, _Dataset] = {
    "facility_volumes": _Dataset(
        code="NDAQ/FIRC",
        params="facilities methodology durability_category",
        server="methodology durability_category",
        time="year",
        sort=_NEWEST_BY_VOLUME,
        drop_zero=True,
        note=(
            "Volumes are CORCs (tonnes of CO2e) by vintage year, the year the "
            "removal happened; the current year is year-to-date."
        ),
    ),
    "methodology_volumes": _Dataset(
        code="NDAQ/IRBM",
        params="methodology",
        server="methodology",
        time="year",
        sort=_NEWEST_BY_VOLUME,
        drop_zero=True,
        note=(
            "Issued volumes are by vintage year, volume_retired_transaction by "
            "retirement year; the current year is year-to-date. pct_retired_* "
            "are shares (0-1) of retirements by beneficiary continent (na, sa, eu, "
            "oc, as, af); Nasdaq publishes issuance shares only for North "
            "(pct_issued_na) and South America (pct_issued_sa)."
        ),
    ),
    "retirements": _Dataset(
        code="NDAQ/RITM",
        params=(
            "facilities methodology durability_category account_holder "
            "retirement_location"
        ),
        server="methodology durability_category",
        time="date",
        sort=(("date", True),),
        holder="beneficiary",
    ),
    "transactions": _Dataset(
        code="NDAQ/COLT",
        params="facilities methodology transaction_type account_holder",
        server="facilities methodology transaction_type",
        time="date",
        sort=(("date", True),),
        holder="receiver_name",
    ),
    "registry_view": _Dataset(
        code="NDAQ/SYVW",
        params=(
            "facilities methodology durability_category transaction_type account_holder"
        ),
        server="facilities",
        time="date",
        sort=(("date", True),),
        holder="account_holder_name",
        hidden=("methodology_documentation_url",),
        note=(
            "In this table `volume` does not always equal the certificate range "
            "in certificates_bundle; the transactions dataset reports per-bundle "
            "volumes."
        ),
    ),
    "reference_prices": _Dataset(
        code="NDAQ/TRAN",
        params="methodology",
        server="",
        time="month",
        sort=(("month", True), ("methodology", False)),
    ),
}


FacilitiesArg = Annotated[
    str | list[str] | None,
    Field(description="Facility IDs or exact facility names; one or a list."),
]
MethodologyArg = Annotated[
    Methodology | None,
    Field(description="Puro.earth methodology."),
]
DurabilityArg = Annotated[Durability | None, Field(description="Durability class.")]


def _key(text: Any) -> str:
    """Case-, accent- and punctuation-insensitive form of a name."""
    plain = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return " ".join("".join(c for c in plain if c.isalnum() or c.isspace()).split())


def _country(text: Any) -> str:
    key = _key(text)
    return _COUNTRY_ALIASES.get(key, key)


def _base_methodology(value: Any) -> str:
    return _key(str(value or "").split(",")[0])


def _compact(value: Any) -> str:
    return str(value or "").replace(" ", "").casefold()


def _equals(column: str, wanted: str, norm: Callable[[Any], str] = _key) -> Test:
    target = norm(wanted)
    return lambda r: norm(r.get(column)) == target


def _month(value: Any) -> tuple[int, int] | None:
    """(year, month) named by a month label, else None."""
    text = " ".join(str(value or "").casefold().split())
    for form in _MONTH_FORMS:
        if found := form.match(text):
            parts = found.groupdict()
            name = parts.get("name")
            month = (
                _MONTH_NAMES.index(name) + 1
                if name in _MONTH_NAMES
                else int(parts.get("m") or parts.get("mm") or 0)
            )
            return (int(parts["y"]), month) if 1 <= month <= 12 else None
    return None


def _facility_queries(value: str | Sequence[str]) -> list[str]:
    items = [value] if isinstance(value, str) else list(value)
    # Names may contain commas; only a string of numeric IDs is split.
    parts = [
        part
        for item in items
        for part in (item.split(",") if _ID_LIST_RE.match(item.strip()) else [item])
    ]
    queries = [q for q in (p.strip(" ,\t\n") for p in parts) if q]
    if not queries:
        raise InvalidRequestError("`facilities` is empty; pass facility IDs or names.")
    return list(dict.fromkeys(queries))


def _directory(read: TableRead) -> dict[str, str]:
    """facility_id -> facility name, from rows of NDAQ/FAFD."""
    _require(read, ("facility_id", "facility"))
    return {
        str(r["facility_id"]).strip(): str(r["facility"] or "")
        for r in read.records()
        if r["facility_id"]
    }


def _match_facilities(
    directory: Mapping[str, str], queries: Sequence[str]
) -> list[FacilityMatch]:
    """Resolve facility IDs or exact names (case, accents and punctuation aside)."""
    by_name: dict[str, list[str]] = {}
    for fid, name in directory.items():
        by_name.setdefault(_key(name), []).append(fid)
    matches: list[FacilityMatch] = []
    for query in queries:
        ids = [query] if query in directory else by_name.get(_key(query), [])
        if not ids:
            needle = _key(query)
            found = [
                f"{name!r} ({fid})"
                for fid, name in sorted(directory.items(), key=lambda f: _key(f[1]))
                if needle and (needle in _key(name) or needle in fid)
            ]
            hint = f" Names containing it: {', '.join(found[:5])}." if found else ""
            raise InvalidRequestError(
                f"No Puro.earth facility has the ID or name {query!r}.{hint} "
                f"ndl_get_carbon_removal_facilities lists all {len(directory)} "
                "facilities with their IDs."
            )
        matches += [
            FacilityMatch(query=query, facility_id=i, facility=directory[i])
            for i in ids
        ]
    return matches


def _require(read: TableRead, columns: Sequence[str]) -> None:
    missing = [c for c in dict.fromkeys(columns) if c not in read.column_names]
    if missing:
        raise UpstreamError(
            f"{read.code} no longer has the column(s) {', '.join(missing)}; "
            "read it with ndl_query_table."
        )


@dataclass
class _Local:
    """Filters applied to the rows read: echoed in the request, then tested."""

    echo: dict[str, Any] = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    tests: list[Test] = field(default_factory=list)

    def add(self, param: str, shown: Any, test: Test, *columns: str) -> None:
        self.echo[param] = shown
        self.columns += columns or (param,)
        self.tests.append(test)

    def rows(self, read: TableRead) -> list[list[Any]]:
        _require(read, self.columns)
        names = read.column_names
        return [
            row
            for row in read.rows
            if all(test(dict(zip(names, row, strict=False))) for test in self.tests)
        ]


def _request(
    read: TableRead, local: Mapping[str, Any], sort: Sequence[tuple[str, bool]]
) -> dict[str, Any]:
    request = dict(read.request)
    request["sort_by"] = ", ".join(f"{c} {'desc' if d else 'asc'}" for c, d in sort)
    if local:
        request["local_filters"] = dict(local)
    return request


# ------------------------------------------------------------------- tools


async def ndl_get_carbon_removal_facilities(
    ctx: Context,
    facilities: FacilitiesArg = None,
    country: Annotated[
        str | None,
        Field(description="Country of the facility, e.g. 'Finland' or 'USA'."),
    ] = None,
    region: Annotated[
        Region | None, Field(description="Continent of the facility.")
    ] = None,
    methodology: MethodologyArg = None,
    durability_category: DurabilityArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, TableResult]:
    """List Puro.earth carbon removal facilities: location, methodology, owner, auditor.

    Every facility that has issued CORCs, from Nasdaq's Carbon Removal Data-CORC
    (free, refreshed daily), one row per durability category, with the latest
    audit date and audited period. Its facility_id or name feeds `facilities` in
    ndl_get_carbon_removal_data.
    """
    queries = _facility_queries(facilities) if facilities else []
    country = (country or "").strip()
    read = await read_table(ctx, FACILITIES)
    _require(read, _FAFD_COLUMNS.split())
    local = _Local()
    if queries:
        ids = {m.facility_id for m in _match_facilities(_directory(read), queries)}
        local.add("facility_id", sorted(ids), lambda r: str(r["facility_id"]) in ids)
    if country:
        present = sorted({str(r["country"]) for r in read.records() if r["country"]})
        if _country(country) not in {_country(c) for c in present}:
            raise InvalidRequestError(
                f"No Puro.earth facility is located in {country!r}. Countries "
                f"with facilities: {', '.join(present)}."
            )
        local.add("country", country, _equals("country", country, _country))
    if region:
        local.add("region", region, _equals("region", region))
    if methodology:
        test = _equals("methodology", methodology, _base_methodology)
        local.add("methodology", methodology, test)
    if durability_category:
        test = _equals("durability_category", durability_category, _compact)
        local.add("durability_category", durability_category, test)

    rows = local.rows(read)
    names = read.column_names
    i_name, i_durability = names.index("facility"), names.index("durability_category")
    rows.sort(key=lambda r: (_key(r[i_name]), _compact(r[i_durability])))
    sort = (("facility", False), ("durability_category", False))
    request = _request(read, local.echo, sort)
    return to_tool_result(build_result(ctx, read, rows, limit=limit, request=request))


async def ndl_get_carbon_removal_data(
    ctx: Context,
    dataset: Annotated[DatasetName, Field(description="Table to read.")],
    facilities: FacilitiesArg = None,
    methodology: MethodologyArg = None,
    durability_category: DurabilityArg = None,
    transaction_type: Annotated[
        TransactionType | None,
        Field(description="Withdrawal: registry_view only."),
    ] = None,
    account_holder: Annotated[
        str | None,
        Field(description="Part of a beneficiary or receiver name."),
    ] = None,
    retirement_location: Annotated[
        str | None,
        Field(description="Beneficiary's country or continent."),
    ] = None,
    start_date: StartYearOrDateArg = None,
    end_date: EndYearOrDateArg = None,
    limit: LimitArg = None,
) -> Annotated[CallToolResult, CarbonResult]:
    """Get Puro.earth carbon removal (CORC) volumes, retirements, transactions, prices.

    Puro.earth registry since 2019 (one CORC = one tonne of CO2 removed). Free,
    refreshed daily, newest first, except reference_prices (subscription).
    """
    spec = DATASETS[dataset]
    account_holder = (account_holder or "").strip()
    retirement_location = (retirement_location or "").strip()
    given = {
        "facilities": facilities,
        "methodology": methodology,
        "durability_category": durability_category,
        "transaction_type": transaction_type,
        "account_holder": account_holder,
        "retirement_location": retirement_location,
    }
    _check_params(dataset, spec, given)
    queries = _facility_queries(facilities) if facilities else []
    lo, hi = period_bounds(start_date, end_date)

    server: dict[str, Any] = {}
    local = _Local(columns=[c for c, _ in spec.sort])
    months: tuple[tuple[int, int], tuple[int, int]] | None = None
    if spec.time == "date":
        server.update(date_range("date", lo, hi))
    elif spec.time == "year":
        bounds = (("year.gte", lo), ("year.lte", hi))
        server.update({k: int(v[:4]) for k, v in bounds if v})
    elif lo or hi:
        # Month labels are text: each bound selects the whole month it falls in.
        first = (int(lo[:4]), int(lo[5:7])) if lo else (0, 0)
        last = (int(hi[:4]), int(hi[5:7])) if hi else (9999, 12)
        months = (first, last)
        bounds = (("month.gte", lo), ("month.lte", hi))
        local.echo.update({k: v[:7] for k, v in bounds if v})

    def route(column: str, value: str, test: Test, sent: Any = None) -> None:
        if column in spec.server.split():
            server[column] = value if sent is None else sent
        else:
            local.add(column, value, test)

    matches: list[FacilityMatch] = []
    if queries:
        directory = await read_table(
            ctx, FACILITIES, columns=("facility_id", "facility"), validate=False
        )
        matches = _match_facilities(_directory(directory), queries)
        ids = list(dict.fromkeys(m.facility_id for m in matches))
        if "facilities" in spec.server.split():
            server["facility_id"] = ids
        else:
            local.add("facility_id", ids, lambda r: str(r["facility_id"]) in ids)
    if methodology:
        test = _equals("methodology", methodology, _base_methodology)
        route("methodology", methodology, test)
    if durability_category:
        test = _equals("durability_category", durability_category, _compact)
        spellings = list(
            dict.fromkeys([durability_category, durability_category.replace(" ", "")])
        )
        route("durability_category", durability_category, test, spellings)
    if transaction_type:
        test = _equals("transaction_type", transaction_type)
        route("transaction_type", transaction_type, test)
    if account_holder:
        needle = account_holder.casefold()
        local.add(
            "account_holder",
            account_holder,
            lambda r: needle in str(r[spec.holder] or "").casefold(),
            spec.holder,
        )
    if retirement_location:
        place = _country(retirement_location)
        local.add(
            "retirement_location",
            retirement_location,
            lambda r: (
                place
                in (_country(r["country_retirement"]), _key(r["region_retirement"]))
            ),
            "country_retirement",
            "region_retirement",
        )

    read = await read_table(ctx, spec.code, filters=server)
    rows = local.rows(read)
    names = read.column_names
    notes: list[str] = []
    if months:
        i_month = names.index("month")
        labelled = [(_month(row[i_month]), row) for row in rows]
        if unread := sum(month is None for month, _ in labelled):
            notes.append(
                f"{unread} rows whose month label is not a recognised month were "
                "left out of the date range."
            )
        rows = [r for m, r in labelled if m is not None and months[0] <= m <= months[1]]
    if spec.drop_zero:
        volumes = [i for i, n in enumerate(names) if n.startswith("volume_")]
        nonzero = [r for r in rows if any(r[i] for i in volumes)]
        if len(nonzero) < len(rows):
            notes.append(
                f"{len(rows) - len(nonzero)} rows with no issued or retired "
                "volume were left out."
            )
        rows = nonzero
    rows = sort_rows_by(names, rows, [k for k in spec.sort if k[0] != "month"])
    if spec.time == "month":  # text labels: sort by the month they name
        i_month = names.index("month")
        rows.sort(key=lambda r: _month(r[i_month]) or (0, 0), reverse=True)
    if rows and spec.note:
        notes.append(spec.note)

    settings = app_state(ctx).settings
    row_limit = max(1, min(limit or settings.default_limit, settings.max_limit))
    if len(rows) > row_limit:
        notes.append(
            f"{len(rows)} rows matched; showing the newest {row_limit}. An earlier "
            "end_date reaches older rows."
        )
    docs = _methodology_docs(read, rows[:row_limit]) if spec.hidden else []
    keep = [i for i, n in enumerate(names) if n not in spec.hidden]
    if len(keep) < len(names):
        rows = [[row[i] for i in keep] for row in rows]
    result = build_result(
        ctx,
        read,
        rows,
        limit=row_limit,
        columns=[read.columns[i] for i in keep],
        notes=notes,
        request=_request(read, local.echo, spec.sort),
        count_note=False,
    )
    out = CarbonResult(
        **dict(result),
        matched_facilities=matches or None,
        methodology_docs=docs or None,
    )
    return to_tool_result(fit_rows(out, settings.max_response_bytes))


def _check_params(dataset: str, spec: _Dataset, given: Mapping[str, Any]) -> None:
    accepted = [p for p in given if p in spec.params.split()]
    extra = [p for p, value in given.items() if value and p not in accepted]
    if extra:
        used = {
            p: [n for n, d in DATASETS.items() if p in d.params.split()] for p in extra
        }
        accepted += ["start_date", "end_date", "limit"]
        raise InvalidRequestError(
            f"Dataset {dataset!r} ({spec.code}) does not take "
            + "; ".join(f"{p} (used by {', '.join(u)})" for p, u in used.items())
            + f". It accepts: {', '.join(accepted)}."
        )
    if dataset == "transactions" and given["transaction_type"] == "Withdrawal":
        raise InvalidRequestError(
            "The transactions dataset lists issuances, transfers and retirements; "
            "withdrawals are in registry_view."
        )


def _methodology_docs(
    read: TableRead, rows: Sequence[list[Any]]
) -> list[MethodologyDoc]:
    docs: dict[tuple[str, str | None], MethodologyDoc] = {}
    for r in read.records(rows):
        if url := r.get("methodology_documentation_url"):
            version = r.get("methodology_version")
            key = (str(r.get("methodology")), str(version) if version else None)
            doc = MethodologyDoc(methodology=key[0], version=key[1], url=str(url))
            docs.setdefault(key, doc)
    return list(docs.values())


TOOLSET = Toolset(
    name="carbon",
    description="Carbon removal certificates (Puro.earth CORC) published by Nasdaq.",
    tools=(
        ToolSpec(
            ndl_get_carbon_removal_facilities,
            "Carbon removal facilities (CORC)",
            tables=(FACILITIES,),
        ),
        ToolSpec(
            ndl_get_carbon_removal_data,
            "Carbon removal volumes and trades",
            tables=(*(d.code for d in DATASETS.values()), FACILITIES),
        ),
    ),
)
