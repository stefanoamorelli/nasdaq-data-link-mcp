from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.tools import world_bank
from nasdaq_data_link_mcp_os.tools.world_bank import country_index
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

# Names as in WB/METADATA; descriptions shortened.
META_ROWS = [
    ["TG.VAL.TOTL.GD.ZS", "Merchandise trade (% of GDP)", "Exports and imports."],
    ["NY.GDP.PCAP.CD", "GDP per capita (current US$)", "GDP divided by population."],
    ["NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)", "Annual growth rate of GDP."],
    [
        "NY.GDP.MKTP.CD",
        "GDP (current US$)",
        "Gross domestic product is the total income earned through production. "
        "This indicator is expressed in current US dollars.",
    ],
    ["NY.GDP.MKTP.CN", "GDP (current LCU)", "GDP in current local currency."],
    ["SP.POP.TOTL", "Population, total", "Total population counts all residents."],
    ["SI.POV.GINI", "Gini index", "Measures income inequality."],
    ["FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)", "Annual change."],
    ["NY.GDP.DEFL.KD.ZG", "Inflation, GDP deflator (annual %)", "Price change."],
    ["per_si_allsi.cov_pop_tot", "Coverage of social insurance (% of pop.)", "x"],
]
GDP = {"ITA": 2.0e12, "GBR": 3.0e12, "UKR": 1.5e11, "WLD": 1.0e14, "KOR": 1.7e12}
POP = {"ITA": 5.9e7, "GBR": 6.8e7, "UKR": 3.7e7, "WLD": 8.0e9, "KOR": 5.1e7}
NAMES = {"ITA": "Italy", "GBR": "United Kingdom", "UKR": "Ukraine", "WLD": "World"}
NAMES["KOR"] = "Korea, Rep."


def _data_rows() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for year in range(2019, 2024):
        for code in GDP:
            rows.append(["NY.GDP.MKTP.CD", code, NAMES[code], year, GDP[code] + year])
            rows.append(["SP.POP.TOTL", code, NAMES[code], year, POP[code] + year])
    for year in range(2015, 2022):
        rows.append(["SI.POV.GINI", "ITA", "Italy", year, 34.0 + year % 3])
    rows.append(["per_si_allsi.cov_pop_tot", "ZWE", "Zimbabwe", 2019, 4.8])
    # Nasdaq returns rows unsorted: interleave so no column is in order.
    return rows[1::3] + rows[::-3] + rows[2::3]


@pytest.fixture
def wb(fake: FakeNasdaq) -> FakeNasdaq:
    fake.add_table(
        "WB/METADATA",
        columns=[("series_id", "text"), ("name", "text"), ("description", "text")],
        filters=["series_id"],
        primary_key=["series_id"],
        rows=[list(r) for r in META_ROWS],
        name="World Bank Metadata",
        refreshed_at="2026-06-23T01:14:14.000Z",
    )
    fake.add_table(
        "WB/DATA",
        columns=[
            ("series_id", "text"),
            ("country_code", "text"),
            ("country_name", "text"),
            ("year", "Integer"),
            ("value", "double"),
        ],
        filters=["country_code", "series_id"],
        primary_key=["series_id", "country_code", "year"],
        rows=_data_rows(),
        name="World Bank Data",
        refreshed_at="2025-08-23T01:08:11.000Z",
    )
    return fake


async def _search(client: Any, query: str, **extra: Any) -> dict[str, Any]:
    args = {"query": query, **extra}
    return payload(await client.call_tool("ndl_search_world_bank_indicators", args))


async def _data(client: Any, **args: Any) -> Any:
    args = {"indicators": "NY.GDP.MKTP.CD", "countries": "ITA", **args}
    return await client.call_tool("ndl_get_world_bank_data", args)


# ------------------------------------------------------------ search tool


async def test_search_ranks_names_then_definitions(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        gdp = await _search(client, "GDP")
        per_capita = await _search(client, "gdp per capita", limit=1)
        inflation = await _search(client, "inflation")
        exact = await _search(client, "si.pov.gini")
        prefix = await _search(client, "NY.GDP.MKTP")
        nothing = await _search(client, "zebra crossing")
    ids = [r["series_id"] for r in gdp["results"]]
    assert ids[:2] == ["NY.GDP.MKTP.CD", "NY.GDP.MKTP.KD.ZG"]  # headline series
    assert ids.index("TG.VAL.TOTL.GD.ZS") > ids.index("NY.GDP.MKTP.CN")  # unit word
    assert gdp["results"][0]["description"] == (
        "Gross domestic product is the total income earned through production."
    )
    assert gdp["indicators_searched"] == len(META_ROWS)
    assert [r["series_id"] for r in per_capita["results"]] == ["NY.GDP.PCAP.CD"]
    assert inflation["results"][0]["series_id"] == "FP.CPI.TOTL.ZG"
    assert exact["results"][0]["series_id"] == "SI.POV.GINI"
    assert {r["series_id"] for r in prefix["results"][:3]} == {
        "NY.GDP.MKTP.CD",
        "NY.GDP.MKTP.CN",
        "NY.GDP.MKTP.KD.ZG",
    }
    assert nothing["results"] == [] and nothing["notes"]
    # WB/METADATA is downloaded once, with explicit columns, then reused.
    requests = wb.data_requests("WB/METADATA")
    assert len(requests) == 1
    assert requests[0]["qopts.columns"] == "series_id,name,description"
    assert requests[0]["qopts.per_page"] == "10000"


async def test_search_cache_expires_after_a_day(
    wb: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_000.0]
    monkeypatch.setattr(world_bank, "_clock", lambda: now[0])
    async with make_client() as client:
        await _search(client, "population")
        await _search(client, "population")
        assert len(wb.data_requests("WB/METADATA")) == 1
        now[0] += world_bank.METADATA_TTL_SECONDS + 1
        await _search(client, "population")
    assert len(wb.data_requests("WB/METADATA")) == 2


async def test_search_does_not_cache_an_empty_indicator_list(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    wb.tables["WB/METADATA"].rows = []
    async with make_client() as client:
        empty = await client.call_tool(
            "ndl_search_world_bank_indicators", {"query": "x"}
        )
        wb.tables["WB/METADATA"].rows = [list(r) for r in META_ROWS]
        found = await _search(client, "gdp")
    assert "[UPSTREAM]" in error_text(empty)
    assert found["results"][0]["series_id"] == "NY.GDP.MKTP.CD"
    assert len(wb.data_requests("WB/METADATA")) == 2


# -------------------------------------------------------------- data tool


async def test_get_data_one_request_sorted_with_names(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        data = payload(
            await _data(
                client,
                indicators=["NY.GDP.MKTP.CD", "sp.pop.totl"],
                countries=["ITA", "UK", "World"],
                start_date="2022",
            )
        )
    (sent,) = wb.data_requests("WB/DATA")
    assert sent["series_id"] == "NY.GDP.MKTP.CD,SP.POP.TOTL"
    assert sent["country_code"] == "ITA,GBR,WLD"  # UK is GBR, never UKR
    assert not any(k.startswith("year") for k in sent)
    assert sent["qopts.columns"] == "series_id,country_code,country_name,year,value"
    assert [c["name"] for c in data["columns"]] == list(world_bank.DATA_COLUMNS)
    assert [(r[3], r[0], r[1]) for r in data["rows"]] == [
        (year, sid, code)
        for year in (2023, 2022)
        for sid in ("NY.GDP.MKTP.CD", "SP.POP.TOTL")
        for code in ("ITA", "GBR", "WLD")
    ]
    assert data["rows"][0] == ["NY.GDP.MKTP.CD", "ITA", "Italy", 2023, 2.0e12 + 2023]
    assert data["row_count"] == 12 and data["has_more"] is False
    assert data["indicators"] == [
        {"series_id": "NY.GDP.MKTP.CD", "name": "GDP (current US$)"},
        {"series_id": "SP.POP.TOTL", "name": "Population, total"},
    ]
    assert data["countries"][1] == {"given": "UK", "code": "GBR", "name": NAMES["GBR"]}
    assert data["access"] == "free"
    assert data["request"]["sort"] == world_bank.SORT_ORDER
    assert data["request"]["start_date"] == "2022"
    assert data["refreshed_at"].startswith("2025-08-23")
    assert any("cannot be filtered by year" in n for n in data["notes"])
    assert data["coverage"][-1] == {
        "series_id": "SP.POP.TOTL",
        "country_code": "WLD",
        "first_year": 2019,
        "last_year": 2023,
        "years": 5,
    }
    # Names came from one small filtered read, not the full download.
    assert wb.data_requests("WB/METADATA") == [
        {
            "series_id": "NY.GDP.MKTP.CD,sp.pop.totl",
            "qopts.columns": "series_id,name",
            "qopts.per_page": "100",
        }
    ]


async def test_get_data_default_returns_most_recent_rows(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    args = {"indicators": "NY.GDP.MKTP.CD,SP.POP.TOTL", "limit": 3}
    async with make_client() as client:
        data = payload(await _data(client, countries=["Korea, Rep.", "IT"], **args))
    assert wb.data_requests("WB/DATA")[0]["country_code"] == "KOR,ITA"
    assert [(r[3], r[0], r[1]) for r in data["rows"]] == [
        (2023, "NY.GDP.MKTP.CD", "KOR"),
        (2023, "NY.GDP.MKTP.CD", "ITA"),
        (2023, "SP.POP.TOTL", "KOR"),
    ]
    assert data["has_more"] is True and data["row_count"] == 3
    assert not any("cannot be filtered by year" in n for n in data["notes"])
    assert "start_date" not in data["request"]


async def test_get_data_reports_missing_pairs_and_late_years(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        data = payload(
            await _data(
                client,
                indicators="SI.POV.GINI",
                countries="ITA,WLD",
                start_date="2020-12-31",
                end_date="2030-01-01",
            )
        )
    assert [r[3] for r in data["rows"]] == [2021, 2020]
    notes = " ".join(data["notes"])
    assert "No values in WB/DATA for SI.POV.GINI for WLD." in notes
    assert "latest year with data for this request is 2021" in notes
    assert [(c["country_code"], c["years"]) for c in data["coverage"]] == [("ITA", 7)]


async def test_get_data_uses_cached_names_and_lowercase_ids(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        await _search(client, "social")
        data = payload(
            await _data(client, indicators="PER_SI_ALLSI.COV_POP_TOT", countries="ZW")
        )
    assert len(wb.data_requests("WB/METADATA")) == 1  # the full download only
    assert wb.data_requests("WB/DATA")[0]["series_id"] == "per_si_allsi.cov_pop_tot"
    assert data["rows"] == [["per_si_allsi.cov_pop_tot", "ZWE", "Zimbabwe", 2019, 4.8]]


async def test_get_data_rejects_keywords_and_unknown_ids(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        keyword = error_text(await _data(client, indicators="inflation"))
        typo = error_text(
            await _data(client, indicators=["SP.POP.TOTL", "NY.GDP.MKTP"])
        )
        nothing = error_text(await _data(client, indicators="zebra crossing"))
    assert (
        "'inflation' is not a WB/METADATA series_id; series containing it: " in keyword
    )
    assert "FP.CPI.TOTL.ZG (Inflation, consumer prices (annual %))" in keyword
    assert "'NY.GDP.MKTP' is not" in typo and "NY.GDP.MKTP.CD (GDP" in typo
    assert "'SP.POP.TOTL'" not in typo
    for text in (keyword, typo, nothing):
        assert "[INVALID_REQUEST]" in text and world_bank.SEARCH_TOOL in text
    assert wb.data_requests("WB/DATA") == []


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"countries": "Itlay"}, "Unknown country 'Itlay'. Countries are ISO3"),
        ({"countries": "Trinidad"}, "containing it: TTO (Trinidad and Tobago)."),
        ({"countries": "Korea"}, "KOR (Korea, Rep.), PRK (Korea, Dem. People's Rep.)"),
        ({"countries": [f"C{i}" for i in range(31)]}, "31 countries requested"),
        ({"countries": " , "}, "`countries` is empty"),
        ({"indicators": [f"A.B{i}" for i in range(11)]}, "the maximum is 10"),
        ({"start_date": "2020", "end_date": "2010-06-30"}, "after end"),
        ({"start_date": "2021-02-30"}, "start_date='2021-02-30' is not a real date"),
    ],
)
async def test_get_data_validation(
    wb: FakeNasdaq, make_client: ClientFactory, args: dict[str, Any], expected: str
) -> None:
    async with make_client() as client:
        text = error_text(await _data(client, **args))
    assert "[INVALID_REQUEST]" in text and expected in text
    assert wb.requests == []


async def test_get_data_years_from_dates(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    args = {"indicators": "SI.POV.GINI", "start_date": "1900", "end_date": "2016-01-31"}
    async with make_client() as client:
        old = payload(await _data(client, **args))
        renamed = await _data(client, start_year=2015)
    assert [r[3] for r in old["rows"]] == [2016, 2015]  # end_date keeps all of 2016
    assert old["request"]["end_date"] == "2016-01-31"
    assert renamed.is_error and "start_year" in error_text(renamed)


async def test_get_data_points_to_imf_for_later_years(
    wb: FakeNasdaq, make_client: ClientFactory
) -> None:
    args = {"indicators": "SP.POP.TOTL", "start_date": "2024"}
    async with make_client() as client:
        later = payload(await _data(client, **args))
    async with make_client(toolsets=("world_bank",)) as client:
        alone = payload(await _data(client, **args))
    assert later["rows"] == [] and later["has_more"] is False
    notes = " ".join(later["notes"])
    assert "fall in 2024 or later" in notes
    assert "latest year with data for this request is 2023" in notes
    assert "ndl_get_imf_weo_data" in notes
    assert not any("ndl_get_imf_weo_data" in n for n in alone["notes"])


@pytest.mark.parametrize(
    ("page_size", "requests", "row_count", "has_more"),
    [(8, 3, 20, False), (5, world_bank.MAX_PAGES, 15, True)],
)
async def test_get_data_follows_cursor_pages(
    wb: FakeNasdaq,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    page_size: int,
    requests: int,
    row_count: int,
    has_more: bool,
) -> None:
    monkeypatch.setattr(world_bank, "MAX_PAGE_SIZE", page_size)
    args = {"indicators": "NY.GDP.MKTP.CD,SP.POP.TOTL", "countries": "ITA,GBR"}
    async with make_client() as client:
        data = payload(await _data(client, **args))
    sent = wb.data_requests("WB/DATA")
    assert len(sent) == requests  # 20 rows in pages of page_size
    assert "qopts.cursor_id" not in sent[0] and sent[1]["qopts.cursor_id"]
    assert data["row_count"] == row_count and data["has_more"] is has_more
    assert "next_cursor" not in data  # rows were re-sorted, no resumable cursor
    assert data["rows"][0][:4] == ["NY.GDP.MKTP.CD", "ITA", "Italy", 2023]


# ------------------------------------------------------- country resolution


@pytest.mark.parametrize(
    ("given", "code"),
    [
        ("ITA", "ITA"),
        ("ita", "ITA"),
        ("IT", "ITA"),
        ("Italy", "ITA"),
        ("UK", "GBR"),
        ("U.K.", "GBR"),
        ("US", "USA"),
        ("U.S.", "USA"),
        ("South Korea", "KOR"),
        ("korea, rep", "KOR"),
        ("Turkey", "TUR"),
        ("Türkiye", "TUR"),
        ("Ivory Coast", "CIV"),
        ("Côte d’Ivoire", "CIV"),
        ("Russia", "RUS"),
        ("World", "WLD"),
        ("Euro area", "EMU"),
        ("EU", "EUU"),
        ("Low & middle income", "LMY"),
        ("low and middle income", "LMY"),
        ("XKX", "XKX"),
    ],
)
def test_country_resolution(given: str, code: str) -> None:
    assert country_index().resolve(given).code == code


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ("", "empty"),
        ("Congo", "COD (Congo, Dem. Rep.), COG (Congo, Rep.)"),
        ("Virgin Islands", "VGB (British Virgin Islands), VIR (Virgin Islands (U.S.))"),
        ("developed", "Unknown country 'developed'. Names or codes containing it: LDC"),
        ("high income countries", "Unknown country"),
    ],
)
def test_country_errors(given: str, message: str) -> None:
    with pytest.raises(InvalidRequestError) as info:
        country_index().resolve(given)
    assert message in str(info.value)


def test_bundled_codes_names_and_aliases_resolve_to_their_economy() -> None:
    files = resources.files("nasdaq_data_link_mcp_os").joinpath("data")
    raw = {
        name: json.loads(files.joinpath(name).read_text(encoding="utf-8"))
        for name in ("wb_economies.json", "world_bank_aliases.json")
    }
    assert all(data["source"] and data["license"] for data in raw.values())
    index = country_index()
    assert len(index.economies) == 265
    for code, item in raw["wb_economies.json"]["economies"].items():
        for text in (code, item.get("iso2"), item["name"]):
            assert text is None or index.resolve(text).code == code, text
    for alias, code in raw["world_bank_aliases.json"]["aliases"].items():
        assert index.resolve(alias).code == code, alias


def test_country_values_split_commas_unless_one_name() -> None:
    index = country_index()
    assert index.values("ITA, FRA,ita") == ["ITA", "FRA", "ita"]
    assert index.values("Korea, Rep.") == ["Korea, Rep."]
    assert index.values(["Bahamas, The", "DEU,FRA"]) == ["Bahamas, The", "DEU", "FRA"]


# ------------------------------------------------------------------ prompt


async def test_country_profile_prompt(make_client: ClientFactory) -> None:
    async with make_client() as client:
        uk = await client.get_prompt("country_economic_profile", {"country": "UK"})
        world = await client.get_prompt("country_economic_profile", {"country": "WLD"})
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("country_economic_profile", {"country": "Korea"})
    text = uk.messages[0].content.text  # type: ignore[union-attr]
    assert "United Kingdom (GBR)" in text and "['GBR', 'WLD']" in text
    assert "NY.GDP.MKTP.CD" in text and "start_date='2014'" in text
    assert "['WLD']" in world.messages[0].content.text  # type: ignore[union-attr]
    assert caught.value.code == INVALID_PARAMS
    assert "KOR (Korea, Rep.)" in caught.value.message


async def test_tools_are_registered_in_world_bank_toolset(
    make_client: ClientFactory,
) -> None:
    async with make_client(toolsets=("world_bank",)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        found = payload(
            await client.call_tool("ndl_search_tables", {"query": "WB", "vendor": "WB"})
        )
    for name in ("ndl_search_world_bank_indicators", "ndl_get_world_bank_data"):
        assert (tools[name].meta or {}).get("toolset") == "world_bank"
        assert tools[name].output_schema
    by_code = {r["code"]: r.get("tools") for r in found["results"]}
    assert by_code["WB/DATA"] == ["ndl_get_world_bank_data"]
    assert by_code["WB/METADATA"] == [
        "ndl_search_world_bank_indicators",
        "ndl_get_world_bank_data",
    ]
