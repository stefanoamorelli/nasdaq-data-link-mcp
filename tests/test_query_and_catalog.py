from __future__ import annotations

import pytest

from nasdaq_data_link_mcp_os.catalog import Catalog, CatalogEntry
from nasdaq_data_link_mcp_os.client import Column, TableMetadata
from nasdaq_data_link_mcp_os.config import Settings, parse_toolsets
from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.query import (
    build_column_params,
    build_filter_params,
    sort_rows,
)
from nasdaq_data_link_mcp_os.results import TableResult, fit_rows

META = TableMetadata(
    code="NDAQ/RTAT10",
    name="RTAT10",
    description=None,
    columns=[
        Column("date", "Date"),
        Column("ticker", "text"),
        Column("activity", "double"),
        Column("sentiment", "Integer"),
    ],
    filters=["date", "ticker"],
    primary_key=["date", "ticker"],
    premium=False,
    refreshed_at=None,
    update_frequency=None,
    status=None,
)


# ------------------------------------------------------------------ filters


def test_equality_list_and_ranges() -> None:
    params = build_filter_params(
        {
            "ticker": ["aapl", "MSFT"],
            "date.gte": "2024-01-01",
            "date.lte": "2024-02-01",
        },
        META,
    )
    assert params == [
        ("ticker", "aapl,MSFT"),
        ("date.gte", "2024-01-01"),
        ("date.lte", "2024-02-01"),
    ]


def test_nested_operator_form() -> None:
    params = build_filter_params(
        {"date": {"gte": "2024-01-01", "$lt": "2024-02-01"}}, META
    )
    assert params == [("date.gte", "2024-01-01"), ("date.lt", "2024-02-01")]


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"date.ne": "2024-01-01"}, "Unsupported operator"),
        ({"activity": 1}, "cannot be used as a filter"),
        ({"date": "04/10/2026"}, "YYYY-MM-DD"),
        ({"date": "2024-02-30"}, "not a real date"),
        ({"date.gte": ["2024-01-01", "2024-02-01"]}, "single value"),
        ({"ticker": []}, "empty list"),
        ({"date": {"between": "x"}}, "Unsupported operator"),
    ],
)
def test_invalid_filters(filters: dict, message: str) -> None:
    with pytest.raises(InvalidRequestError, match=message):
        build_filter_params(filters, META)


def test_table_without_filters() -> None:
    meta = TableMetadata(**{**META.__dict__, "filters": []})
    with pytest.raises(InvalidRequestError, match="no filterable columns"):
        build_filter_params({"ticker": "AAPL"}, meta)


def test_unknown_metadata_skips_column_checks() -> None:
    assert build_filter_params({"anything": 1}, None) == [("anything", "1")]


def test_columns() -> None:
    assert build_column_params(["date", "ticker", "date"], META) == [
        ("qopts.columns", "date,ticker")
    ]
    with pytest.raises(InvalidRequestError, match="Unknown column"):
        build_column_params(["nope"], META)


def test_sort_rows_puts_empty_values_last() -> None:
    rows = [["b", 2.0], ["a", None], ["c", 3.0], ["d", float("nan")]]
    assert sort_rows(["k", "v"], rows, "v", descending=True)[:2] == [
        ["c", 3.0],
        ["b", 2.0],
    ]
    assert [r[0] for r in sort_rows(["k", "v"], rows, "v", descending=False)][-2:] == [
        "a",
        "d",
    ]
    with pytest.raises(InvalidRequestError):
        sort_rows(["k"], rows, "missing", descending=False)


def test_fit_rows_trims_to_budget() -> None:
    result = TableResult(
        table="X/Y",
        columns=[],
        rows=[["x" * 100] for _ in range(200)],
        row_count=200,
        has_more=False,
        next_cursor="abc",
    )
    trimmed = fit_rows(result, 5_000)
    assert 0 < trimmed.row_count < 200
    assert trimmed.has_more and trimmed.next_cursor is None
    assert "trimmed" in trimmed.notes[-1]


# ------------------------------------------------------------------ catalog


def test_catalog_lists_the_tools_tables_and_every_free_table() -> None:
    from nasdaq_data_link_mcp_os.tools import TOOLSETS

    tool_tables = {t for ts in TOOLSETS.values() for s in ts.tools for t in s.tables}
    entries = Catalog.load().entries
    assert tool_tables <= {e.code for e in entries}
    assert all(e.code in tool_tables or e.access == "free" for e in entries)


def test_catalog_search() -> None:
    catalog = Catalog.load()
    assert catalog.get("ndaq/rtat10").access == "free"  # type: ignore[union-attr]
    top = [e.code for e in catalog.search("retail sentiment", limit=3)]
    assert "NDAQ/RTAT10" in top
    free = catalog.search("", access="free", limit=100)
    assert free and all(e.access == "free" for e in free)
    world_bank = catalog.search("indicators", vendor="wb", limit=10)
    assert world_bank and all(e.vendor == "WB" for e in world_bank)
    assert catalog.search("WB/DATA", limit=1)[0].code == "WB/DATA"
    assert catalog.search("zebra unicorn") == []


def test_catalog_knows_retired_codes() -> None:
    catalog = Catalog.load()
    assert catalog.is_known_missing("QOR/STATS")
    assert catalog.get("QOR/STATS") is None


# ----------------------------------------------------------------- settings


def test_settings_from_env() -> None:
    settings = Settings.from_env(
        {
            "NASDAQ_DATA_LINK_API_KEY": "  k  ",
            "NDL_TOOLSETS": "equities, World_Bank",
            "NDL_MAX_LIMIT": "500",
            "NDL_DEFAULT_LIMIT": "900",
        }
    )
    assert settings.api_key == "k"
    assert settings.toolsets == ("equities", "world_bank")
    assert settings.max_limit == 500
    assert settings.default_limit == 500


def test_settings_empty_key_is_none() -> None:
    assert Settings.from_env({"NASDAQ_DATA_LINK_API_KEY": "  "}).api_key is None


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"NDL_MAX_RETRIES": "abc"}, "integer"),
        ({"NDL_MAX_CONCURRENCY": "9"}, "between"),
        ({"NDL_LOG_LEVEL": "loud"}, "NDL_LOG_LEVEL"),
    ],
)
def test_settings_validation(env: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_env(env)


def test_parse_toolsets() -> None:
    assert parse_toolsets(None) is None
    assert parse_toolsets("all") is None
    assert parse_toolsets(" , ") is None
    assert parse_toolsets("sql,sql,Core") == ("sql", "core")


def test_catalog_holds_only_our_own_short_text() -> None:
    import re

    jargon = re.compile(
        r"\b(403|404|422|429)\b|HTTP \d|QE[A-Z]x\d|premium=|probe",
        re.IGNORECASE,
    )
    # Exact dates in a note would be values read from sample rows.
    sample_values = re.compile(r"\d{4}-\d{2}-\d{2}")
    for entry in Catalog.load().entries:
        for text in (entry.notes, entry.description):
            assert not (text and jargon.search(text)), (entry.code, text)
        assert not (entry.notes and sample_values.search(entry.notes)), entry.code
        assert len(entry.description) <= 120, entry.code
        assert len(entry.name) <= 60, entry.code


def test_catalog_entries_reject_fields_outside_the_data_policy() -> None:
    raw = {
        "code": "X/Y",
        "vendor": "X",
        "name": "Example",
        "access": "free",
        "description": "Example table.",
    }
    assert CatalogEntry.from_json(raw).code == "X/Y"
    with pytest.raises(ValueError, match="columns"):
        CatalogEntry.from_json({**raw, "columns": ["a"]})
    with pytest.raises(ValueError, match="access"):
        CatalogEntry.from_json({**raw, "access": "unknown"})


def test_refresh_script_keeps_the_bundled_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "refresh_catalog", root / "scripts" / "refresh_catalog.py"
    )
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "refresh_catalog", script)
    spec.loader.exec_module(script)
    text = (root / "nasdaq_data_link_mcp_os" / "data" / "catalog.json").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(text)
    assert script.render(catalog) == text
    entry = catalog["tables"][0]
    live = TableMetadata(**{**META.__dict__, "name": "Vendor title"})
    probe = script.Probe(entry["code"], metadata=live, access="free")
    assert set(script.updated_entry(entry, probe)) == set(entry)


def test_table_read_records_respects_an_empty_selection() -> None:
    from nasdaq_data_link_mcp_os.results import ColumnInfo
    from nasdaq_data_link_mcp_os.tools._common import TableRead

    read = TableRead(
        code="X/Y",
        metadata=None,
        columns=[ColumnInfo(name="a")],
        rows=[[1], [2]],
        request={},
        next_cursor=None,
        page_size=10,
    )
    assert read.records() == [{"a": 1}, {"a": 2}]
    assert read.records([]) == []


def test_fit_rows_twice_keeps_one_note_with_the_original_total() -> None:
    result = TableResult(
        table="X/Y",
        columns=[],
        rows=[["x" * 100] for _ in range(300)],
        row_count=300,
        has_more=False,
    )
    once = fit_rows(result, 8_000)
    twice = fit_rows(once.model_copy(update={"notes": [*once.notes, "extra"]}), 5_000)
    trim_notes = [n for n in twice.notes if n.startswith("Output trimmed")]
    assert len(trim_notes) == 1 and "of 300 rows" in trim_notes[0]
    from nasdaq_data_link_mcp_os.results import dump, to_json

    assert len(to_json(dump(twice)).encode()) <= 5_000


@pytest.mark.parametrize(
    "filters",
    [
        {"ticker": None},
        {"ticker": "  "},
        {"date": {"gte": ["2024-01-01", "2024-02-01"]}},
    ],
)
def test_empty_values_and_nested_lists_are_rejected(filters: dict) -> None:
    with pytest.raises(InvalidRequestError):
        build_filter_params(filters, META)


def test_missing_values_use_the_rows_layout() -> None:
    from nasdaq_data_link_mcp_os.results import ColumnInfo
    from nasdaq_data_link_mcp_os.tools._common import TableRead, _missing_values

    read = TableRead(
        code="ZILLOW/DATA",
        metadata=None,
        columns=[ColumnInfo(name="region_id"), ColumnInfo(name="date")],
        rows=[],
        request={"region_id": "1,2"},
        next_cursor="more",
        page_size=10,
    )
    reshaped = [["2025-01-31", "1"]]  # the tool reordered to [date, region_id]
    assert _missing_values(read, reshaped, ["date", "region_id"]) == ["region_id 2"]
