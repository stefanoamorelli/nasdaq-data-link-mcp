from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.server import create_server
from nasdaq_data_link_mcp_os.tools.sql import read_only_statement
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import API_KEY, FakeNasdaq

pytestmark = pytest.mark.anyio

RTAT10_COLUMNS = [
    {"name": "date", "type": "date"},
    {"name": "ticker", "type": "varchar"},
    {"name": "activity", "type": "double"},
    {"name": "sentiment", "type": "integer"},
]
RTAT10_ROWS = [
    ["2026-10-02", "TSLA", 0.0243, -2],
    ["2026-10-02", "NVDA", 0.0318, 0],
    ["2026-10-01", "MU", 0.0454, 2],
    ["2026-09-30", "TSLA", 0.0301, 1],
    ["2026-09-30", "AAPL", 0.0207, 5],
]


def _serve(fake: FakeNasdaq, *pages: dict[str, Any]) -> list[str]:
    """Answer every statement with ``pages`` (after a QUEUED page); return the SQL."""
    seen: list[str] = []

    def handler(sql: str) -> list[dict[str, Any]]:
        seen.append(sql)
        return [{"id": "q1", "stats": {"state": "QUEUED"}}, *pages]

    fake.sql_handler = handler
    return seen


def _rows_pages(rows: list[list[Any]], per_page: int = 2) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for start in range(0, len(rows), per_page):
        page: dict[str, Any] = {
            "data": rows[start : start + per_page],
            "stats": {"state": "RUNNING"},
        }
        if start == 0:
            page["columns"] = RTAT10_COLUMNS
        pages.append(page)
    pages.append({"stats": {"state": "FINISHED"}})
    return pages


def _sql_calls(fake: FakeNasdaq) -> list[str]:
    return [r.method for r in fake.requests if r.url.path.startswith("/v1/statement")]


# ------------------------------------------------------------ read-only guard


@pytest.mark.parametrize(
    ("sql", "sent"),
    [
        ("SELECT 1", "SELECT 1"),
        (
            "  select * from ndaq_rtat10 limit 5 ;  ",
            "select * from ndaq_rtat10 limit 5",
        ),
        ("SHOW TABLES;;", "SHOW TABLES"),
        ("DESCRIBE ndaq_rtat10; -- schema", "DESCRIBE ndaq_rtat10"),
        ("desc ndaq_rtat10", "desc ndaq_rtat10"),
        ("-- latest rows\nSELECT 1", "-- latest rows\nSELECT 1"),
        ("/* a; b */ WITH t AS (SELECT 1 AS x) SELECT x FROM t", None),
        ("VALUES (1, 'a'), (2, 'b')", None),
        ("(SELECT 1) UNION ALL (SELECT 2)", None),
        ("EXPLAIN SELECT * FROM ndaq_rtat10", None),
        ("EXPLAIN ANALYZE VERBOSE SELECT 1", None),
        ("EXPLAIN (TYPE DISTRIBUTED, FORMAT JSON) SELECT 1", None),
        ("EXPLAIN (SELECT 1)", None),
        ("SELECT ';' AS s, \"a;b\" FROM t -- ; trailing", None),
        ("SELECT 'it''s; fine' AS s", None),
    ],
)
def test_guard_accepts_read_only_statements(sql: str, sent: str | None) -> None:
    assert read_only_statement(sql) == (sent if sent is not None else sql.strip())


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("", "empty"),
        ("  ;  ", "empty"),
        ("-- only a comment", "empty"),
        ("INSERT INTO ndaq_rtat10 VALUES (1)", "starts with INSERT"),
        ("drop table ndaq_rtat10", "starts with DROP"),
        ("CREATE TABLE x AS SELECT 1", "starts with CREATE"),
        ("SET SESSION query_max_run_time = '1h'", "starts with SET"),
        ("CALL system.runtime.kill_query('q1')", "starts with CALL"),
        ("/* SELECT */ DELETE FROM ndaq_rtat10", "starts with DELETE"),
        ("-- SELECT\nDROP TABLE ndaq_rtat10", "starts with DROP"),
        ("(DELETE FROM t)", "starts with DELETE"),
        ("(SHOW TABLES)", "starts with SHOW"),
        ("EXPLAIN ANALYZE INSERT INTO t SELECT 1", "starts with INSERT"),
        ("EXPLAIN (TYPE IO) DELETE FROM t", "starts with DELETE"),
        ("EXPLAIN EXPLAIN SELECT 1", "starts with EXPLAIN"),
        ("EXPLAIN", "needs a statement"),
        ("SELECT 1; DROP TABLE ndaq_rtat10", "one SQL statement"),
        ("SELECT 1; SELECT 2;", "one SQL statement"),
        ("; SELECT 1", "one SQL statement"),
        ("* FROM t", "must start with"),
    ],
)
def test_guard_rejects_everything_else(sql: str, message: str) -> None:
    with pytest.raises(InvalidRequestError, match=message):
        read_only_statement(sql)


def test_guard_lists_the_allowed_keywords() -> None:
    with pytest.raises(InvalidRequestError) as info:
        read_only_statement("UPDATE t SET x = 1")
    assert "SELECT, WITH, SHOW, DESCRIBE, EXPLAIN or VALUES" in str(info.value)


# ---------------------------------------------------------------- the tool


async def test_select_collects_rows_and_strips_semicolon(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    seen = _serve(fake, *_rows_pages(RTAT10_ROWS))
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_sql_query",
                {"sql": "SELECT * FROM ndaq_rtat10 ORDER BY date DESC;\n"},
            )
        )
    assert seen == ["SELECT * FROM ndaq_rtat10 ORDER BY date DESC"]
    assert data["columns"] == RTAT10_COLUMNS
    assert data["rows"] == RTAT10_ROWS
    assert data["row_count"] == 5
    assert data["has_more"] is False
    assert data["notes"] == []
    sql_requests = [r for r in fake.requests if r.url.path == "/v1/statement"]
    assert sql_requests[0].headers["x-trino-catalog"] == "main"
    assert sql_requests[0].headers["x-trino-schema"] == "huron"


async def test_max_rows_truncates_and_cancels(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(fake, *_rows_pages(RTAT10_ROWS))
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq_rtat10", "limit": 3}
            )
        )
    assert data["row_count"] == 3 and data["rows"] == RTAT10_ROWS[:3]
    assert data["has_more"] is True
    assert any("More than 3 rows matched" in n for n in data["notes"])
    assert "DELETE" in _sql_calls(fake)


async def test_exactly_max_rows_is_not_truncated(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    # Trino keeps a nextUri on the last data page; that alone is not truncation.
    _serve(fake, *_rows_pages(RTAT10_ROWS, per_page=5))
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq_rtat10", "limit": 5}
            )
        )
    assert data["row_count"] == 5 and data["has_more"] is False
    assert "DELETE" not in _sql_calls(fake)


async def test_rows_on_the_final_page_beyond_max_rows_are_truncated(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(
        fake,
        {
            "columns": RTAT10_COLUMNS,
            "data": RTAT10_ROWS,
            "stats": {"state": "FINISHED"},
        },
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq_rtat10", "limit": 2}
            )
        )
    assert data["row_count"] == 2 and data["has_more"] is True


async def test_max_rows_respects_the_server_limit(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(fake, *_rows_pages(RTAT10_ROWS))
    async with make_client(max_limit=2) as client:
        data = payload(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq_rtat10", "limit": 50}
            )
        )
    assert data["row_count"] == 2 and data["has_more"] is True
    assert any("max 2" in n for n in data["notes"])


async def test_large_output_is_trimmed_to_the_byte_budget(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    wide = [[str(i), "x" * 500] for i in range(60)]
    _serve(
        fake,
        {
            "columns": [
                {"name": "k", "type": "varchar"},
                {"name": "blob", "type": "varchar"},
            ],
            "data": wide,
            "stats": {"state": "FINISHED"},
        },
    )
    async with make_client(max_response_bytes=5_000) as client:
        data = payload(
            await client.call_tool("ndl_sql_query", {"sql": "SELECT k, blob FROM t"})
        )
    assert 0 < data["row_count"] < 60
    assert data["has_more"] is True
    assert any("Output trimmed" in n for n in data["notes"])
    assert len(json.dumps(data, separators=(",", ":")).encode()) <= 5_000


async def test_show_tables_explains_entitlements(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(
        fake,
        {
            "columns": [{"name": "Table", "type": "varchar"}],
            "data": [["ndaq_rtat"], ["ndaq_rtat10"]],
            "stats": {"state": "FINISHED"},
        },
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool("ndl_sql_query", {"sql": "-- list\nshow tables"})
        )
    assert data["rows"] == [["ndaq_rtat"], ["ndaq_rtat10"]]
    (note,) = data["notes"]
    assert "Tables API" in note and "ndaq_rtat10 is NDAQ/RTAT10" in note


async def test_write_statements_never_reach_nasdaq(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(fake, *_rows_pages(RTAT10_ROWS))
    async with make_client() as client:
        write = error_text(
            await client.call_tool("ndl_sql_query", {"sql": "DROP TABLE ndaq_rtat10"})
        )
        multi = error_text(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT 1; DELETE FROM ndaq_rtat10"}
            )
        )
    assert "[INVALID_REQUEST]" in write and "starts with DROP" in write
    assert "[INVALID_REQUEST]" in multi and "one SQL statement" in multi
    assert _sql_calls(fake) == []


async def test_permission_denied_is_a_subscription_error(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _serve(
        fake,
        {
            "error": {
                "message": f"Access Denied: User {API_KEY} cannot select from "
                "columns [date, id, value] in table or view main.huron.qdl_opec",
                "errorName": "PERMISSION_DENIED",
            },
            "stats": {"state": "FAILED"},
        },
    )
    async with make_client() as client:
        text = error_text(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM qdl_opec LIMIT 2"}
            )
        )
    assert "[SUBSCRIPTION]" in text
    assert "qdl_opec" in text and "ndl_query_table" in text and "SHOW TABLES" in text
    assert API_KEY not in text


async def test_syntax_and_missing_table_errors(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    errors = iter(
        [
            {
                "message": "line 1:8: mismatched input 'FROM'",
                "errorName": "SYNTAX_ERROR",
            },
            {
                "message": "line 1:15: Table 'main.huron.ndaq_rtat11' does not exist",
                "errorName": "TABLE_NOT_FOUND",
            },
            {
                "message": "line 1:15: Schema 'ndaq' does not exist",
                "errorName": "SCHEMA_NOT_FOUND",
            },
        ]
    )

    def handler(sql: str) -> list[dict[str, Any]]:
        return [{"error": next(errors), "stats": {"state": "FAILED"}}]

    fake.sql_handler = handler
    async with make_client() as client:
        syntax = error_text(
            await client.call_tool("ndl_sql_query", {"sql": "SELECT FROM ndaq_rtat10"})
        )
        missing = error_text(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq_rtat11"}
            )
        )
    assert "[INVALID_REQUEST]" in syntax and "SYNTAX_ERROR" in syntax
    assert "SHOW TABLES" not in syntax
    assert "[INVALID_REQUEST]" in missing and "TABLE_NOT_FOUND" in missing
    assert "ndaq_rtat10" in missing and "SHOW TABLES" in missing
    async with make_client() as client:
        schema = error_text(
            await client.call_tool(
                "ndl_sql_query", {"sql": "SELECT * FROM ndaq.rtat10"}
            )
        )
    assert "SCHEMA_NOT_FOUND" in schema and "ndaq_rtat10" in schema


async def test_max_rows_is_validated(make_client: ClientFactory) -> None:
    async with make_client() as client:
        result = await client.call_tool(
            "ndl_sql_query", {"sql": "SELECT 1", "limit": 5000}
        )
    assert result.is_error


async def test_missing_key_is_reported() -> None:
    server = create_server(Settings(api_key=None, toolsets=("sql",)))
    async with Client(server) as client:
        text = error_text(
            await client.call_tool("ndl_sql_query", {"sql": "SHOW TABLES"})
        )
    assert "[AUTH]" in text and "NASDAQ_DATA_LINK_API_KEY" in text


# ------------------------------------------------------------ security guards


@pytest.mark.parametrize(
    "sql",
    [
        # Trino ends `--` comments at \r: the guard must not be fooled by it.
        "--\rSET SESSION query_max_run_time = '1h' /*\nSELECT */",
        "SELECT 1 --\rDROP TABLE x",
        "SELECT\x0b1",
        "SELECT current_user",
        "SELECT reverse(CURRENT_USER)",
        "SELECT session_user",
        "SELECT * FROM system.runtime.queries",
        'SELECT * FROM "system"."runtime"."queries"',
        "SELECT * FROM main . runtime . tasks",
    ],
)
def test_guard_rejects_bypasses_and_identity_reads(sql: str) -> None:
    with pytest.raises(InvalidRequestError):
        read_only_statement(sql)


def test_guard_allows_identity_words_inside_strings() -> None:
    assert read_only_statement("SELECT 'current_user' AS label") == (
        "SELECT 'current_user' AS label"
    )


async def test_api_key_is_redacted_from_sql_rows(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    import base64

    encoded = base64.b64encode(API_KEY.encode()).decode().rstrip("=")
    fake.sql_handler = lambda sql: [
        {
            "columns": [
                {"name": "a", "type": "varchar"},
                {"name": "b", "type": "varchar"},
            ],
            "data": [[API_KEY, API_KEY[::-1]], [encoded, API_KEY.encode().hex()]],
            "stats": {"state": "FINISHED"},
        }
    ]
    async with make_client() as client:
        result = await client.call_tool("ndl_sql_query", {"sql": "SELECT a, b FROM t"})
    text = result.content[0].text  # type: ignore[union-attr]
    for form in (API_KEY, API_KEY[::-1], encoded, API_KEY.encode().hex()):
        assert form not in text
        assert form not in str(result.structured_content)
    assert "<redacted>" in text


async def test_unknown_arguments_are_rejected(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    async with make_client() as client:
        result = await client.call_tool(
            "ndl_sql_query", {"sql": "SHOW TABLES", "max_rows": 5}
        )
    assert result.is_error
    assert "max_rows" in result.content[0].text  # type: ignore[union-attr]
