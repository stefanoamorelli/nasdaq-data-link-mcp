"""Offline tests for the funds toolset (Nasdaq Fund Network NFN/MFR* tables).

Fake tables copy the live column names and filterable columns (fetched
2026-10-03); ids and values are made up.
"""

from __future__ import annotations

from typing import Any

import anyio
import jsonschema
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

from nasdaq_data_link_mcp_os.tools import funds
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import FakeNasdaq

pytestmark = pytest.mark.anyio


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


COLUMBIA, PRINCIPAL, CEF_FUND = _uuid(1), _uuid(2), _uuid(3)
LIBAX, CIBRX, PTDAX, CEF_SEC = _uuid(11), _uuid(12), _uuid(13), _uuid(14)
BENCH, BENCH_OTHER, UNKNOWN = _uuid(21), _uuid(22), _uuid(99)
NIL = "00000000-0000-0000-0000-000000000000"

PERIODS = "1day 1wk 1mo 3mo 1yr 3yr 5yr 10yr inception ytd".split()
HOLDING = (
    "fund_id date holding_index issuer_name issuer_lei title cusip isin ticker "
    "figi_ticker figi_exch_code figi other_id_desc other_id balance units "
    "desc_oth_units cur_cd exchange_rt val_usd pct_val payoff_profile asset_cat "
    "asset_cat_desc issuer_cat issuer_cat_desc inv_country risk_country "
    "is_restricted_sec liquidity_cat fair_value_level is_cash_collateral "
    "cash_collateral_val is_non_cash_collateral non_cash_collateral_val "
    "is_loan_by_fund loan_val is_debt is_derivative is_repurchase_agrmt"
)
COLUMNS = {
    "NFN/MFRSM": "security_id fund_id name instrument_code inception_date "
    "inception_share_price inception_nav final_date final_comment nav_symbol "
    "ticker_symbol cusip edgar_class_id share_class_figi nav_figi ticker_figi "
    "nasdaq_security_master",
    "NFN/MFRFM": "fund_id name investment_company_type formation_date "
    "termination_date termination_comment lei edgar_series_id "
    "nasdaq_root_symbol cik",
    "NFN/MFRFI": "fund_id info_date family advisors objective strategy risks "
    "websites fye turnover_rate closed_to_new_inv closed_to_existing_inv "
    "edgar_prospectus_url street1 street2 city state zip_or_postal_code country "
    "phone benchmarks portfolio_managers cef_period_end_date cef_mgmt_fee "
    "cef_op_exp assets_date tot_assets tot_liabs net_assets ndw_date "
    "ndw_fund_score ndw_investment_category ndw_investment_group",
    "NFN/MFRSI": "security_id info_date issuer currency registration "
    "pricing_agent share_class op_exp_date net_expenses_over_assets "
    "expenses_over_assets mgmt_fees_over_assets dist_12b1_fees_over_assets "
    "other_expenses_over_assets fee_waiver_over_asset shareholder_fees_date "
    "max_sales_charge max_deferred_sales_charge max_redemption_fee "
    "max_sales_charge_on_reinvested",
    "NFN/MFRPS": "security_id pricing_type_id ref_date benchmark_id date "
    + " ".join(f"date_{p}" for p in PERIODS)
    + " "
    + " ".join(f"ret_{p}" for p in PERIODS)
    + " last_price net_chg_1day date_hi_52wk date_lo_52wk hi_52wk lo_52wk "
    "yield_1yr",
    "NFN/MFRPA": "security_id benchmark_id pricing_type_id period ref_date "
    "start_date end_date n total_return std_dev alpha beta r_squared "
    "upside_capture_ratio downside_capture_ratio downside_deviation "
    "tracking_error sharpe_ratio sortino_ratio information_ratio treynor_ratio "
    "max_draw_down max_gain",
    "NFN/MFRPH10": HOLDING,
    "NFN/MFRPH": f"{HOLDING} debt_maturity_date debt_coupon_category "
    "debt_coupon_ann_rate",
    "NFN/MFRPM": "fund_id date manager_index name role ownership biography "
    "file_date years_exp_fund years_exp_group years_exp_industry "
    "start_date_fund start_date_group start_date_industry",
    "NFN/MFRPB": "benchmark_id name grp blended rebalance_freq_id price_ret "
    "hedged net after_tax",
    "NFN/MFRMF": "fund_id year month file_date redemption reinvestment sales",
}
# Filterable columns where not every column is (live metadata).
FILTERS = {
    "NFN/MFRFI": "family info_date fund_id",
    "NFN/MFRPS": "benchmark_id pricing_type_id ref_date security_id",
    "NFN/MFRPA": "security_id benchmark_id ref_date pricing_type_id",
    "NFN/MFRPH": "date fund_id holding_index issuer_name ticker",
    "NFN/MFRMF": "fund_id",
}


def _class(sec: str, fund: str, name: str, nav: str, **kw: Any) -> dict[str, Any]:
    return {
        "security_id": sec,
        "fund_id": fund,
        "name": name,
        "instrument_code": "O",
        "nav_symbol": nav,
        **kw,
    }


def _price(sec: str, ptype: int, ref: str, bench: str) -> dict[str, Any]:
    return {
        "security_id": sec,
        "pricing_type_id": ptype,
        "ref_date": ref,
        "benchmark_id": bench,
        "date": ref,
        "last_price": 10.0 if ptype == 0 else None,
    }


def _holding(fund: str, date: str, index: int, issuer: str, pct: float) -> dict:
    return {
        "fund_id": fund,
        "date": date,
        "holding_index": index,
        "issuer_name": issuer,
        "pct_val": pct,
    }


ROWS: dict[str, list[dict[str, Any]]] = {
    "NFN/MFRSM": [
        _class(LIBAX, COLUMBIA, "Columbia Total Return Bond Fund Class A", "LIBAX")
        | {"cusip": "00000A001"},
        _class(CIBRX, COLUMBIA, "Columbia Total Return Bond Fund Class R", "CIBRX"),
        _class(PTDAX, PRINCIPAL, "Principal Fds, Inc. LifeTime 2040 Fd A", "PTDAX"),
        _class(CEF_SEC, CEF_FUND, "PIMCO Dynamic Income Fund", "XPDIX")
        | {"instrument_code": "C", "ticker_symbol": "PDI"},
    ],
    "NFN/MFRFM": [
        {"fund_id": f, "name": n, "investment_company_type": t}
        for f, n, t in (
            (COLUMBIA, "Columbia Total Return Bond Fund", "N-1A"),
            (PRINCIPAL, "Principal LifeTime 2040 Fund", "N-1A"),
            (CEF_FUND, "PIMCO Dynamic Income Fund", "N-2"),
        )
    ],
    "NFN/MFRFI": [
        {
            "fund_id": COLUMBIA,
            "info_date": "2026-06-22",
            "objective": "Total return.",
            "risks": "x" * 30_000,
            "net_assets": 1.5e9,
        }
    ],
    "NFN/MFRSI": [
        {"security_id": s, "info_date": "2026-06-22", "net_expenses_over_assets": e}
        for s, e in ((LIBAX, 0.005), (CIBRX, 0.01))
    ],
    "NFN/MFRPS": [
        _price(LIBAX, 0, "2026-09-01", NIL),
        _price(LIBAX, 2, "2026-10-03", BENCH),
        _price(LIBAX, 0, "2026-10-03", NIL),
        _price(LIBAX, 2, "2026-09-01", BENCH_OTHER),
        _price(CIBRX, 0, "2026-10-03", NIL),
    ],
    "NFN/MFRPB": [{"benchmark_id": BENCH, "name": "Index A", "grp": "BB"}],
    "NFN/MFRPA": [
        {"security_id": _uuid(50), "period": "Y10", "ref_date": "2026-01-01"}
    ],
    "NFN/MFRPH10": [
        _holding(COLUMBIA, "2026-07-31", 256, "Issuer C", 1.0),
        _holding(COLUMBIA, "2026-07-31", 240, "Issuer A", 4.0),
        _holding(COLUMBIA, "2026-07-31", 40, "Issuer B", 2.0),
        _holding(PRINCIPAL, "2026-06-30", 3, "Issuer D", 9.0),
    ],
    "NFN/MFRPM": [
        {"fund_id": COLUMBIA, "date": "2025-05-29", "manager_index": 0, "name": "Old"},
        {"fund_id": COLUMBIA, "date": "2026-05-29", "manager_index": 1, "name": "B"},
        {"fund_id": COLUMBIA, "date": "2026-05-29", "manager_index": 0, "name": "A"},
    ],
}


def _mfr(fake: FakeNasdaq) -> None:
    """Register the NFN/MFR* tables (free-key sample access, MFRMF 403)."""
    for code, text in COLUMNS.items():
        names = text.split()
        records = ROWS.get(code, [])
        assert all(set(r) <= set(names) for r in records), code
        fake.add_table(
            code,
            [(n, "String") for n in names],
            filters=FILTERS.get(code, text).split(),
            rows=[[r.get(n) for n in names] for r in records],
            premium=True,
            forbidden=code == "NFN/MFRMF",
        )


def _column(data: dict[str, Any], name: str) -> list[Any]:
    index = [c["name"] for c in data["columns"]].index(name)
    return [row[index] for row in data["rows"]]


def _metadata_requests(fake: FakeNasdaq, code: str) -> int:
    return sum(r.url.path.endswith(f"/{code}/metadata") for r in fake.requests)


async def _search(client: Client, query: str, **kw: Any) -> dict[str, Any]:
    arguments = {"query": query, **kw}
    return payload(await client.call_tool("ndl_search_mutual_funds", arguments))


async def _report(client: Client, **arguments: Any) -> dict[str, Any]:
    return payload(await client.call_tool("ndl_get_mutual_fund_report", arguments))


# ------------------------------------------------------------------- search


@pytest.mark.parametrize(
    ("query", "matched_by", "column", "fund", "tickers"),
    [
        ("libax", "ticker", "nav_symbol", COLUMBIA, ["LIBAX"]),
        ("PDI", "ticker", "ticker_symbol", CEF_FUND, ["XPDIX"]),
        ("00000a001", "cusip", "cusip", COLUMBIA, ["LIBAX"]),
        (LIBAX.upper(), "security_id", "security_id", COLUMBIA, ["LIBAX"]),
        (COLUMBIA, "fund_id", "fund_id", COLUMBIA, ["LIBAX", "CIBRX"]),
    ],
)
async def test_search_exact_lookups(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    query: str,
    matched_by: str,
    column: str,
    fund: str,
    tickers: list[str],
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _search(client, query)
    assert data["matched_by"] == matched_by and data["access"] == "sample"
    [match] = data["funds"]
    assert match["fund_id"] == fund
    assert [s["ticker"] for s in match["share_classes"]] == tickers
    assert column in fake.data_requests("NFN/MFRSM")[-1]
    [fund_lookup] = fake.data_requests("NFN/MFRFM")
    assert fund_lookup["fund_id"] == fund
    assert _metadata_requests(fake, "NFN/MFRSM") == 0
    assert any("about 30 funds" in n for n in data["notes"])


async def test_search_by_name_needs_every_word(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        bond = await _search(client, "columbia bond")
        fds = await _search(client, "Fds Inc")
        everything = await _search(client, "", limit=2)
        nothing = await _search(client, "VFIAX")
    [fund] = bond["funds"]
    assert bond["matched_by"] == "name" and fund["fund_id"] == COLUMBIA
    assert {s["ticker"] for s in fund["share_classes"]} == {"LIBAX", "CIBRX"}
    # Only the share-class name ("Principal Fds, Inc. ...") has these words.
    assert [f["name"] for f in fds["funds"]] == ["Principal LifeTime 2040 Fund"]
    assert everything["matched_by"] == "all" and everything["has_more"] is True
    assert [f["name"] for f in everything["funds"]] == [
        "Columbia Total Return Bond Fund",
        "PIMCO Dynamic Income Fund",
    ]
    assert nothing["funds"] == [] and nothing["matched_by"] == "name"
    assert any("every word of 'VFIAX'" in n for n in nothing["notes"])


async def test_search_unknown_id_skips_the_name_scan(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _search(client, UNKNOWN)
    assert data["funds"] == [] and any(UNKNOWN in n for n in data["notes"])
    sent = fake.data_requests("NFN/MFRSM")
    assert [r.get("security_id") or r.get("fund_id") for r in sent] == [UNKNOWN] * 2
    assert fake.data_requests("NFN/MFRFM") == []


# ------------------------------------------------------------------ reports


async def test_fees_by_tickers_resolve_security_ids(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _report(client, report="fees", tickers=["libax", "CIBRX"])
    assert data["table"] == "NFN/MFRSI" and data["report"] == "fees"
    assert fake.data_requests("NFN/MFRSM")[0]["nav_symbol"] == "LIBAX,CIBRX"
    assert fake.data_requests("NFN/MFRSI")[0]["security_id"] == f"{LIBAX},{CIBRX}"
    assert sorted(_column(data, "net_expenses_over_assets")) == [0.005, 0.01]
    assert {r["ticker"] for r in data["resolved"]} == {"LIBAX", "CIBRX"}
    assert any("fractions" in n for n in data["notes"])
    assert _metadata_requests(fake, "NFN/MFRSM") == 0
    assert _metadata_requests(fake, "NFN/MFRSI") == 1


@pytest.mark.parametrize(
    ("args", "table", "sent", "resolved"),
    [
        ({"report": "fees", "fund_ids": COLUMBIA}, "NFN/MFRSI", f"{LIBAX},{CIBRX}", 2),
        (
            {"report": "fund_info", "security_ids": f"{LIBAX.upper()}, {CIBRX}"},
            "NFN/MFRFI",
            COLUMBIA,
            2,
        ),
        ({"report": "share_classes", "tickers": "LIBAX"}, "NFN/MFRSM", COLUMBIA, 1),
        ({"report": "fund_info", "fund_ids": COLUMBIA}, "NFN/MFRFI", COLUMBIA, None),
    ],
)
async def test_ids_are_mapped_to_the_reports_key(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    args: dict[str, Any],
    table: str,
    sent: str,
    resolved: int | None,
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _report(client, **args)
    key = funds.REPORTS[args["report"]].key_column
    assert fake.data_requests(table)[-1][key] == sent
    assert len(data.get("resolved") or []) == (resolved or 0)
    assert ("resolved" in data) == (resolved is not None)


async def test_pricing_newest_first_with_benchmark_names(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _report(client, report="pricing", tickers="LIBAX")
        dated = await _report(
            client,
            report="pricing",
            security_ids=LIBAX,
            benchmark_ids=BENCH,
            start_date="2026-10-01",
        )
    sent = fake.data_requests("NFN/MFRPS")[0]
    assert sent["security_id"] == LIBAX and "date_1day" not in sent["qopts.columns"]
    assert _column(data, "ref_date") == ["2026-10-03"] * 2 + ["2026-09-01"] * 2
    assert _column(data, "pricing_type_id") == [0, 2, 0, 2]  # NAV before benchmark
    assert any("pricing_type_id 0 = NAV" in n for n in data["notes"])
    # Names come from one id lookup without a metadata request; BENCH_OTHER has none.
    assert data["benchmark_names"] == {BENCH: "Index A"}
    lookup = fake.data_requests("NFN/MFRPB")[0]
    assert set(lookup["benchmark_id"].split(",")) == {BENCH, BENCH_OTHER}
    assert _metadata_requests(fake, "NFN/MFRPB") == 0
    sent = fake.data_requests("NFN/MFRPS")[1]
    assert sent["ref_date.gte"] == "2026-10-01" and sent["benchmark_id"] == BENCH
    assert dated["row_count"] == 1 and "resolved" not in dated


@pytest.mark.parametrize(
    ("failure", "expected"),
    [("slow", "did not answer within 0.05 s"), ("forbidden", "failed (SUBSCRIPTION)")],
)
async def test_benchmark_names_are_optional(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: str,
) -> None:
    _mfr(fake)
    fake.tables["NFN/MFRPB"].forbidden = failure == "forbidden"
    real = funds.read_table

    async def slow(ctx: Any, code: str, **kwargs: Any) -> Any:
        if code == "NFN/MFRPB" and failure == "slow":
            await anyio.sleep(5)
        return await real(ctx, code, **kwargs)

    monkeypatch.setattr(funds, "read_table", slow)
    if failure == "slow":
        monkeypatch.setattr(funds, "BENCHMARK_LOOKUP_SECONDS", 0.05)
    async with make_client() as client:
        with anyio.fail_after(2):
            data = await _report(client, report="pricing", tickers="LIBAX")
    assert data["row_count"] == 4 and "benchmark_names" not in data
    assert any(expected in n for n in data["notes"])


async def test_fund_info_columns(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _mfr(fake)
    async with make_client() as client:
        default = await _report(client, report="fund_info", fund_ids=COLUMBIA)
        everything = await _report(
            client, report="fund_info", fund_ids=COLUMBIA, columns="all"
        )
        custom = await _report(
            client, report="fund_info", fund_ids=COLUMBIA, columns=["risks"]
        )
    names = [c["name"] for c in default["columns"]]
    assert "risks" not in names and "objective" in names
    assert _column(default, "net_assets") == [1.5e9]
    assert len(everything["columns"]) == len(COLUMNS["NFN/MFRFI"].split())
    assert [c["name"] for c in custom["columns"]] == ["fund_id", "risks"]


@pytest.mark.parametrize(
    ("report", "column", "expected", "sort_by"),
    [
        ("top_holdings", "pct_val", [4.0, 2.0, 1.0], "pct_val desc"),
        ("managers", "name", ["A", "B", "Old"], "date desc, manager_index asc"),
    ],
)
async def test_fund_reports_are_sorted(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    report: str,
    column: str,
    expected: list[Any],
    sort_by: str,
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _report(client, report=report, fund_ids=COLUMBIA)
    assert _column(data, column) == expected
    assert data["request"]["sort_by"] == sort_by


async def test_holdings_use_each_funds_latest_report_date(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    names = COLUMNS["NFN/MFRPH"].split()
    fake.tables["NFN/MFRPH"].rows = [
        [r.get(n) for n in names]
        for r in (
            _holding(COLUMBIA, "2026-07-31", 0, "New A", 1.0),
            _holding(COLUMBIA, "2026-07-31", 1, "New B", 5.0),
            _holding(COLUMBIA, "2026-04-30", 0, "Old A", 3.0),
            _holding(PRINCIPAL, "2026-03-31", 0, "P old", 8.0),
            _holding(PRINCIPAL, "2026-06-30", 0, "P A", 7.0),
            _holding(PRINCIPAL, "2026-07-31", 5, "P stray", 0.1),
        )
    ]
    async with make_client() as client:
        data = await _report(client, report="holdings", fund_ids=[COLUMBIA, PRINCIPAL])
    probe, main = fake.data_requests("NFN/MFRPH")
    assert probe["holding_index"] == "0" and probe["qopts.columns"] == "fund_id,date"
    assert main["date"] == "2026-06-30,2026-07-31"
    assert _column(data, "issuer_name") == ["P A", "New B", "New A"]


async def test_empty_samples_and_403_tables_name_an_alternative(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        holdings = await _report(client, report="holdings", tickers="LIBAX")
        flows = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "flows", "fund_ids": COLUMBIA}
            )
        )
    assert holdings["rows"] == []
    assert any("top_holdings (NFN/MFRPH10)" in n for n in holdings["notes"])
    assert "[SUBSCRIPTION]" in flows and "fund_info has total and net assets" in flows


async def test_report_without_identifier_is_an_unsorted_slice(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _mfr(fake)
    async with make_client() as client:
        data = await _report(client, report="managers", limit=1)
        bench = await _report(client, report="benchmarks", benchmark_ids=BENCH)
    assert data["row_count"] == 1 and data["has_more"] is True
    assert "next_cursor" not in data  # the tool has no cursor parameter
    assert "sort_by" not in data["request"]
    assert any("No fund or share class was given" in n for n in data["notes"])
    assert _column(bench, "name") == ["Index A"]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"report": "fees", "tickers": "LIBAX", "fund_ids": COLUMBIA}, "only one of"),
        ({"report": "fees", "security_ids": "LIBAX"}, "not a UUID"),
        ({"report": "fees", "tickers": "LIB AX"}, "not a ticker"),
        ({"report": "fees", "tickers": [f"T{i}" for i in range(26)]}, "at most 25"),
        ({"report": "fund_master", "start_date": "2024-01-01"}, "no date filter"),
        ({"report": "fees", "benchmark_ids": BENCH}, "benchmark_ids applies"),
        ({"report": "benchmarks", "tickers": "LIBAX"}, "benchmark dictionary"),
        (
            {
                "report": "pricing",
                "security_ids": LIBAX,
                "start_date": "2026-02-01",
                "end_date": "2026-01-01",
            },
            "after end date",
        ),
    ],
)
async def test_invalid_requests_spend_no_data_calls(
    fake: FakeNasdaq,
    make_client: ClientFactory,
    arguments: dict[str, Any],
    expected: str,
) -> None:
    _mfr(fake)
    async with make_client() as client:
        text = error_text(
            await client.call_tool("ndl_get_mutual_fund_report", arguments)
        )
    assert "[INVALID_REQUEST]" in text and expected in text
    assert fake.data_requests() == []


async def test_tickers_must_be_nav_symbols(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mfr(fake)
    async with make_client() as client:
        missing = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "fees", "tickers": "VFIAX"}
            )
        )
        # A closed-end fund's exchange ticker is not its nav_symbol.
        exchange = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "fees", "tickers": "PDI"}
            )
        )
        partial = await _report(client, report="fees", tickers=["LIBAX", "VFIAX"])
        monkeypatch.setattr(funds, "MAX_KEYS", 1)
        too_many = error_text(
            await client.call_tool(
                "ndl_get_mutual_fund_report", {"report": "fees", "fund_ids": COLUMBIA}
            )
        )
    assert "[INVALID_REQUEST]" in missing and "nav_symbol VFIAX" in missing
    assert "sample" in missing and "ndl_search_mutual_funds" in missing
    assert "nav_symbol PDI" in exchange
    assert any("Not found in NFN/MFRSM: VFIAX" in n for n in partial["notes"])
    assert "cover 2 security_id values" in too_many
    assert [r["security_id"] for r in fake.data_requests("NFN/MFRSI")] == [LIBAX]


@pytest.mark.parametrize(
    "args",
    [
        {"report": "fees", "security_ids": LIBAX, "columns": "security_id"},
        {"report": "fund_info", "fund_ids": COLUMBIA, "columns": "all"},
        {"report": "benchmarks", "benchmark_ids": [BENCH, BENCH_OTHER]},
    ],
)
async def test_schema_admits_single_strings_and_lists(
    fake: FakeNasdaq, make_client: ClientFactory, args: dict[str, Any]
) -> None:
    _mfr(fake)
    async with make_client() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        jsonschema.validate(args, tools["ndl_get_mutual_fund_report"].input_schema)
        await _report(client, **args)


# ------------------------------------------------------------------ prompts


async def test_fund_snapshot_prompt(make_client: ClientFactory) -> None:
    async with make_client() as client:
        prompts = {p.name: p for p in (await client.list_prompts()).prompts}
        result = await client.get_prompt("fund_snapshot", {"fund": " columbia\n bond "})
    description = prompts["fund_snapshot"].description or ""
    assert description and "\n" not in description
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert "mutual fund columbia bond with" in text
    assert "ndl_search_mutual_funds" in text and "ndl_get_mutual_fund_report" in text


@pytest.mark.parametrize("fund", ["", "  \n ", "x" * (funds.MAX_QUERY_LEN + 1)])
async def test_fund_snapshot_rejects_blank_or_overlong_fund(
    make_client: ClientFactory, fund: str
) -> None:
    async with make_client() as client:
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("fund_snapshot", {"fund": fund})
    assert caught.value.code == INVALID_PARAMS
    assert "'LIBAX'" in caught.value.message


async def test_tools_declare_the_tables_they_read(make_client: ClientFactory) -> None:
    async with make_client() as client:
        data = payload(
            await client.call_tool("ndl_search_tables", {"query": "NFN/MFRSM"})
        )
    [entry] = [r for r in data["results"] if r["code"] == "NFN/MFRSM"]
    assert set(entry["tools"]) == {
        "ndl_search_mutual_funds",
        "ndl_get_mutual_fund_report",
    }
