"""End-to-end check of the installed server against the live Nasdaq Data Link API.

Starts the server the way an MCP client does (a subprocess spoken to over stdio,
through the MCP SDK's stdio client) and checks, with a real API key:

- the server identity, and that exactly the expected 38 tools are listed, each
  read-only, strict about arguments and with an output schema;
- every tool, called with realistic arguments (taken from tests/live): tables a
  free key can read return rows; subscription-only data fails with the
  [SUBSCRIPTION] label; structured_content validates against the tool's output
  schema; the text content is the compact JSON of structured_content; each
  call answers within --max-latency seconds;
- prompts/list plus prompts/get of each prompt, resources/list, the resource
  template, and a read of each resource;
- an unknown argument is rejected, and ndl_check_api_status reports a valid key;
- the API key (also reversed, upper/lower case, hex or base64) appears in no
  response and not in the server's stderr.

It prints a pass/fail table and exits 1 when a check fails (2 on usage errors).
A full run makes about 80 Nasdaq API calls; the count is read from the server's
request log (NDL_LOG_LEVEL=INFO) and printed at the end. The server runs in an
empty temporary directory, so no local .env is read.

Usage:
    uv run python scripts/live_e2e.py
    uv run python scripts/live_e2e.py --only ndl_search_tables,opec
    uv run python scripts/live_e2e.py --mode legacy
    uv run python scripts/live_e2e.py -- docker run --rm -i \\
        -e NASDAQ_DATA_LINK_API_KEY -e NDL_LOG_LEVEL nasdaq-data-link-mcp

Without a command after ``--`` the script starts the ``nasdaq-data-link-mcp``
console script installed next to the running Python interpreter.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import anyio
import jsonschema
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent, Tool

from nasdaq_data_link_mcp_os.catalog import Catalog
from nasdaq_data_link_mcp_os.tools import TOOLSETS

API_KEY_ENV = "NASDAQ_DATA_LINK_API_KEY"
SERVER_NAME = "nasdaq-data-link-mcp"
# The tools this checkout registers; every one of them must have a case below.
EXPECTED_TOOLS = frozenset(
    spec.fn.__name__ for toolset in TOOLSETS.values() for spec in toolset.tools
)
EXPECTED_TOOL_COUNT = len(EXPECTED_TOOLS)
REGISTERED_PROMPTS = frozenset(
    prompt.fn.__name__ for toolset in TOOLSETS.values() for prompt in toolset.prompts
)
EXPECTED_TOOLSETS = len(TOOLSETS)

# Prompt name -> sample arguments, and a string the rendered prompt must contain.
PROMPTS: dict[str, tuple[dict[str, str], str]] = {
    "retail_sentiment_brief": ({"tickers": "TSLA,NVDA", "days": "5"}, "TSLA"),
    "company_snapshot": ({"ticker": "AAPL"}, "AAPL"),
    "fund_snapshot": ({"fund": "LIBAX"}, "LIBAX"),
    "country_economic_profile": ({"country": "Italy"}, "Italy"),
    "cot_positioning_review": ({"contract": "gold"}, "gold"),
    "zillow_housing_snapshot": ({"place": "Austin, TX"}, "Austin, TX"),
}
RESOURCES = ("ndl://catalog", "ndl://guides/query-syntax")
RESOURCE_TEMPLATE = "ndl://catalog/{vendor}/{table}"

COLUMBIA_FUND = "04638b4b-c7d3-490b-a98e-e00cb4eeeb3a"
SUBSCRIPTION = "[SUBSCRIPTION]"

Check = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class Case:
    """One tool call and what it must return."""

    id: str
    tool: str
    args: dict[str, Any]
    error_label: str | None = None  # expected error label, None = success
    nonempty: str | None = "rows"  # list field that must not be empty
    check: Check | None = None


def _rows(n: int) -> Check:
    def check(data: dict[str, Any]) -> None:
        assert data["row_count"] == n, f"row_count {data['row_count']} != {n}"

    return check


def _access(level: str) -> Check:
    def check(data: dict[str, Any]) -> None:
        assert data.get("access") == level, f"access {data.get('access')!r}"

    return check


def _api_status(data: dict[str, Any]) -> None:
    assert data["api_key_configured"] is True, "api_key_configured is not true"
    assert data["api_key_valid"] is True, f"key not valid: {data.get('message')}"
    assert isinstance(data.get("daily_calls_remaining"), int), "no remaining quota"
    assert len(data["enabled_toolsets"]) == EXPECTED_TOOLSETS, data["enabled_toolsets"]


def _export(data: dict[str, Any]) -> None:
    status = data.get("status")
    assert status in {"fresh", "creating", "regenerating"}, f"status {status!r}"
    if status == "fresh":
        assert str(data.get("link", "")).startswith("https://"), "no https link"


def _sql(data: dict[str, Any]) -> None:
    assert data["row_count"] == 5, f"row_count {data['row_count']}"
    assert [c["name"] for c in data["columns"]][:2] == ["date", "ticker"]


CASES: tuple[Case, ...] = (
    # core
    Case("api_status", "ndl_check_api_status", {}, nonempty=None, check=_api_status),
    Case(
        "search_tables",
        "ndl_search_tables",
        {"query": "retail sentiment", "access": "free", "limit": 5},
        nonempty="results",
    ),
    Case(
        "describe_table",
        "ndl_describe_table",
        {"table_code": "NDAQ/RTAT10"},
        nonempty="columns",
    ),
    Case(
        "query_table",
        "ndl_query_table",
        {"table_code": "NDAQ/RTAT10", "filters": {"ticker": "TSLA"}, "limit": 5},
        check=_access("free"),
    ),
    Case(
        "export_table",
        "ndl_export_table",
        {
            "table_code": "NDAQ/RTAT10",
            "filters": {"ticker": "TSLA", "date.gte": "2026-01-01"},
            "wait_seconds": 10,
        },
        nonempty=None,
        check=_export,
    ),
    # sql
    Case(
        "sql_query",
        "ndl_sql_query",
        {
            "sql": "SELECT date, ticker, activity, sentiment FROM ndaq_rtat10 "
            "ORDER BY date DESC, activity DESC LIMIT 5"
        },
        check=_sql,
    ),
    Case(
        "sql_denied",
        "ndl_sql_query",
        {"sql": "SELECT * FROM qdl_opec LIMIT 2"},
        error_label=SUBSCRIPTION,
    ),
    # nasdaq
    Case(
        "retail_activity",
        "ndl_get_retail_trading_activity",
        {"limit": 10},
        check=_rows(10),
    ),
    Case("ticker_changes", "ndl_get_ticker_changes", {"tickers": "FB"}),
    Case(
        "equities360",
        "ndl_get_equities360",
        {"dataset": "statistics", "tickers": "MSFT"},
        error_label=SUBSCRIPTION,
    ),
    # equities
    Case(
        "search_tickers",
        "ndl_search_tickers",
        {"tickers": ["AAPL", "NVDA"]},
        check=_rows(2),
    ),
    Case(
        "fundamentals",
        "ndl_get_fundamentals",
        {"tickers": "AAPL", "start_date": "2022", "end_date": "2023"},
        check=_access("sample"),
    ),
    Case(
        "financial_metrics",
        "ndl_search_financial_metrics",
        {"query": "free cash flow", "limit": 5},
    ),
    Case(
        "stock_prices",
        "ndl_get_stock_prices",
        {"tickers": "AAPL", "start_date": "2018-12-24", "end_date": "2018-12-31"},
        check=_rows(5),
    ),
    Case(
        "valuation",
        "ndl_get_valuation_metrics",
        {"tickers": "AAPL", "start_date": "2018-12-01", "end_date": "2018-12-31"},
        check=_access("sample"),
    ),
    Case(
        "corporate_actions",
        "ndl_get_corporate_actions",
        {"tickers": "AAPL", "actions": ["dividend"], "limit": 4},
    ),
    Case("sp500", "ndl_get_sp500_constituents", {"view": "current"}),
    Case(
        "insiders",
        "ndl_get_insider_transactions",
        {
            "tickers": "AAPL",
            "start_date": "2018-09-04",
            "end_date": "2018-12-31",
            "limit": 10,
        },
    ),
    Case(
        "institutional",
        "ndl_get_institutional_holdings",
        {"dataset": "by_ticker", "tickers": "AAPL"},
        error_label=SUBSCRIPTION,
    ),
    Case(
        "company_events",
        "ndl_get_company_events",
        {"tickers": "AAPL", "start_date": "2025-01-01", "limit": 5},
    ),
    Case(
        "analyst_estimates",
        "ndl_get_analyst_estimates",
        {"tickers": "AAPL", "period_type": "annual"},
    ),
    # funds
    Case(
        "search_funds",
        "ndl_search_mutual_funds",
        {"query": "LIBAX"},
        nonempty="funds",
    ),
    Case(
        "fund_fees",
        "ndl_get_mutual_fund_report",
        {"report": "fees", "tickers": "LIBAX"},
        check=_rows(1),
    ),
    Case(
        "fund_flows",
        "ndl_get_mutual_fund_report",
        {"report": "flows", "fund_ids": COLUMBIA_FUND},
        error_label=SUBSCRIPTION,
    ),
    # world_bank
    Case(
        "wb_search",
        "ndl_search_world_bank_indicators",
        {"query": "GDP", "limit": 5},
        nonempty="results",
    ),
    Case(
        "wb_data",
        "ndl_get_world_bank_data",
        {"indicators": "NY.GDP.MKTP.CD", "countries": "ITA", "start_date": "2020"},
        check=_access("free"),
    ),
    # macro
    Case(
        "imf_weo",
        "ndl_get_imf_weo_data",
        {
            "countries": "USA",
            "indicators": "NGDPD",
            "start_date": "2022",
            "end_date": "2028",
        },
    ),
    Case("bond_yields", "ndl_get_bond_index_yields", {}, check=_rows(27)),
    # commodities
    Case("cot", "ndl_get_cot_report", {"contract": "gold", "limit": 4}, check=_rows(4)),
    Case(
        "jodi",
        "ndl_get_jodi_energy_data",
        {"countries": "USA", "codes": "CRPRKD", "limit": 6},
        check=_rows(6),
    ),
    Case("opec", "ndl_get_opec_basket_price", {"limit": 5}, check=_rows(5)),
    Case(
        "lme",
        "ndl_get_lme_warehouse_stocks",
        {"metals": "CU", "limit": 5},
        check=_rows(5),
    ),
    Case(
        "wasde",
        "ndl_get_wasde_data",
        {"query": "CORN_US_12", "item": "Ending Stocks"},
    ),
    # crypto
    Case(
        "crypto_prices",
        "ndl_get_crypto_prices",
        {"pairs": ["BTCUSD"], "limit": 3},
        check=_rows(3),
    ),
    Case(
        "blockchain",
        "ndl_get_blockchain_metrics",
        {"metrics": ["MKPRU"], "limit": 3},
        check=_rows(3),
    ),
    # housing
    Case(
        "zillow_regions",
        "ndl_search_zillow_regions",
        {"query": "94110"},
        nonempty="results",
    ),
    Case(
        "zillow_data",
        "ndl_get_zillow_data",
        {"indicator": "ZALL", "regions": "10221", "limit": 3},
        check=_rows(3),
    ),
    Case(
        "zillow_indicators",
        "ndl_search_zillow_indicators",
        {"query": "rent"},
        nonempty="indicators",
    ),
    # carbon
    Case(
        "carbon_facilities",
        "ndl_get_carbon_removal_facilities",
        {"country": "finland", "methodology": "Biochar"},
    ),
    Case(
        "carbon_retirements",
        "ndl_get_carbon_removal_data",
        {"dataset": "retirements", "limit": 5},
        check=_rows(5),
    ),
    Case(
        "carbon_prices",
        "ndl_get_carbon_removal_data",
        {"dataset": "reference_prices"},
        error_label=SUBSCRIPTION,
    ),
)


# ------------------------------------------------------------------ results


@dataclass
class Outcome:
    name: str
    ok: bool
    detail: str = ""
    seconds: float | None = None


@dataclass
class Report:
    secrets: dict[str, str]
    outcomes: list[Outcome] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)  # every response, as text

    def safe(self, text: str) -> str:
        for value in sorted(self.secrets.values(), key=len, reverse=True):
            text = text.replace(value, "<redacted>")
        return text

    def add(
        self, name: str, ok: bool, detail: str = "", seconds: float | None = None
    ) -> None:
        detail = self.safe(" ".join(detail.split()))
        self.outcomes.append(Outcome(name, ok, detail, seconds))
        mark = "PASS" if ok else "FAIL"
        took = f" {seconds:5.1f}s" if seconds is not None else ""
        print(f"  {mark}{took}  {name}: {detail[:160]}", flush=True)

    def record(self, *items: Any) -> None:
        for item in items:
            if hasattr(item, "model_dump_json"):
                self.transcript.append(item.model_dump_json(by_alias=True))
            else:
                self.transcript.append(str(item))

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.ok]


def secret_forms(key: str) -> dict[str, str]:
    """Encodings of the key that must not appear anywhere, by name."""
    raw = key.encode()
    forms = {
        "key": key,
        "reversed": key[::-1],
        "lowercase": key.lower(),
        "uppercase": key.upper(),
        "hex": raw.hex(),
        "HEX": raw.hex().upper(),
        "base64": base64.b64encode(raw).decode().rstrip("="),
        "base64url": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "reversed-base64": base64.b64encode(raw[::-1]).decode().rstrip("="),
    }
    return {name: value for name, value in forms.items() if len(value) >= 8}


def leaked_forms(text: str, secrets: dict[str, str]) -> list[str]:
    # Log handlers wrap long lines, so also search with all whitespace removed.
    squashed = re.sub(r"\s+", "", text)
    return sorted(
        name for name, value in secrets.items() if value in text or value in squashed
    )


# ------------------------------------------------------------------- checks


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def result_text(result: CallToolResult) -> str:
    return "\n".join(b.text for b in result.content if isinstance(b, TextContent))


def check_result(case: Case, tool: Tool, result: CallToolResult) -> str:
    """Raise AssertionError on a wrong result; return a one-line summary."""
    text = result_text(result)
    if case.error_label:
        assert result.is_error, f"expected {case.error_label}, got success"
        # The SDK prefixes tool errors with "Error executing tool <name>: ".
        label = re.match(r"(?:Error executing tool \S+: )?(\[[A-Z_]+\])", text)
        found = label.group(1) if label else None
        assert found == case.error_label, f"wrong error: {text[:200]}"
        return text[:120]
    assert not result.is_error, f"tool error: {text[:300]}"
    data = result.structured_content
    assert isinstance(data, dict), "no structured_content"
    assert tool.output_schema, "tool declares no output schema"
    validator_cls = jsonschema.validators.validator_for(tool.output_schema)
    validator_cls.check_schema(tool.output_schema)
    errors = sorted(
        validator_cls(tool.output_schema).iter_errors(data), key=lambda e: e.path
    )
    assert not errors, f"output schema: {errors[0].message[:200]}"
    blocks = result.content
    assert len(blocks) == 1 and isinstance(blocks[0], TextContent), (
        f"expected one text block, got {[b.type for b in blocks]}"
    )
    assert json.loads(text) == data, "text content differs from structured_content"
    assert text == compact_json(json.loads(text)), "text content is not compact JSON"
    if case.nonempty:
        values = data.get(case.nonempty)
        assert isinstance(values, list) and values, f"empty `{case.nonempty}`"
    if case.check:
        case.check(data)
    parts = []
    for key in ("table", "access", "row_count", "result_count", "status"):
        if key in data:
            parts.append(f"{key}={data[key]}")
    if case.nonempty and case.nonempty != "rows":
        parts.append(f"{case.nonempty}={len(data[case.nonempty])}")
    return " ".join(parts) or "ok"


async def run_cases(
    client: Client,
    tools: dict[str, Tool],
    cases: list[Case],
    report: Report,
    max_latency: float,
) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    for case in cases:
        tool = tools.get(case.tool)
        if tool is None:
            report.add(f"call {case.id}", False, f"{case.tool} is not listed")
            continue
        started = time.monotonic()
        try:
            result = await client.call_tool(
                case.tool, case.args, read_timeout_seconds=max_latency + 30
            )
        except (MCPError, TimeoutError, RuntimeError) as exc:
            elapsed = time.monotonic() - started
            report.add(
                f"call {case.id}", False, f"{type(exc).__name__}: {exc}", elapsed
            )
            continue
        elapsed = time.monotonic() - started
        report.record(result)
        try:
            summary = check_result(case, tool, result)
            assert elapsed < max_latency, f"took {elapsed:.1f}s (> {max_latency:.0f}s)"
        except AssertionError as exc:
            report.add(f"call {case.id}", False, str(exc), elapsed)
            continue
        report.add(f"call {case.id}", True, f"{case.tool} {summary}", elapsed)
        if case.tool == "ndl_check_api_status":
            statuses[case.id] = result.structured_content
    return statuses


async def check_listing(client: Client, report: Report) -> dict[str, Tool]:
    info = client.server_info
    name = info.name if info else None
    version = info.version if info else None
    report.add(
        "initialize",
        name == SERVER_NAME and bool(version),
        f"server {name} {version}, protocol {client.protocol_version}",
    )
    listed: list[Tool] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        report.record(page)
        listed.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            break
    names = [t.name for t in listed]
    missing = sorted(EXPECTED_TOOLS - set(names))
    extra = sorted(set(names) - EXPECTED_TOOLS)
    dupes = sorted({n for n in names if names.count(n) > 1})
    report.add(
        "tools/list",
        len(names) == EXPECTED_TOOL_COUNT and not (missing or extra or dupes),
        f"{len(names)} tools (expected {EXPECTED_TOOL_COUNT}); missing={missing} "
        f"extra={extra} duplicates={dupes}",
    )
    problems = []
    for tool in listed:
        if not tool.output_schema:
            problems.append(f"{tool.name}: no output schema")
        if tool.input_schema.get("additionalProperties") is not False:
            problems.append(f"{tool.name}: accepts unknown arguments")
        if not (tool.annotations and tool.annotations.read_only_hint):
            problems.append(f"{tool.name}: not marked read-only")
    toolsets = {(t.meta or {}).get("toolset") for t in listed}
    if len(toolsets) != EXPECTED_TOOLSETS:
        problems.append(f"{len(toolsets)} toolsets: {sorted(map(str, toolsets))}")
    report.add(
        "tool metadata",
        not problems,
        "; ".join(problems)
        or f"all read-only, strict inputs, output schemas, {len(toolsets)} toolsets",
    )
    return {t.name: t for t in listed}


async def check_prompts(client: Client, report: Report) -> None:
    listed = await client.list_prompts()
    report.record(listed)
    names = sorted(p.name for p in listed.prompts)
    report.add(
        "prompts/list",
        names == sorted(REGISTERED_PROMPTS),
        f"{len(names)} prompts: {', '.join(names)}",
    )
    for name, (arguments, expect) in PROMPTS.items():
        if name not in REGISTERED_PROMPTS:
            continue
        try:
            prompt = await client.get_prompt(name, arguments)
        except MCPError as exc:
            report.add(f"prompts/get {name}", False, f"MCPError: {exc}")
            continue
        report.record(prompt)
        text = " ".join(
            m.content.text
            for m in prompt.messages
            if isinstance(m.content, TextContent)
        )
        report.add(
            f"prompts/get {name}",
            bool(prompt.messages) and expect in text,
            f"{len(prompt.messages)} message(s), {len(text)} chars, mentions {expect!r}"
            if expect in text
            else f"rendered prompt lacks {expect!r}",
        )


async def check_resources(client: Client, report: Report) -> None:
    listed = await client.list_resources()
    templates = await client.list_resource_templates()
    report.record(listed, templates)
    uris = sorted(str(r.uri) for r in listed.resources)
    patterns = sorted(t.uri_template for t in templates.resource_templates)
    report.add(
        "resources/list",
        uris == sorted(RESOURCES) and patterns == [RESOURCE_TEMPLATE],
        f"resources {uris}, templates {patterns}",
    )

    def body(result: Any) -> str:
        return "".join(getattr(c, "text", "") for c in result.contents)

    for uri in (*RESOURCES, "ndl://catalog/NDAQ/RTAT10"):
        try:
            result = await client.read_resource(uri)
        except MCPError as exc:
            report.add(f"resources/read {uri}", False, f"MCPError: {exc}")
            continue
        report.record(result)
        text = body(result)
        try:
            if uri == "ndl://catalog":
                data = json.loads(text)
                expected = len(Catalog.load().entries)
                assert data["tables"] == expected, (data["tables"], expected)
                assert data["free_tables"], "no free tables"
                detail = f"{data['tables']} tables, {len(data['free_tables'])} free"
            elif uri.endswith("query-syntax"):
                assert "Tables API" in text and "SUBSCRIPTION" in text
                detail = f"{len(text)} chars of markdown"
            else:
                data = json.loads(text)
                assert data["code"] == "NDAQ/RTAT10", data.get("code")
                assert data["filters"], "no filters"
                detail = f"{data['code']} access={data['access']}"
        except (AssertionError, KeyError, ValueError) as exc:
            report.add(f"resources/read {uri}", False, f"{type(exc).__name__} {exc}")
            continue
        report.add(f"resources/read {uri}", True, detail)

    try:
        missing = await client.read_resource("ndl://catalog/NOPE/NOTATABLE")
    except MCPError as exc:
        report.add("resources/read unknown table", True, f"rejected: {exc}")
    else:
        report.record(missing)
        report.add("resources/read unknown table", False, "returned contents")


async def check_unknown_argument(client: Client, report: Report) -> None:
    arguments = {"query": "gdp", "not_a_parameter": 1}
    try:
        result = await client.call_tool("ndl_search_tables", arguments)
    except MCPError as exc:
        report.add(
            "unknown argument rejected",
            "not_a_parameter" in str(exc),
            f"protocol error: {exc}",
        )
        return
    report.record(result)
    text = result_text(result)
    report.add(
        "unknown argument rejected",
        result.is_error and "not_a_parameter" in text,
        f"isError={result.is_error}: {text[:200]}",
    )


# --------------------------------------------------------------------- main


def select_cases(only: str | None) -> list[Case]:
    # Cases for tools this checkout does not register are skipped.
    available = [c for c in CASES if c.tool in EXPECTED_TOOLS]
    if not only:
        return available
    wanted = {w.strip() for w in only.split(",") if w.strip()}
    chosen = [c for c in available if c.id in wanted or c.tool in wanted]
    unknown = wanted - {c.id for c in chosen} - {c.tool for c in chosen}
    if unknown:
        raise SystemExit(f"--only: no case or tool named {', '.join(sorted(unknown))}")
    # The key check is part of every run.
    if not any(c.tool == "ndl_check_api_status" for c in chosen):
        chosen.insert(0, available[0])
    return chosen


async def run(args: argparse.Namespace, key: str, errlog: TextIO) -> Report:
    report = Report(secrets=secret_forms(key))
    command = args.command or [str(Path(sys.executable).parent / SERVER_NAME)]
    env = {API_KEY_ENV: key, "NDL_LOG_LEVEL": args.log_level}
    for item in args.env:
        name, _, value = item.partition("=")
        env[name] = value
    cases = select_cases(args.only)
    if not args.only:
        uncovered = sorted(EXPECTED_TOOLS - {c.tool for c in cases})
        report.add(
            "every tool has a case",
            not uncovered,
            f"uncovered: {uncovered}" if uncovered else f"{len(cases)} cases",
        )
    print(f"server: {' '.join(command)} (mode={args.mode})", flush=True)
    with tempfile.TemporaryDirectory(prefix="ndl-e2e-") as cwd:
        params = StdioServerParameters(
            command=command[0], args=command[1:], env=env, cwd=cwd
        )
        started = time.monotonic()
        async with Client(
            stdio_client(params, errlog=errlog),
            mode=args.mode,
            read_timeout_seconds=args.max_latency + 30,
        ) as client:
            report.add("connect", True, "stdio session up", time.monotonic() - started)
            tools = await check_listing(client, report)
            await check_prompts(client, report)
            await check_resources(client, report)
            await check_unknown_argument(client, report)
            statuses = await run_cases(client, tools, cases, report, args.max_latency)
            if statuses and len(cases) > 1:
                last = await client.call_tool("ndl_check_api_status", {})
                report.record(last)
                first = next(iter(statuses.values()))
                after = (last.structured_content or {}).get("daily_calls_remaining")
                before = first.get("daily_calls_remaining")
                if isinstance(before, int) and isinstance(after, int):
                    print(
                        f"  info: daily quota {before} -> {after} "
                        "(shared with anything else using the key)",
                        flush=True,
                    )
    return report


def finish(report: Report, stderr_text: str, json_path: Path | None) -> int:
    calls = stderr_text.count("HTTP Request:")
    leaks = leaked_forms("\n".join(report.transcript), report.secrets)
    report.add(
        "API key absent from responses",
        not leaks,
        f"forms found: {leaks}" if leaks else f"{len(report.transcript)} responses",
    )
    leaks = leaked_forms(stderr_text, report.secrets)
    report.add(
        "API key absent from server stderr",
        not leaks,
        f"forms found: {leaks}" if leaks else f"{len(stderr_text)} chars scanned",
    )
    tracebacks = stderr_text.count("Traceback")
    report.add(
        "no tracebacks on server stderr",
        tracebacks == 0,
        f"{tracebacks} traceback(s)",
    )

    width = max(len(o.name) for o in report.outcomes)
    print()
    print(f"{'CHECK':<{width}}  RESULT  SECONDS  DETAIL")
    for o in report.outcomes:
        took = f"{o.seconds:7.1f}" if o.seconds is not None else " " * 7
        result = "PASS" if o.ok else "FAIL"
        print(f"{o.name:<{width}}  {result:<6}  {took}  {o.detail[:110]}")
    passed = len(report.outcomes) - len(report.failed)
    print(
        f"\n{passed}/{len(report.outcomes)} checks passed; "
        f"{calls} Nasdaq API requests logged by the server."
    )
    if json_path:
        json_path.write_text(
            json.dumps(
                {
                    "passed": not report.failed,
                    "api_requests": calls,
                    "checks": [o.__dict__ for o in report.outcomes],
                },
                indent=2,
            )
        )
    return 1 if report.failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    parser.add_argument(
        "--only",
        help="Comma-separated case ids or tool names to call (default: all).",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        help="MCP client mode: auto (default), legacy (2025-11-25 initialize "
        "handshake) or a protocol version.",
    )
    parser.add_argument(
        "--max-latency",
        type=float,
        default=45.0,
        help="Maximum seconds per tool call (default 45).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="NDL_LOG_LEVEL for the server; INFO logs each Nasdaq request.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Extra environment variable for the server (repeatable).",
    )
    parser.add_argument("--json", type=Path, help="Also write the results here.")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Server command after '--' (default: the installed console script).",
    )
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        print("NASDAQ_DATA_LINK_API_KEY is not set; this script needs a real key.")
        raise SystemExit(2)

    with tempfile.TemporaryFile("w+", encoding="utf-8") as errlog:
        try:
            report = anyio.run(run, args, key, errlog)
        except Exception as exc:  # report, then fail
            errlog.seek(0)
            safe = Report(secret_forms(key)).safe
            tail = errlog.read()[-2000:]
            print(
                f"FAIL: the session ended early: {safe(f'{type(exc).__name__}: {exc}')}"
            )
            print(f"server stderr (last 2000 chars):\n{safe(tail)}")
            raise SystemExit(1) from None
        errlog.seek(0)
        stderr_text = errlog.read()
    raise SystemExit(finish(report, stderr_text, args.json))


if __name__ == "__main__":
    main()
