from __future__ import annotations

from typing import Any

import pytest

from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.tools import table_tools
from nasdaq_data_link_mcp_os.tools.macro import (
    COUNTRY_HEADLINE,
    GROUP_HEADLINE,
    WORLD_HEADLINE,
    bonds,
    weo,
)
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

# Metadata copied from the live QDL/ODA and QDL/ML tables.
ODA_REFRESHED = "2023-10-31T19:36:43.000Z"
ML_REFRESHED = "2025-03-02T16:01:25.000Z"


def _oda(fake: FakeNasdaq) -> None:
    usa = {2019: 21380.95, 2020: 21060.45, 2021: 23315.075, 2022: 25464.475}
    usa.update({2023: 26854.599, 2028: 32349.658})
    rows: list[list[Any]] = [["USA_NGDPD", f"{y}-12-31", v] for y, v in usa.items()]
    rows += [
        ["DEU_NGDP_RPCH", "2019-12-31", 1.1],
        ["DEU_NGDP_RPCH", "2020-12-31", -3.7],
        ["DEU_NGDP_RPCH", "2021-12-31", 2.6],
        ["FRA_NGDP_RPCH", "2021-12-31", 6.4],
        ["FRA_NGDP_RPCH", "2020-12-31", -7.5],
        ["WORLD_POILBRE", "2022-12-31", 98.996],
        ["WORLD_POILBRE", "2023-12-31", 75.358],
        ["WORLD_LUR", "2022-12-31", None],
        ["FAD_G7_LUR", "2022-12-31", 4.3],
        ["FAD_G7_NGDP_RPCH", "2022-12-31", 2.1],
    ]
    fake.add_table(
        "QDL/ODA",
        columns=[("indicator", "text"), ("date", "Date"), ("value", "double")],
        filters=["date", "indicator"],
        primary_key=["indicator", "date"],
        rows=rows,
        name="IMF Cross Country Macroeconomic Statistics",
        refreshed_at=ODA_REFRESHED,
    )


def _ml(fake: FakeNasdaq) -> None:
    rows: list[list[Any]] = []
    for i, day in enumerate(["2025-02-24", "2025-02-25", "2025-02-26", "2025-02-27"]):
        rows.append(["BAMLC0A4CBBBEY", day, 5.3 + i / 100])
        rows.append(["BAMLH0A0HYM2", day, 2.8 + i / 100])
        rows.append(["BAMLHYH0A3CMTRIV", day, 645.0 + i])
    rows.append(["BAMLC0A4CBBBEY", "2024-01-02", 5.5])
    fake.add_table(
        "QDL/ML",
        columns=[("series_code", "text"), ("date", "Date"), ("rate", "double")],
        filters=["date", "series_code"],
        primary_key=["series_code", "date"],
        rows=rows,
        name="Corporate Bond Yield Rates",
        refreshed_at=ML_REFRESHED,
    )


# ------------------------------------------------------------- resolution


def test_bundled_code_lists() -> None:
    w, b = weo(), bonds()
    assert len(w.economies) == 196 and len(w.groups) == 13
    assert set(COUNTRY_HEADLINE + GROUP_HEADLINE + WORLD_HEADLINE) <= set(w.concepts)
    assert len(b.series) == 27
    assert all(set(s) == {"label", "unit", "first_date"} for s in b.series.values())


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("usa", "USA"),
        ("DE", "DEU"),
        ("Germany", "DEU"),
        ("Korea, Rep.", "KOR"),
        ("Türkiye", "TUR"),
        ("UK", "GBR"),
        ("XKX", "UVK"),
        ("Taiwan", "TWN"),
        ("fad_g7", "FAD_G7"),
        ("G7", "FAD_G7"),
        ("euro area", "EUROAREA"),
        ("WLD", "WORLD"),
        ("SSA", "SSA"),
    ],
)
def test_area_codes_and_exact_names_resolve(value: str, code: str) -> None:
    assert weo().resolve_area(value) == code


@pytest.mark.parametrize(
    ("value", "candidates"),
    [
        ("Congo", ["COD", "COG"]),
        ("Europe", ["EU", "EDE"]),
        ("Hong Kong SAR", ["HKG"]),
        ("PRK", []),
    ],
)
def test_unknown_areas_list_substring_candidates(
    value: str, candidates: list[str]
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        weo().resolve_area(value)
    message = str(raised.value)
    assert all(f"{c} (" in message for c in candidates)
    assert "FAD_G7 (G7 economies)" in message


@pytest.mark.parametrize(
    ("value", "codes"),
    [
        ("Korea, Rep.", ["KOR"]),
        ("US, DE", ["USA", "DEU"]),
        (["Korea, Rep.", "Germany"], ["KOR", "DEU"]),
    ],
)
def test_country_strings_split_on_commas_unless_one_name(
    value: str | list[str], codes: list[str]
) -> None:
    assert weo().resolve_areas(value) == codes


@pytest.mark.parametrize(
    ("code", "parts"),
    [
        ("usa_ngdpd", ("USA", "NGDPD")),
        ("FAD_G7_NGDP_RPCH", ("FAD_G7", "NGDP_RPCH")),
        ("EU_PCPIPCH", ("EU", "PCPIPCH")),
        ("XYZ_NGDPD", None),
        ("NGDPD", None),
    ],
)
def test_series_codes_split_into_area_and_concept(
    code: str, parts: tuple[str, str] | None
) -> None:
    if parts:
        assert weo().split_series(code) == parts
    else:
        with pytest.raises(InvalidRequestError, match="<economy>_<concept>"):
            weo().split_series(code)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("bamlh0a0hym2", None),
        ("BBB", "BAMLC0A4CBBBEY (US corporates rated BBB: effective yield)"),
        ("bitcoin", "BAMLEMRECRPIEMEATRIV"),
    ],
)
def test_bond_series_take_codes_only(value: str, message: str | None) -> None:
    if message is None:
        assert bonds().resolve(value) == ["BAMLH0A0HYM2"]
    else:
        with pytest.raises(InvalidRequestError, match="Unknown QDL/ML series") as e:
            bonds().resolve(value)
        assert message in str(e.value)


# ----------------------------------------------------------- WEO tool


async def test_weo_default_stops_at_the_last_actual_year(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    args = {"countries": "United States", "indicators": "ngdpd", "limit": 3}
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    sent = fake.data_requests("QDL/ODA")[-1]
    assert sent["indicator"] == "USA_NGDPD"
    assert sent["qopts.per_page"] == "60"
    assert sent["date.lte"] == "2022-12-31"
    assert data["columns"][-1]["name"] == "projected"
    assert [r[1] for r in data["rows"]] == ["2022-12-31", "2021-12-31", "2020-12-31"]
    assert [r[3] for r in data["rows"]] == [False, False, False]
    assert data["has_more"]
    assert data["series"] == [
        {
            "indicator": "USA_NGDPD",
            "area": "USA",
            "area_name": "United States",
            "concept": "NGDPD",
            "label": "Nominal GDP in US dollars",
            "unit": "USD bn",
        }
    ]
    assert data["notes"][0].startswith("IMF WEO April 2023 edition")
    assert any("Projections excluded" in n for n in data["notes"])


async def test_weo_projections(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _oda(fake)
    code = {"series_codes": "USA_NGDPD"}
    async with make_client() as client:

        async def call(**args: Any) -> dict[str, Any]:
            result = await client.call_tool("ndl_get_imf_weo_data", {**code, **args})
            return payload(result)

        included = await call(include_projections=True)
        assert "date.lte" not in fake.data_requests("QDL/ODA")[-1]
        ranged = await call(start_date="2022", end_date="2023")
        future = await call(start_date="2025")
        excluded = await call(
            start_date="2022", end_date="2028", include_projections=False
        )
        assert fake.data_requests("QDL/ODA")[-1]["date.lte"] == "2022-12-31"
        reads = len(fake.data_requests("QDL/ODA"))
        impossible = error_text(
            await client.call_tool(
                "ndl_get_imf_weo_data",
                {**code, "start_date": "2025", "include_projections": False},
            )
        )
    flags = [(r[1][:4], r[3]) for r in included["rows"][:3]]
    assert flags == [("2028", True), ("2023", True), ("2022", False)]
    assert [(r[1][:4], r[3]) for r in ranged["rows"]] == [
        ("2023", True),
        ("2022", False),
    ]
    assert [r[1] for r in future["rows"]] == ["2028-12-31"]
    assert any("start_date is after 2022" in n for n in future["notes"])
    assert [r[1][:4] for r in excluded["rows"]] == ["2022"]
    assert "[INVALID_REQUEST]" in impossible and "2022" in impossible
    assert len(fake.data_requests("QDL/ODA")) == reads


async def test_weo_rows_are_newest_first_then_in_request_order(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    args = {
        "countries": ["Germany", "FR"],
        "indicators": "NGDP_RPCH",
        "start_date": "2020",
        "end_date": "2021-12-31",
    }
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    sent = fake.data_requests("QDL/ODA")[-1]
    assert sent["indicator"] == "DEU_NGDP_RPCH,FRA_NGDP_RPCH"
    assert (sent["date.gte"], sent["date.lte"]) == ("2020-01-01", "2021-12-31")
    assert [r[:2] for r in data["rows"]] == [
        ["DEU_NGDP_RPCH", "2021-12-31"],
        ["FRA_NGDP_RPCH", "2021-12-31"],
        ["DEU_NGDP_RPCH", "2020-12-31"],
        ["FRA_NGDP_RPCH", "2020-12-31"],
    ]


async def test_weo_world_only_concepts_are_read_under_world(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    args = {"countries": "Japan", "indicators": "POILBRE"}
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    assert data["request"]["indicator"] == "WORLD_POILBRE"
    assert data["rows"] == [["WORLD_POILBRE", "2022-12-31", 98.996, False]]
    assert data["series"][0]["unit"] == "USD per barrel"
    assert any("only under WORLD" in n for n in data["notes"])


async def test_weo_unknown_codes_pass_through_and_gaps_are_named(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    args = {"countries": ["G7", "world"], "indicators": ["LUR", "inflation"]}
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_get_imf_weo_data", args))
    assert data["request"]["indicator"] == (
        "FAD_G7_LUR,FAD_G7_INFLATION,WORLD_LUR,WORLD_INFLATION"
    )
    assert any("No values" in n and "WORLD_LUR" in n for n in data["notes"])
    gap = next(n for n in data["notes"] if n.startswith("No rows"))
    assert "FAD_G7_INFLATION, WORLD_INFLATION" in gap and "PCPIPCH" in gap
    assert {
        "indicator": "WORLD_INFLATION",
        "area": "WORLD",
        "area_name": "World",
        "concept": "INFLATION",
    } in data["series"]


async def test_weo_defaults_and_series_codes(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    async with make_client() as client:
        world = payload(await client.call_tool("ndl_get_imf_weo_data", {}))
        group = payload(
            await client.call_tool(
                "ndl_get_imf_weo_data", {"series_codes": "fad_g7_ngdp_rpch"}
            )
        )
    assert world["request"]["indicator"].split(",") == [
        f"WORLD_{c}" for c in WORLD_HEADLINE
    ]
    assert any("headline" in n for n in world["notes"])
    assert group["rows"] == [["FAD_G7_NGDP_RPCH", "2022-12-31", 2.1, False]]
    assert group["series"][0]["area_name"] == "G7 economies"


async def test_weo_edition_note_follows_the_live_refresh_date(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _oda(fake)
    fake.tables["QDL/ODA"].refreshed_at = "2099-01-01T00:00:00.000Z"
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_get_imf_weo_data", {"series_codes": "USA_NGDPD"}
            )
        )
    assert data["notes"][0].startswith("Nasdaq reloaded QDL/ODA on 2099-01-01")


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"countries": "Narnia"}, "not a QDL/ODA economy or group"),
        ({"series_codes": "XYZ_NGDPD"}, "<economy>_<concept>"),
        ({"indicators": "real gdp growth"}, "NGDP_RPCH (Real GDP growth)"),
        ({"countries": ["USA", "DEU", "FRA", "ITA"]}, "limit is 30"),
        ({"start_date": "2022", "end_date": "2020"}, "is after end"),
        ({"country": "USA"}, "country"),
    ],
)
async def test_weo_invalid_requests_spend_no_data_calls(
    fake: FakeNasdaq, make_client: ClientFactory, args: dict[str, Any], expected: str
) -> None:
    _oda(fake)
    async with make_client() as client:
        text = error_text(await client.call_tool("ndl_get_imf_weo_data", args))
    assert expected in text
    assert fake.data_requests("QDL/ODA") == []


# ---------------------------------------------------------- bond tool


async def test_bond_series_codes(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _ml(fake)
    args = {"series": "bamlc0a4cbbbey", "limit": 2}
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_get_bond_index_yields", args))
    sent = fake.data_requests("QDL/ML")[-1]
    assert sent["series_code"] == "BAMLC0A4CBBBEY"
    assert sent["date.lte"] == "2025-03-02"
    assert "2024-09-01" < sent["date.gte"] < "2025-02-20"
    assert [r[1] for r in data["rows"]] == ["2025-02-27", "2025-02-26"]
    assert data["series"] == [
        {
            "series_code": "BAMLC0A4CBBBEY",
            "label": "US corporates rated BBB: effective yield",
            "unit": "percent",
            "first_date": "1996-12-31",
        }
    ]
    assert any("2025-02-27" in n and "no longer updated" in n for n in data["notes"])


async def test_bond_snapshot_range_and_empty_range(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _ml(fake)
    async with make_client() as client:
        snap = payload(await client.call_tool("ndl_get_bond_index_yields", {}))
        snap_sent = fake.data_requests("QDL/ML")[-1]
        late = payload(
            await client.call_tool(
                "ndl_get_bond_index_yields", {"end_date": "2026-01-01"}
            )
        )
        late_sent = fake.data_requests("QDL/ML")[-1]
        ranged = payload(
            await client.call_tool(
                "ndl_get_bond_index_yields",
                {"start_date": "2025-02-26", "end_date": "2025-02-27"},
            )
        )
        old = payload(
            await client.call_tool(
                "ndl_get_bond_index_yields",
                {"series": ["BAMLC0A4CBBBEY"], "end_date": "2024-01-31"},
            )
        )
        empty = payload(
            await client.call_tool(
                "ndl_get_bond_index_yields",
                {"series": "BAMLH0A0HYM2", "start_date": "2026-01-01"},
            )
        )
    assert "series_code" not in snap_sent and snap_sent["date.gte"] == "2025-02-16"
    expected = ["BAMLC0A4CBBBEY", "BAMLH0A0HYM2", "BAMLHYH0A3CMTRIV"]
    for data in (snap, late):
        assert [r[0] for r in data["rows"]] == expected
        assert {r[1] for r in data["rows"]} == {"2025-02-27"}
        assert [s["series_code"] for s in data["series"]] == expected
    assert (late_sent["date.gte"], late_sent["date.lte"]) == (
        "2025-02-16",
        "2026-01-01",
    )
    assert any("on or before 2026-01-01" in n for n in late["notes"])
    assert ranged["row_count"] == 6
    assert old["rows"] == [["BAMLC0A4CBBBEY", "2024-01-02", 5.5]]
    assert empty["rows"] == []
    assert any("No observations" in n for n in empty["notes"])


async def test_bond_invalid_requests_spend_no_data_calls(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _ml(fake)
    async with make_client() as client:
        unknown = error_text(
            await client.call_tool("ndl_get_bond_index_yields", {"series": "BBB yield"})
        )
        bad_date = error_text(
            await client.call_tool(
                "ndl_get_bond_index_yields", {"end_date": "2025-02-30"}
            )
        )
    assert "[INVALID_REQUEST]" in unknown and "BAMLC0A0CMEY" in unknown
    assert "[INVALID_REQUEST]" in bad_date
    assert fake.data_requests("QDL/ML") == []


def test_tools_declare_their_tables() -> None:
    assert table_tools(["macro"]) == {
        "QDL/ODA": ["ndl_get_imf_weo_data"],
        "QDL/ML": ["ndl_get_bond_index_yields"],
    }
