"""Offline tests of the carbon removal (Puro.earth CORC) tools.

The fake tables copy the filters and the relevant columns of the live BUWP
metadata (2026-10-03), including their quirks: versioned methodology names and
"CORC100+" in FAFD and SYVW, facility names with commas.
"""

from __future__ import annotations

import pytest

from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio

DATA = "ndl_get_carbon_removal_data"
FACILITIES = "ndl_get_carbon_removal_facilities"
PDF = "https://example.org/biochar.pdf"
RIEDEN = ("Carbon Cycle, 001, Rieden, DE", "511285")
NOKIA = ("Carbofex Nokia 1", "507468")
BRODIE = ("Brodie Biomass", "680422")
GEVO = ("Gevo North Dakota", "353054")
BRECEY = ("A. James - 50370 Brecey", "181856")
CONCEPCION = ("Exomad Green, Concepción", "111111")
RIBERALTA = ("Exomad Green, Riberalta", "222222")


def _text(*names: str) -> list[tuple[str, str]]:
    return [(n, "text") for n in names]


def _fafd(fake: FakeNasdaq) -> None:
    eu, sa, biochar, owner = "Europe", "South America", "Biochar, 2022", "Owner"
    fake.add_table(
        "NDAQ/FAFD",
        columns=_text("facility", "facility_id", "region", "country", "methodology",
                      "durability_category", "facility_owner"),
        filters=["region", "country", "durability_category", "methodology"],
        rows=[
            [*RIEDEN, eu, "Germany", biochar, "CORC100+", "Accend AS"],
            [*GEVO, "North America", "United States of America",
             "Geologically stored carbon, 2021", "CORC1000+", owner],
            [*CONCEPCION, sa, "Bolivia", biochar, "CORC100+", owner],
            [*NOKIA, eu, "Finland", biochar, "CORC100+", owner],
            [*RIBERALTA, sa, "Bolivia", biochar, "CORC100+", owner],
            [*RIEDEN, eu, "Germany", biochar, "CORC", "Accend AS"],
            [*BRODIE, eu, "United Kingdom", biochar, "CORC100+", owner],
            [*BRECEY, eu, "France", "Wooden Building Elements", "CORC", owner],
        ],
    )  # fmt: skip


def _firc(fake: FakeNasdaq) -> None:
    volumes = ["volume_issued_gross_vintage", "volume_issued_net_vintage"]
    fake.add_table(
        "NDAQ/FIRC",
        columns=[
            ("year", "Integer"),
            *_text("facility", "facility_id", "methodology", "durability_category"),
            *[(c, "Integer") for c in [*volumes, "volume_retired_of_vintage"]],
        ],
        filters=["year", "methodology", "durability_category"],
        rows=[
            [2024, *NOKIA, "Biochar", "CORC 100+", 700, 690, 600],
            [2025, *NOKIA, "Biochar", "CORC 100+", 856, 856, 567],
            [2019, *NOKIA, "Biochar", "CORC 100+", 0, 0, 0],
            [2025, *BRODIE, "Biochar", "CORC 100+", 1200, 1200, 300],
            [2025, *GEVO, "Geologically stored carbon", "CORC 1000+", 9, 9, 9],
        ],
    )


def _irbm(fake: FakeNasdaq) -> None:
    shares = ["pct_retired_na", "pct_retired_sa", "pct_issued_sa"]
    fake.add_table(
        "NDAQ/IRBM",
        columns=[
            ("year", "Integer"),
            ("methodology", "text"),
            ("volume_issued_net_vintage", "Integer"),
            ("volume_retired_transaction", "Integer"),
            *[(c, "double") for c in shares],
        ],
        filters=["year", "methodology"],
        rows=[
            [2026, "Soil Amendment", 0, 0, 0.0, 0.0, 0.0],
            [2026, "Geologically stored carbon", 104515, 82613, 0.99, 0.0, 0.0],
            [2026, "Biochar", 188623, 119192, 0.09, 0.81, 0.91],
            [2025, "Biochar", 249000, 90000, 0.5, 0.5, 0.5],
        ],
    )


def _ritm(fake: FakeNasdaq) -> None:
    na, usa = "North America", "United States of America"
    fake.add_table(
        "NDAQ/RITM",
        columns=[
            ("date", "Date"),
            *_text("certificate_id", "methodology", "durability_category"),
            *_text("beneficiary", "region_retirement", "country_retirement"),
            *_text("facility", "facility_id"),
            ("volume_retired_transaction", "Integer"),
        ],
        filters=["date", "methodology", "facility", "durability_category"],
        rows=[
            ["2026-09-03", "C1", "Biochar", "CORC 100+", "Microsoft Corp", na, usa,
             *RIEDEN, 100],
            ["2026-05-08", "C2", "Biochar", "CORC 100+", None, "Europe", "Germany",
             *RIEDEN, 40],
            ["2026-09-20", "C3", "Biochar", "CORC 100+", "Shopify Inc.", na, "Canada",
             *NOKIA, 5],
            ["2026-10-01", "C5", "Biochar", "CORC 100+", "Microsoft Corp", "Europe",
             "Finland", *NOKIA, 300],
        ],
    )  # fmt: skip


def _colt(fake: FakeNasdaq) -> None:
    fake.add_table(
        "NDAQ/COLT",
        columns=[
            *_text("facility", "facility_id"),
            ("date", "Date"),
            *_text("methodology", "certificates_bundle", "transaction_type"),
            ("receiver_name", "text"),
            ("volume", "Integer"),
        ],
        filters=["facility", "facility_id", "methodology", "date", "transaction_type"],
        rows=[
            [*BRODIE, "2025-03-01", "Biochar", "B_1-2000", "Issuance", "Brodie", 2000],
            [*BRODIE, "2026-09-29", "Biochar", "B_1277-1315", "Retirement", "Eco", 39],
            [*BRODIE, "2026-09-30", "Biochar", "B_1136-1151", "Retirement", "Eco", 16],
            [*GEVO, "2026-05-21", "Geologic", "G_1-9", "Retirement", "Net-Zero", 9],
        ],
    )


def _syvw(fake: FakeNasdaq) -> None:
    brodie = (*BRODIE, "Biochar, 2022", "Edition 2022 V3", PDF, "CORC 100+")
    gevo = (*GEVO, "Geologically stored carbon, 2021", None, "https://x.org/g.pdf")
    fake.add_table(
        "NDAQ/SYVW",
        columns=[
            ("date", "Date"),
            *_text("certificates_bundle", "facility", "facility_id", "methodology"),
            *_text("methodology_version", "methodology_documentation_url"),
            *_text("durability_category", "transaction_type", "account_holder_name"),
            ("volume", "Integer"),
        ],
        filters=["date", "certificates_bundle", "facility_id", "facility"],
        rows=[
            ["2026-09-29", "B1", *brodie, "Retirement", "Ecologi Action Ltd", 55],
            ["2026-06-30", "B2", *brodie, "Withdrawal", None, 30],
            ["2026-08-01", "B3", *gevo, "CORC 1000+", "Withdrawal", None, 100],
        ],
    )


def _tran(fake: FakeNasdaq, months: list[str] | None = None) -> None:
    fake.add_table(
        "NDAQ/TRAN",
        columns=[
            *_text("month", "methodology"),
            ("reference_price", "double"),
            ("quarterly_period", "text"),
        ],
        filters=["methodology", "quarterly_period", "month"],
        premium=True,
        forbidden=months is None,
        rows=[[m, "Biochar", 150.0, None] for m in months or []],
    )


@pytest.fixture
def tables(fake: FakeNasdaq) -> FakeNasdaq:
    for add in (_fafd, _firc, _irbm, _ritm, _colt, _syvw, _tran):
        add(fake)
    return fake


def _column(data: dict, name: str) -> list:
    index = [c["name"] for c in data["columns"]].index(name)
    return [row[index] for row in data["rows"]]


async def _call(make_client: ClientFactory, tool: str, **args: object) -> dict:
    async with make_client() as client:
        return payload(await client.call_tool(tool, args))


async def _error(make_client: ClientFactory, tool: str, **args: object) -> str:
    async with make_client() as client:
        return error_text(await client.call_tool(tool, args))


async def test_facilities_filter_locally_across_spellings(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    data = await _call(
        make_client,
        FACILITIES,
        country="U.S.A.",
        methodology="Geologically stored carbon",
        durability_category="CORC 1000+",
    )
    assert (data["table"], data["access"]) == ("NDAQ/FAFD", "free")
    assert _column(data, "facility") == ["Gevo North Dakota"]
    # Comma-containing values cannot be sent as Nasdaq filters: all local.
    assert tables.data_requests("NDAQ/FAFD") == [{"qopts.per_page": "10000"}]
    assert data["request"]["local_filters"]["country"] == "U.S.A."


@pytest.mark.parametrize(
    ("facilities", "ids"),
    [
        ("507468, 680422", ["507468", "680422"]),
        (["Carbofex Nokia 1", "BRODIE BIOMASS"], ["507468", "680422"]),
        ("carbon cycle 001 rieden de", ["511285", "511285"]),
        ("Exomad Green, Concepcion", ["111111"]),
        (["507468, 680422", "Exomad Green, Riberalta"], ["222222", "507468", "680422"]),
    ],
)
async def test_facilities_resolve_ids_and_exact_names(
    tables: FakeNasdaq, make_client: ClientFactory, facilities: object, ids: list
) -> None:
    data = await _call(make_client, FACILITIES, facilities=facilities)
    assert sorted(_column(data, "facility_id")) == ids


@pytest.mark.parametrize(
    ("query", "candidates"),
    [
        ("exomad", ["'Exomad Green, Concepción' (111111)", "Riberalta' (222222)"]),
        ("Accend AS", []),  # owners are not names
        ("999999", []),
    ],
)
async def test_unknown_facility_lists_substring_candidates(
    tables: FakeNasdaq, make_client: ClientFactory, query: str, candidates: list
) -> None:
    text = await _error(make_client, DATA, dataset="transactions", facilities=query)
    assert "[INVALID_REQUEST]" in text
    assert all(c in text for c in candidates)
    assert ("Names containing it" in text) == bool(candidates)
    assert "ndl_get_carbon_removal_facilities lists all 7 facilities" in text
    assert tables.data_requests("NDAQ/COLT") == []


async def test_facilities_country_must_exist_and_rows_sort_by_name(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    unknown = await _error(make_client, FACILITIES, country="Japan")
    none_here = await _call(
        make_client, FACILITIES, country="Finland", methodology="Soil Amendment"
    )
    europe = await _call(make_client, FACILITIES, region="Europe", limit=4)
    assert "[INVALID_REQUEST]" in unknown and "Bolivia, Finland, France" in unknown
    assert none_here["rows"] == []
    # Sorted by name (case and punctuation aside), then durability category.
    assert _column(europe, "facility_id") == ["181856", "680422", "507468", "511285"]
    assert _column(europe, "durability_category")[3] == "CORC"
    assert europe["has_more"] is True


async def test_tables_are_declared_per_tool(make_client: ClientFactory) -> None:
    found = await _call(make_client, "ndl_search_tables", query="NDAQ/RITM")
    (ritm,) = [t for t in found["results"] if t["code"] == "NDAQ/RITM"]
    assert ritm["tools"] == [DATA]


async def test_facility_volumes(tables: FakeNasdaq, make_client: ClientFactory) -> None:
    data = await _call(
        make_client,
        DATA,
        dataset="facility_volumes",
        facilities="507468",
        methodology="Biochar",
        durability_category="CORC 100+",
        start_date="2019",
        end_date="2025-06-30",
    )
    # The directory read skips the metadata request: its columns are constants.
    assert len([r for r in tables.requests if "NDAQ/FAFD" in r.url.path]) == 1
    assert tables.data_requests("NDAQ/FAFD")[0]["qopts.columns"] == (
        "facility_id,facility"
    )
    (sent,) = tables.data_requests("NDAQ/FIRC")
    assert (sent["year.gte"], sent["year.lte"]) == ("2019", "2025")
    assert sent["methodology"] == "Biochar"
    assert sent["durability_category"] == "CORC 100+,CORC100+"
    assert _column(data, "year") == [2025, 2024]
    assert any("no issued or retired volume" in n for n in data["notes"])
    assert any("vintage year" in n for n in data["notes"])
    assert data["request"]["local_filters"] == {"facility_id": ["507468"]}
    assert data["request"]["sort_by"] == "year desc, volume_issued_net_vintage desc"
    assert data["matched_facilities"] == [
        {"query": "507468", "facility_id": "507468", "facility": "Carbofex Nokia 1"}
    ]


async def test_methodology_volumes(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    data = await _call(
        make_client, DATA, dataset="methodology_volumes", start_date="2026-06-30"
    )
    assert tables.data_requests("NDAQ/IRBM")[0]["year.gte"] == "2026"
    assert _column(data, "methodology") == ["Biochar", "Geologically stored carbon"]
    assert any("pct_issued_sa" in n for n in data["notes"])


async def test_retirements_facility_with_commas_is_matched_by_id(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    data = await _call(
        make_client,
        DATA,
        dataset="retirements",
        facilities="Carbon Cycle, 001, Rieden, DE",
        start_date="2026-01-01",
    )
    (sent,) = tables.data_requests("NDAQ/RITM")
    assert sent == {"date.gte": "2026-01-01", "qopts.per_page": "10000"}
    assert _column(data, "certificate_id") == ["C1", "C2"]


@pytest.mark.parametrize(
    ("args", "certificates"),
    [
        ({"account_holder": "microsoft", "retirement_location": "usa"}, ["C1"]),
        ({"account_holder": "Microsoft", "retirement_location": "europe"}, ["C5"]),
        ({"retirement_location": "Japan"}, []),
        ({"account_holder": "  ", "limit": 2}, ["C5", "C3"]),
    ],
)
async def test_retirements_local_filters_and_newest_first(
    tables: FakeNasdaq, make_client: ClientFactory, args: dict, certificates: list
) -> None:
    data = await _call(make_client, DATA, dataset="retirements", **args)
    assert _column(data, "certificate_id") == certificates
    if args.get("limit"):
        assert data["has_more"] is True
        assert "local_filters" not in data["request"]
        assert any("showing the newest 2" in n for n in data["notes"])


async def test_transactions_filter_on_nasdaq(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    data = await _call(
        make_client,
        DATA,
        dataset="transactions",
        facilities=["Brodie Biomass"],
        transaction_type="Retirement",
        start_date="2026",
        end_date="2026",
    )
    (sent,) = tables.data_requests("NDAQ/COLT")
    assert (sent["facility_id"], sent["transaction_type"]) == ("680422", "Retirement")
    assert (sent["date.gte"], sent["date.lte"]) == ("2026-01-01", "2026-12-31")
    assert _column(data, "certificates_bundle") == ["B_1136-1151", "B_1277-1315"]
    assert "local_filters" not in data["request"]


async def test_registry_view_local_filters_and_methodology_docs(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    data = await _call(
        make_client,
        DATA,
        dataset="registry_view",
        methodology="Biochar",
        durability_category="CORC 100+",
        transaction_type="Withdrawal",
    )
    newest = await _call(make_client, DATA, dataset="registry_view", limit=1)
    assert tables.data_requests("NDAQ/SYVW")[0] == {"qopts.per_page": "10000"}
    names = [c["name"] for c in data["columns"]]
    assert "methodology_documentation_url" not in names
    assert len(data["rows"][0]) == len(names)
    assert _column(data, "certificates_bundle") == ["B2"]
    assert data["methodology_docs"] == [
        {"methodology": "Biochar, 2022", "version": "Edition 2022 V3", "url": PDF}
    ]
    assert any("certificate range" in n for n in data["notes"])
    assert set(data["request"]["local_filters"]) == {
        "methodology",
        "durability_category",
        "transaction_type",
    }
    # Documents are listed only for the rows shown.
    assert [d["url"] for d in newest["methodology_docs"]] == [PDF]


async def test_reference_prices_need_a_subscription(
    tables: FakeNasdaq, make_client: ClientFactory
) -> None:
    text = await _error(make_client, DATA, dataset="reference_prices")
    assert "[SUBSCRIPTION]" in text and "NDAQ/TRAN" in text


@pytest.mark.parametrize(
    ("bounds", "months", "echo"),
    [
        (
            {"start_date": "2025-02-15", "end_date": "2025-06-10"},
            ["June 2025", "2025-03", "Feb 2025"],
            {"month.gte": "2025-02", "month.lte": "2025-06"},
        ),
        ({"end_date": "2024"}, ["2024-12"], {"month.lte": "2024-12"}),
        ({"start_date": "2025-07-01"}, ["202601", "07/2025"], {"month.gte": "2025-07"}),
    ],
)
async def test_reference_price_bounds_select_whole_months(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    bounds: dict,
    months: list,
    echo: dict,
) -> None:
    # A subscriber's key: NDAQ/TRAN answers. `month` is text, so each bound
    # selects the month it falls in, locally; rows come back newest first.
    labels = ["2024-12", "2025-01", "Feb 2025", "2025-03", "June 2025", "07/2025"]
    _tran(fake, [*labels, "202601", "2025-Q2"])
    data = await _call(make_client, DATA, dataset="reference_prices", **bounds)
    assert fake.data_requests("NDAQ/TRAN") == [{"qopts.per_page": "10000"}]
    assert _column(data, "month") == months
    assert data["request"]["local_filters"] == echo
    assert any("1 rows whose month" in n for n in data["notes"])


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        (
            DATA,
            {"dataset": "transactions", "durability_category": "CORC"},
            "durability_category (used by facility_volumes, retirements, "
            "registry_view)",
        ),
        (
            DATA,
            {"dataset": "methodology_volumes", "facilities": "Brodie"},
            "It accepts: methodology, start_date, end_date, limit",
        ),
        (
            DATA,
            {"dataset": "transactions", "transaction_type": "Withdrawal"},
            "withdrawals are in registry_view",
        ),
        (
            DATA,
            {
                "dataset": "methodology_volumes",
                "start_date": "2026",
                "end_date": "2025",
            },
            "after end",
        ),
        (DATA, {"dataset": "retirements", "start_date": "2025-02-30"}, "not a real"),
        (DATA, {"dataset": "transactions", "facilities": [" ", ""]}, "is empty"),
        (FACILITIES, {"facilities": " , "}, "`facilities` is empty"),
    ],
)
async def test_invalid_requests_fail_before_any_request(
    tables: FakeNasdaq, make_client: ClientFactory, tool: str, args: dict, expected: str
) -> None:
    text = await _error(make_client, tool, **args)
    assert "[INVALID_REQUEST]" in text and expected in text
    assert tables.requests == []


@pytest.mark.parametrize(
    "args",
    [
        {"dataset": "transactions", "facility": "Brodie"},
        {"dataset": "facility_volumes", "start_year": 2025},
        {"dataset": "retirements", "start_date": "25-01-01"},
    ],
)
async def test_old_or_malformed_arguments_are_rejected(
    tables: FakeNasdaq, make_client: ClientFactory, args: dict
) -> None:
    async with make_client() as client:
        assert (await client.call_tool(DATA, args)).is_error
    assert tables.requests == []


async def test_describe_table_without_a_published_schema_uses_the_list(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    fake.add_table("NDAQ/TRAN", columns=[], filters=[], premium=True, forbidden=True)
    async with make_client() as client:
        data = payload(
            await client.call_tool("ndl_describe_table", {"table_code": "NDAQ/TRAN"})
        )
    assert data["access"] == "subscription"
    assert data["filters"] == ["methodology", "quarterly_period", "month"]
    assert data["columns"] == []
