from __future__ import annotations

import re
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.server import create_server
from nasdaq_data_link_mcp_os.tools import housing
from tests import fake_nasdaq
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def nasdaq_collation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text ranges ignore case, spaces and punctuation on Nasdaq, as checked
    live: region.gte='Austin TX' & region.lt='Austin TY' returns the metro
    'Austin, TX' and the city 'Austin;TX;...'."""
    original = fake_nasdaq._matches

    def collated(value: Any, op: str, target: str) -> bool:
        if op != "eq" and isinstance(value, str):
            value, target = (re.sub(r"[\W_]+", "", v) for v in (value, target))
        return original(value, op, target)

    monkeypatch.setattr(fake_nasdaq, "_matches", collated)


# ZILLOW/REGIONS rows as Nasdaq stores them (ZIP 08904 lost its leading zero).
REGION_ROWS: list[list[Any]] = [
    [
        "97565",
        "zip",
        "94110;CA;San Francisco-Oakland-Berkeley, CA;San Francisco;"
        "San Francisco County",
    ],
    ["61248", "zip", "8904;NJ;New York-Newark-Jersey City, NY-NJ-PA;Highland Park"],
    ["95000", "zip", "89040;NV;Las Vegas-Henderson-Paradise, NV;Clark County"],
    ["9", "state", "California"],
    ["844", "county", "Austin County;TX;Houston-The Woodlands-Sugar Land, TX"],
    ["821653", "neigh", "Austin Ranch;TX;Dallas-Fort Worth-Arlington, TX;The Colony"],
    ["394355", "metro", "Austin, TX"],
    ["394354", "metro", "Austin, MN"],
    ["37228", "city", "Austinburg;OH;Ashtabula, OH;Ashtabula County"],
    ["23555", "city", "Austin;MN;Austin, MN;Mower County"],
    ["10221", "city", "Austin;TX;Austin-Round Rock-Georgetown, TX;Travis County"],
    ["102001", "metro", "United States"],
    [
        "274552",
        "neigh",
        "Mission;CA;San Francisco-Oakland-Berkeley, CA;San Francisco;"
        "San Francisco County",
    ],
]

# ZILLOW/INDICATORS layout with real ids and categories (names are ours), in no
# particular order, as Nasdaq returns them.
INDICATOR_ROWS: list[list[Any]] = [
    ["SSAW", "Median sale price (smooth, all homes, weekly)", "Inventory and sales"],
    ["RSNA", "ZORI smoothed ($)", "Rentals"],
    ["ZCON", "ZHVI condo/co-op ($)", "Home values"],
    ["ISAM", "For-sale inventory (smooth, all homes, monthly)", "Inventory and sales"],
    ["ZALL", "ZHVI all homes ($)", "Home values"],
    ["SSAM", "Median sale price (smooth, all homes, monthly)", "Inventory and sales"],
    ["ZATT", "ZHVI top tier ($)", "Home values"],
]


def _months(start: str, end: str) -> list[str]:
    """Month-end dates from start to end (YYYY-MM), inclusive."""
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    year, month = int(start[:4]), int(start[5:7])
    out = []
    while f"{year:04d}-{month:02d}" <= end:
        day = 29 if month == 2 and year % 4 == 0 else days[month - 1]
        out.append(f"{year:04d}-{month:02d}-{day:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _series(
    indicator: str, region: str, start: str, end: str, base: float
) -> list[list[Any]]:
    return [
        [indicator, region, d, base + i * 1000.123456]
        for i, d in enumerate(_months(start, end))
    ]


def _zillow(
    fake: FakeNasdaq,
    *,
    regions: list[list[Any]] | None = None,
    indicators: list[list[Any]] | None = None,
) -> None:
    fake.add_table(
        "ZILLOW/REGIONS",
        columns=[("region_id", "text"), ("region_type", "text"), ("region", "text")],
        filters=["region_id", "region", "region_type"],
        primary_key=["region_id"],
        rows=REGION_ROWS if regions is None else regions,
    )
    fake.add_table(
        "ZILLOW/INDICATORS",
        columns=[("indicator_id", "text"), ("indicator", "text"), ("category", "text")],
        filters=["indicator", "indicator_id"],
        primary_key=["indicator_id"],
        rows=INDICATOR_ROWS if indicators is None else indicators,
    )
    fake.add_table(
        "ZILLOW/DATA",
        columns=[
            ("indicator_id", "text"),
            ("region_id", "text"),
            ("date", "Date"),
            ("value", "double"),
        ],
        filters=["indicator_id", "region_id"],
        primary_key=["indicator_id", "region_id", "date"],
        rows=_series("ZALL", "10221", "2023-01", "2025-06", 500_000)
        + _series("ZALL", "394355", "2023-01", "2025-01", 450_000)
        + _series("ZALL", "9", "2024-01", "2025-06", 750_000)
        + _series("ZALL", "102001", "2024-01", "2025-01", 350_000)
        + _series("RSNA", "394355", "2021-01", "2022-07", 1_500),
    )


async def _call(client: Client, tool: str, **args: Any) -> dict[str, Any]:
    return payload(await client.call_tool(tool, args))


# ------------------------------------------------------------ pure helpers


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            ["10221", "city", "Austin;TX;Austin-Round Rock, TX;Travis County"],
            ("city", "Austin", "TX", ("Austin-Round Rock, TX", "Travis County")),
        ),
        (
            ["62952", "zip", "13093; NY; Syracuse; nan; Oswego County"],
            ("zip", "13093", "NY", ("Syracuse", "Oswego County")),
        ),
        (["61248", "zip", "8904;NJ"], ("zip", "08904", "NJ", ())),
        (
            ["394913", "metro", "New York, NY-NJ-PA"],
            ("metro", "New York, NY-NJ-PA", "NY-NJ-PA", ()),
        ),
        (["274552", "neigh", "Mission;CA"], ("neighborhood", "Mission", "CA", ())),
    ],
)
def test_parse_region(row: list[str], expected: tuple[Any, ...]) -> None:
    region = housing.parse_region(*row)
    assert (region.region_type, region.name, region.state, region.parents) == expected


@pytest.mark.parametrize(
    ("prefix", "bound"),
    [("Austin TX", "Austin TY"), ("Ritz", "Riu"), ("St.", "Su"), ("zz", None)],
)
def test_upper_bound(prefix: str, bound: str | None) -> None:
    assert housing.upper_bound(prefix) == bound


# ------------------------------------------------------------- region search


async def test_search_regions_by_name(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake)
    async with make_client() as client:
        qualified = await _call(client, "ndl_search_zillow_regions", query="Austin, TX")
        bare = await _call(client, "ndl_search_zillow_regions", query="Austin")
    # commas are sent as spaces: Nasdaq reads a comma in a range value as a list
    assert fake.data_requests("ZILLOW/REGIONS")[0] == {
        "region.gte": "Austin TX",
        "region.lt": "Austin TY",
        "qopts.per_page": "10000",
    }
    assert [r["region_id"] for r in qualified["results"]] == ["394355", "10221"]
    assert qualified["results"][1] == {
        "region_id": "10221",
        "region_type": "city",
        "name": "Austin",
        "state": "TX",
        "parents": ["Austin-Round Rock-Georgetown, TX", "Travis County"],
        "match": "exact",
    }
    # exact names first, larger areas before smaller, then prefix matches
    assert [(r["region_id"], r["match"]) for r in bare["results"]] == [
        ("394354", "exact"),
        ("394355", "exact"),
        ("10221", "exact"),
        ("23555", "exact"),
        ("844", "prefix"),
        ("37228", "prefix"),
        ("821653", "prefix"),
    ]
    assert bare["results"][-1]["region_type"] == "neighborhood"


@pytest.mark.parametrize(
    ("query", "sent", "found"),
    [("94110", "94110", ["97565"]), ("08904", "8904", ["61248"])],
)
async def test_search_zip_codes(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    query: str,
    sent: str,
    found: list[str],
) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(client, "ndl_search_zillow_regions", query=query)
    assert fake.data_requests("ZILLOW/REGIONS")[0]["region.gte"] == sent
    assert [r["region_id"] for r in data["results"]] == found  # not ZIP 89040
    assert data["results"][0]["name"] == query


async def test_search_region_type_uses_zillow_spelling(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(
            client,
            "ndl_search_zillow_regions",
            query="Mission",
            region_type="neighborhood",
        )
        old = error_text(
            await client.call_tool(
                "ndl_search_zillow_regions",
                {"query": "Mission", "region_type": "neigh"},
            )
        )
    assert fake.data_requests("ZILLOW/REGIONS")[0]["region_type"] == "neigh"
    assert [r["region_id"] for r in data["results"]] == ["274552"]
    assert "neighborhood" in old


async def test_search_without_match_or_too_short(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake)
    async with make_client() as client:
        none = await _call(client, "ndl_search_zillow_regions", query="Atlantis")
        short = error_text(
            await client.call_tool("ndl_search_zillow_regions", {"query": "A."})
        )
    assert none["results"] == [] and none["notes"]
    assert "[INVALID_REQUEST]" in short
    assert len(fake.data_requests("ZILLOW/REGIONS")) == 1


async def test_search_notes_a_truncated_read(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    rows = [[str(i), "city", f"Spring{i:05d};TX"] for i in range(1, 10_002)]
    _zillow(fake, regions=rows)
    async with make_client() as client:
        data = await _call(client, "ndl_search_zillow_regions", query="Spring")
    assert data["total_matches"] == 10_000 and data["result_count"] == 20
    assert data["has_more"] is True
    assert any("10,000" in n for n in data["notes"])


# ---------------------------------------------------------- indicator search


async def test_search_indicators_reads_the_table_once(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _zillow(fake)
    now = [1000.0]
    monkeypatch.setattr(housing, "_clock", lambda: now[0])

    async def ids(client: Client, **args: Any) -> list[str]:
        data = await _call(client, "ndl_search_zillow_indicators", **args)
        return [i["indicator_id"] for i in data["indicators"]]

    async with make_client() as client:
        everything = await _call(client, "ndl_search_zillow_indicators")
        weekly = await ids(client, query="sale price WEEKLY")
        rentals = await ids(client, category="rentals")
        zips = await ids(client, region_type="zip")
        none = await _call(client, "ndl_search_zillow_indicators", query="mortgage")
        assert len(fake.data_requests("ZILLOW/INDICATORS")) == 1
        now[0] += housing.INDICATORS_TTL_SECONDS + 1
        await ids(client)
    assert (
        fake.data_requests("ZILLOW/INDICATORS")
        == [
            {
                "qopts.columns": "indicator_id,indicator,category",
                "qopts.per_page": "1000",
            }
        ]
        * 2
    )
    assert everything["result_count"] == len(INDICATOR_ROWS)
    # sorted by category (home values, rentals, inventory and sales), then id
    assert [i["indicator_id"] for i in everything["indicators"]] == [
        "ZALL",
        "ZATT",
        "ZCON",
        "RSNA",
        "ISAM",
        "SSAM",
        "SSAW",
    ]
    assert everything["indicators"][0] == {
        "indicator_id": "ZALL",
        "name": "ZHVI all homes ($)",
        "category": "Home values",
        "frequency": "monthly",
        "region_types": list(housing.REGION_TYPES),
    }
    assert weekly == ["SSAW"]
    assert rentals == ["RSNA"]
    assert zips == ["ZALL", "ZCON", "RSNA"]  # no tiers or sales for ZIP codes
    assert none["indicators"] == [] and len(none["notes"]) == 2


async def test_empty_indicator_table_is_not_cached(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake, indicators=[])
    async with make_client() as client:
        failed = error_text(await client.call_tool("ndl_search_zillow_indicators", {}))
        fake.tables["ZILLOW/INDICATORS"].rows = INDICATOR_ROWS
        data = await _call(client, "ndl_search_zillow_indicators")
    assert "[UPSTREAM]" in failed
    assert data["result_count"] == len(INDICATOR_ROWS)


# --------------------------------------------------------------- data tool


async def test_get_data_by_ids(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(
            client, "ndl_get_zillow_data", indicator="ZALL", regions="10221", limit=3
        )
    assert fake.data_requests("ZILLOW/REGIONS") == [
        {"region_id": "10221", "qopts.per_page": "100"}
    ]
    assert fake.data_requests("ZILLOW/DATA") == [
        {
            "indicator_id": "ZALL",
            "region_id": "10221",
            "qopts.columns": "region_id,date,value",
            "qopts.per_page": "10000",
        }
    ]
    assert data["indicator"]["indicator_id"] == "ZALL"
    assert [c["name"] for c in data["columns"]] == ["date", "region_id", "value"]
    assert data["rows"] == [
        ["2025-06-30", "10221", 529003.58],
        ["2025-05-31", "10221", 528003.46],
        ["2025-04-30", "10221", 527003.33],
    ]
    assert data["row_count"] == 3 and data["has_more"] is True
    assert data["request"] == {
        "indicator_id": "ZALL",
        "region_id": "10221",
        "sort": "date desc",
    }
    assert data["series"] == [
        {
            "region_id": "10221",
            "region_type": "city",
            "region": "Austin, TX",
            "rows": 30,
            "available_from": "2023-01-31",
            "available_to": "2025-06-30",
            "latest_date": "2025-06-30",
            "latest_value": 529003.58,
        }
    ]


@pytest.mark.parametrize("indicator", ["zall", "ZHVI all homes ($)", "zhvi ALL homes"])
async def test_get_data_takes_an_indicator_id_or_exact_name(
    fake: FakeNasdaq, make_client: ClientFactory, indicator: str
) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(
            client, "ndl_get_zillow_data", indicator=indicator, regions=["9"], limit=1
        )
    assert data["indicator"]["indicator_id"] == "ZALL"


async def test_get_data_filters_dates_locally_and_keeps_region_order(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(
            client,
            "ndl_get_zillow_data",
            indicator="ZALL",
            regions="9,10221,102001",
            start_date="2024-11-01",
            end_date="2025-01-31",
        )
        outside = await _call(
            client,
            "ndl_get_zillow_data",
            indicator="ZALL",
            regions="9",
            end_date="2000-12-31",
        )
    sent = fake.data_requests("ZILLOW/DATA")[0]
    assert sent["region_id"] == "9,10221,102001"
    assert not any(k.startswith("date") for k in sent)
    assert [r[:2] for r in data["rows"][:3]] == [
        ["2025-01-31", "9"],
        ["2025-01-31", "10221"],
        ["2025-01-31", "102001"],
    ]
    assert {r[0] for r in data["rows"]} == {"2024-11-30", "2024-12-31", "2025-01-31"}
    assert data["row_count"] == 9 and data["has_more"] is False
    assert [s["region"] for s in data["series"]] == [
        "California",
        "Austin, TX",
        "United States",
    ]
    assert outside["rows"] == [] and outside["notes"]
    assert outside["series"][0]["available_from"] == "2024-01-31"


async def test_get_data_notes_a_region_type_without_coverage(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _zillow(fake)
    async with make_client() as client:
        data = await _call(client, "ndl_get_zillow_data", indicator="ISAM", regions="9")
    assert data["rows"] == [] and data["series"][0]["rows"] == 0
    assert any("covers only metro" in n for n in data["notes"])


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"regions": "Austin, TX"}, ["'Austin'", "ndl_search_zillow_regions"]),
        ({"regions": ["zip:78701"]}, ["'zip:78701'", "ndl_search_zillow_regions"]),
        ({"regions": "999999"}, ["Unknown Zillow region_id(s): 999999"]),
        (
            {"indicator": "home value"},
            ["ZALL (ZHVI all homes ($))", "ZATT", "ndl_search_zillow_indicators"],
        ),
        ({"indicator": "mortgage rates"}, ["not a Zillow indicator id or name"]),
        ({"region_type": "metro"}, ["10221 is a city"]),
        ({"start_date": "2025-01-01", "end_date": "2024-01-01"}, ["after end date"]),
        ({"regions": [str(i) for i in range(1, 12)]}, ["limit is 10"]),
    ],
)
async def test_get_data_rejects_bad_input(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    args: dict[str, Any],
    expected: list[str],
) -> None:
    _zillow(fake)
    async with make_client() as client:
        text = error_text(
            await client.call_tool(
                "ndl_get_zillow_data",
                {"indicator": "ZALL", "regions": "10221", **args},
            )
        )
    assert "[INVALID_REQUEST]" in text
    for part in expected:
        assert part in text
    assert fake.data_requests("ZILLOW/DATA") == []


# --------------------------------------------------------- tables, prompt


async def test_tools_declare_their_tables() -> None:
    server = create_server(Settings(api_key=None))
    async with Client(server) as client:
        data = await _call(client, "ndl_search_tables", query="ZILLOW/DATA", limit=3)
    entry = next(r for r in data["results"] if r["code"] == "ZILLOW/DATA")
    assert entry["tools"] == ["ndl_get_zillow_data"]


async def test_housing_prompt() -> None:
    server = create_server(Settings(api_key=None))
    async with Client(server) as client:
        result = await client.get_prompt(
            "zillow_housing_snapshot", {"place": "Austin, TX"}
        )
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert "Austin, TX" in text and "ndl_search_zillow_regions" in text
