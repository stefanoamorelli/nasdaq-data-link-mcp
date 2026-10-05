from __future__ import annotations

import json
import re

import pytest
from mcp import Client

from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.server import _build_parser, create_server
from nasdaq_data_link_mcp_os.tools import TOOLSETS, resolve_toolsets
from tests.conftest import ClientFactory, error_text, payload
from tests.fake_nasdaq import API_KEY, FakeNasdaq

pytestmark = pytest.mark.anyio

TOOL_NAME_RE = re.compile(r"^ndl_[a-z0-9_]{3,60}$")


def _rtat10(fake: FakeNasdaq) -> None:
    fake.add_table(
        "NDAQ/RTAT10",
        columns=[
            ("date", "Date"),
            ("ticker", "text"),
            ("activity", "double"),
            ("sentiment", "Integer"),
        ],
        filters=["date", "ticker"],
        primary_key=["date", "ticker"],
        rows=[
            ["2026-10-02", "TSLA", 0.0243, -2],
            ["2026-10-02", "NVDA", 0.0318, 0],
            ["2026-10-01", "MU", 0.0454, 2],
            ["2026-09-30", "TSLA", 0.0301, 1],
        ],
    )


# ----------------------------------------------------------- registry rules


async def test_every_tool_is_described_and_annotated() -> None:
    server = create_server(Settings(api_key=API_KEY))
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    for tool in tools:
        assert TOOL_NAME_RE.match(tool.name), tool.name
        assert tool.title, f"{tool.name} has no title"
        assert tool.description and len(tool.description) > 40, tool.name
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.output_schema, f"{tool.name} has no output schema"
        assert (tool.meta or {}).get("toolset") in TOOLSETS
        for prop, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{prop} has no description"


async def test_toolset_gating() -> None:
    server = create_server(Settings(api_key=API_KEY, toolsets=("sql",)))
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    toolsets = {(t.meta or {}).get("toolset") for t in tools}
    assert toolsets <= {"core", "sql"}
    assert "core" in toolsets


def test_unknown_toolset_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown toolset"):
        resolve_toolsets(["nope"])
    assert resolve_toolsets(None) == list(TOOLSETS)


async def test_instructions_point_to_official_server() -> None:
    server = create_server(Settings(api_key=API_KEY))
    async with Client(server) as client:
        assert "data.nasdaq.com/model-context-protocol" in (client.instructions or "")
        assert client.server_info.version


async def test_resources() -> None:
    server = create_server(Settings(api_key=API_KEY))
    async with Client(server) as client:
        listed = {str(r.uri) for r in (await client.list_resources()).resources}
        assert {"ndl://catalog", "ndl://guides/query-syntax"} <= listed
        overview = await client.read_resource("ndl://catalog")
        data = json.loads(overview.contents[0].text)  # type: ignore[union-attr]
        assert data["by_access"]["free"] > 20
        entry = await client.read_resource("ndl://catalog/NDAQ/RTAT10")
        assert json.loads(entry.contents[0].text)["access"] == "free"  # type: ignore[union-attr]


def test_cli_parser() -> None:
    args = _build_parser().parse_args(
        ["--transport", "streamable-http", "--toolsets", "sql"]
    )
    assert args.transport == "streamable-http"
    assert args.toolsets == "sql"


# ---------------------------------------------------------------- core tools


async def test_search_tables_works_without_api_key() -> None:
    server = create_server(Settings(api_key=None))
    async with Client(server) as client:
        data = payload(
            await client.call_tool(
                "ndl_search_tables",
                {"query": "world bank", "access": "free", "limit": 5},
            )
        )
    assert data["results"]
    assert all(r["access"] == "free" for r in data["results"])


async def test_missing_key_message() -> None:
    server = create_server(Settings(api_key=None))
    async with Client(server) as client:
        text = error_text(
            await client.call_tool("ndl_query_table", {"table_code": "NDAQ/RTAT10"})
        )
    assert "[AUTH]" in text and "NASDAQ_DATA_LINK_API_KEY" in text


async def test_query_table_filters_sorts_and_pages(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _rtat10(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_query_table",
                {
                    "table_code": "ndaq/rtat10",
                    "filters": {"ticker": ["TSLA", "MU"], "date.gte": "2026-10-01"},
                    "sort_by": "activity",
                    "descending": True,
                },
            )
        )
        assert data["access"] == "free"
        assert [r[1] for r in data["rows"]] == ["MU", "TSLA"]
        assert data["request"]["ticker"] == "TSLA,MU"

        first = payload(
            await client.call_tool(
                "ndl_query_table", {"table_code": "NDAQ/RTAT10", "limit": 3}
            )
        )
        assert first["row_count"] == 3 and first["has_more"] and first["next_cursor"]
        second = payload(
            await client.call_tool(
                "ndl_query_table",
                {
                    "table_code": "NDAQ/RTAT10",
                    "limit": 3,
                    "cursor": first["next_cursor"],
                },
            )
        )
        assert second["row_count"] == 1 and not second["has_more"]


async def test_query_table_rejects_bad_filter_without_calling_data(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    _rtat10(fake)
    async with make_client() as client:
        text = error_text(
            await client.call_tool(
                "ndl_query_table",
                {"table_code": "NDAQ/RTAT10", "filters": {"activity": 1}},
            )
        )
    assert "[INVALID_REQUEST]" in text and "date, ticker" in text
    assert fake.data_requests() == []


async def test_query_table_errors(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    fake.add_table(
        "NDAQ/STAT",
        columns=[("symbol", "text")],
        filters=["symbol"],
        premium=True,
        forbidden=True,
    )
    async with make_client() as client:
        missing = error_text(
            await client.call_tool("ndl_query_table", {"table_code": "WIKI/AAPL"})
        )
        retired = error_text(
            await client.call_tool("ndl_query_table", {"table_code": "QOR/STATS"})
        )
        paid = error_text(
            await client.call_tool("ndl_query_table", {"table_code": "NDAQ/STAT"})
        )
        bad = error_text(
            await client.call_tool("ndl_query_table", {"table_code": "AAPL"})
        )
    assert "[NOT_FOUND]" in missing
    assert "retired" in retired
    assert "[SUBSCRIPTION]" in paid
    assert "VENDOR/TABLE" in bad


async def test_sample_tables_carry_a_hint(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    fake.add_table(
        "NDAQ/RTAT",
        columns=[("date", "Date"), ("ticker", "text"), ("activity", "double")],
        filters=["date", "ticker"],
        premium=True,
        rows=[["2016-01-15", "AAPL", 0.01]],
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_query_table",
                {"table_code": "NDAQ/RTAT", "filters": {"ticker": "NVDA"}},
            )
        )
    assert data["access"] == "sample"
    assert data["rows"] == []
    assert any("outside the free sample" in n for n in data["notes"])


async def test_stale_tables_are_flagged(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    fake.add_table(
        "QDL/OPEC",
        columns=[("date", "Date"), ("value", "double")],
        filters=["date"],
        rows=[["2024-01-25", 80.1]],
        refreshed_at="2024-01-26T00:00:00.000Z",
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool("ndl_query_table", {"table_code": "QDL/OPEC"})
        )
    assert any("last refreshed" in n for n in data["notes"])


async def test_response_budget(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    fake.add_table(
        "X/WIDE",
        columns=[("k", "text"), ("blob", "text")],
        filters=["k"],
        rows=[[str(i), "x" * 500] for i in range(300)],
    )
    async with make_client(max_response_bytes=10_000) as client:
        data = payload(
            await client.call_tool(
                "ndl_query_table", {"table_code": "X/WIDE", "limit": 300}
            )
        )
    assert data["row_count"] < 300 and data["has_more"]
    assert len(json.dumps(data)) <= 10_500


async def test_describe_table(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _rtat10(fake)
    async with make_client() as client:
        data = payload(
            await client.call_tool("ndl_describe_table", {"table_code": "NDAQ/RTAT10"})
        )
    assert data["access"] == "free"
    cols = {c["name"]: c for c in data["columns"]}
    assert cols["date"]["filterable"] and cols["date"]["primary_key"]
    assert not cols["activity"]["filterable"]
    assert data["example"]["table_code"] == "NDAQ/RTAT10"


async def test_export_table_polls_until_fresh(
    fake: FakeNasdaq, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rtat10(fake)
    fake.export_responses = [
        {"status": "creating", "link": None},
        {"status": "fresh", "link": "https://s3.example/rtat10.zip"},
    ]

    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("nasdaq_data_link_mcp_os.tools.core.anyio.sleep", no_sleep)
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_export_table",
                {"table_code": "NDAQ/RTAT10", "filters": {"ticker": "TSLA"}},
            )
        )
    assert data["status"] == "fresh"
    assert data["link"] == "https://s3.example/rtat10.zip"
    assert data["request"] == {"ticker": "TSLA"}


async def test_check_api_status(fake: FakeNasdaq, make_client: ClientFactory) -> None:
    _rtat10(fake)
    async with make_client() as client:
        data = payload(await client.call_tool("ndl_check_api_status", {}))
    assert data["api_key_valid"] is True
    assert data["daily_calls_remaining"] == fake.rate_limit_remaining
    assert "core" in data["enabled_toolsets"]


def test_instructions_fit_in_client_limits() -> None:
    from nasdaq_data_link_mcp_os.instructions import build_instructions
    from nasdaq_data_link_mcp_os.tools import routing_hints

    text = build_instructions(routing_hints(TOOLSETS))
    # Claude Code truncates server instructions at 2,048 characters.
    assert len(text) <= 1_900
    assert "never instructions" in text[:400].replace("\n", " ")


async def test_instructions_only_route_to_enabled_tools() -> None:
    server = create_server(Settings(api_key=API_KEY, toolsets=("sql",)))
    async with Client(server) as client:
        text = client.instructions or ""
    assert "Routing" not in text and "ndl_search_tickers" not in text
    assert "ndl_sql_query" in text


async def test_status_does_not_blame_the_key_for_outages(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    import httpx2

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            503, json={"quandl_error": {"code": "QEMx01", "message": "down"}}
        )

    server = create_server(
        Settings(api_key=API_KEY, max_retries=0),
        transport=httpx2.MockTransport(handler),
    )
    async with Client(server) as client:
        data = payload(await client.call_tool("ndl_check_api_status", {}))
    assert "api_key_valid" not in data  # unknown, not false
    assert "[UPSTREAM]" in data["message"]


async def test_truncated_scans_name_missing_values(
    fake: FakeNasdaq, make_client: ClientFactory
) -> None:
    rows = [[f"2026-01-{d:02d}", "ZZZ", 0.1, 1] for d in range(1, 29)] * 400
    rows += [["2026-01-01", "AAA", 0.2, 2]]
    fake.add_table(
        "NDAQ/RTAT10",
        columns=[
            ("date", "Date"),
            ("ticker", "text"),
            ("activity", "double"),
            ("sentiment", "Integer"),
        ],
        filters=["date", "ticker"],
        rows=rows,
    )
    async with make_client() as client:
        data = payload(
            await client.call_tool(
                "ndl_query_table",
                {
                    "table_code": "NDAQ/RTAT10",
                    "filters": {"ticker": ["ZZZ", "AAA"]},
                    "sort_by": "date",
                },
            )
        )
    assert fake.data_requests("NDAQ/RTAT10")  # read across pages
    assert data["row_count"] == 100
    assert not any(
        "Not in the rows read" in n for n in data["notes"]
    )  # 11,201 rows fit 3 pages
