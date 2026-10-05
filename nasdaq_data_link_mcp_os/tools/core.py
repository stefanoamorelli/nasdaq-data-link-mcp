"""Core tools: discover tables, read their schema, query any table, export."""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os import __version__
from nasdaq_data_link_mcp_os.catalog import ACCESS_NOTES
from nasdaq_data_link_mcp_os.client import CALL_DEADLINE, normalize_table_code
from nasdaq_data_link_mcp_os.errors import (
    InvalidApiKeyError,
    InvalidRequestError,
    MissingApiKeyError,
    NdlError,
)
from nasdaq_data_link_mcp_os.query import build_column_params, build_filter_params
from nasdaq_data_link_mcp_os.results import TableResult, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import (
    LimitArg,
    TableCodeArg,
    Toolset,
    ToolSpec,
    access_for,
    app_state,
    fetch_table,
    get_metadata,
)

FiltersArg = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Row filters on the table's filterable columns. Equality: "
            "{'ticker': 'AAPL'}; any of several values: {'ticker': ['AAPL', 'MSFT']}; "
            "ranges with gt/gte/lt/lte: {'date.gte': '2024-01-01', 'date.lte': "
            "'2024-03-31'} or {'date': {'gte': '2024-01-01'}}. Dates are YYYY-MM-DD."
        ),
        examples=[{"ticker": "AAPL", "date.gte": "2024-01-01"}],
    ),
]
ColumnsArg = Annotated[
    list[str] | None,
    Field(
        description="Columns to return (default: all). Fewer columns, smaller output."
    ),
]


# ------------------------------------------------------------------ models


class TableSummary(BaseModel):
    code: str
    name: str
    access: str
    description: str
    tools: list[str] | None = Field(
        default=None, description="Typed tools that read this table."
    )
    notes: str | None = None
    filters: list[str] | None = None
    docs_url: str | None = None


class SearchResult(BaseModel):
    """Catalog matches, best first."""

    query: str
    results: list[TableSummary]
    result_count: int
    catalog_snapshot: str | None = Field(
        default=None, description="Date the bundled table list was last checked."
    )
    access_levels: dict[str, str] = Field(
        description="Meaning of each `access` value for a free API key."
    )


class ColumnDetail(BaseModel):
    name: str
    type: str | None = None
    filterable: bool
    primary_key: bool


class TableDescription(BaseModel):
    """Schema and access information for one table."""

    code: str
    name: str | None = None
    description: str | None = None
    access: str
    access_note: str
    premium: bool | None = None
    columns: list[ColumnDetail]
    filters: list[str]
    primary_key: list[str]
    refreshed_at: str | None = None
    update_frequency: str | None = None
    docs_url: str | None = None
    notes: str | None = None
    tools: list[str] | None = Field(
        default=None, description="Typed tools that read this table."
    )
    example: dict[str, Any] | None = Field(
        default=None, description="A ready-to-use ndl_query_table call."
    )


class ExportResult(BaseModel):
    """Status of a bulk export request."""

    table: str
    status: str | None = Field(
        default=None, description="fresh (ready), creating or regenerating."
    )
    link: str | None = Field(
        default=None,
        description="Download URL of a zipped CSV; expires 30 minutes after issue.",
    )
    data_snapshot_time: str | None = None
    last_refreshed_time: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ApiStatus(BaseModel):
    """Health of the server's connection to Nasdaq Data Link."""

    server_version: str
    api_key_configured: bool
    api_key_valid: bool | None = None
    daily_call_limit: int | None = None
    daily_calls_remaining: int | None = None
    enabled_toolsets: list[str]
    catalog_snapshot: str | None = None
    message: str


# ------------------------------------------------------------------- tools


def ndl_search_tables(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description="Keywords, a vendor or a table code, e.g. 'retail sentiment', "
            "'fundamentals', 'SHARADAR', 'WB/DATA'. Empty lists every table."
        ),
    ] = "",
    access: Annotated[
        Literal["all", "free", "sample", "subscription"],
        Field(
            description="Only tables a free key can read fully ('free'), as a "
            "sample ('sample') or not at all ('subscription')."
        ),
    ] = "all",
    vendor: Annotated[
        str | None,
        Field(
            description="Restrict to one vendor code, e.g. 'NDAQ', 'SHARADAR', 'QDL'."
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum results.")] = 20,
) -> Annotated[CallToolResult, SearchResult]:
    """Search a bundled list of Nasdaq Data Link tables by keyword.

    Nasdaq Data Link has no search API. The list covers the tables this server's
    tools read plus every table a free key reads in full, each with a short
    description and what a free key gets. ndl_describe_table and ndl_query_table
    also accept any VENDOR/TABLE code that is not listed.
    """
    state = app_state(ctx)
    catalog = state.catalog
    entries = catalog.search(
        query, access=None if access == "all" else access, vendor=vendor, limit=limit
    )
    return to_tool_result(
        SearchResult(
            query=query,
            results=[
                TableSummary(**e.summary(), tools=state.table_tools.get(e.code))
                for e in entries
            ],
            result_count=len(entries),
            catalog_snapshot=catalog.generated_at,
            access_levels=ACCESS_NOTES,
        )
    )


async def ndl_describe_table(
    ctx: Context, table_code: TableCodeArg
) -> Annotated[CallToolResult, TableDescription]:
    """Show a table's columns, filterable columns, primary key and freshness.

    Reads the live metadata endpoint, which works even for premium tables your key
    cannot read, and adds what a free key gets when the table is in the bundled
    list.
    """
    state = app_state(ctx)
    code = normalize_table_code(table_code)
    entry = state.catalog.get(code)
    metadata = await get_metadata(state, code)
    access = access_for(state, code, metadata)
    if metadata is None and entry is None:
        raise InvalidRequestError(
            f"No metadata is available for {code}; it may not be a Tables API "
            "table. Use ndl_search_tables to find one."
        )
    source = metadata if metadata and metadata.columns else entry
    filters = list(source.filters) if source else []
    pk = list(source.primary_key) if source else []
    columns = list(metadata.columns) if metadata else []
    example: dict[str, Any] = {"table_code": code, "limit": 10}
    if filters:
        example["filters"] = {filters[0]: "..."}
    return to_tool_result(
        TableDescription(
            code=code,
            name=(metadata.name if metadata else None)
            or (entry.name if entry else None),
            description=(entry.description if entry else None)
            or (metadata.description if metadata else None),
            access=access,
            access_note=ACCESS_NOTES.get(access, ""),
            premium=metadata.premium if metadata else None,
            columns=[
                ColumnDetail(
                    name=c.name,
                    type=c.type,
                    filterable=c.name in filters,
                    primary_key=c.name in pk,
                )
                for c in columns
            ],
            filters=filters,
            primary_key=pk,
            refreshed_at=metadata.refreshed_at if metadata else None,
            update_frequency=metadata.update_frequency if metadata else None,
            docs_url=entry.docs_url if entry else None,
            notes=entry.notes if entry else None,
            tools=state.table_tools.get(code),
            example=example,
        )
    )


async def ndl_query_table(
    ctx: Context,
    table_code: TableCodeArg,
    filters: FiltersArg = None,
    columns: ColumnsArg = None,
    limit: LimitArg = None,
    cursor: Annotated[
        str | None,
        Field(description="`next_cursor` from a previous call, to read the next page."),
    ] = None,
    sort_by: Annotated[
        str | None,
        Field(
            description="Column to sort by, locally (Nasdaq returns rows unsorted). "
            "Reads up to 10,000 matching rows first; cannot be combined with cursor."
        ),
    ] = None,
    descending: Annotated[bool, Field(description="Sort in descending order.")] = False,
) -> Annotated[CallToolResult, TableResult]:
    """Read rows from any Nasdaq Data Link table, with filters and paging.

    Filters only work on a table's filterable columns (see ndl_describe_table).
    Premium tables return a fixed sample to free keys. Results are capped by
    `limit`; follow `next_cursor` for more pages.
    """
    result = await fetch_table(
        ctx,
        table_code,
        filters=filters,
        columns=columns,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        descending=descending,
    )
    return to_tool_result(result)


async def ndl_export_table(
    ctx: Context,
    table_code: TableCodeArg,
    filters: FiltersArg = None,
    columns: ColumnsArg = None,
    wait_seconds: Annotated[
        int,
        Field(
            ge=0,
            le=60,
            description="How long to wait for Nasdaq to finish building the file.",
        ),
    ] = 15,
) -> Annotated[CallToolResult, ExportResult]:
    """Request a full (filtered) table export as a zipped CSV download link.

    For data too large to read through ndl_query_table. Returns a link that
    expires after 30 minutes; nothing is downloaded by the server. Nasdaq limits
    exports to a few per hour per key and applies the same entitlements as
    queries (free keys get sample-sized files for premium tables).
    """
    state = app_state(ctx)
    code = normalize_table_code(table_code)
    metadata = await get_metadata(state, code)
    params = build_filter_params(filters, metadata) + build_column_params(
        columns, metadata
    )
    status = await state.client.export_table(code, params)
    # Stop polling early enough to answer before the call's own deadline.
    deadline = CALL_DEADLINE.get()
    stop_at = time.monotonic() + wait_seconds
    if deadline is not None:
        stop_at = min(stop_at, deadline - 10.0)
    while status.status != "fresh":
        step = min(5.0, stop_at - time.monotonic())
        if step <= 0:
            break
        await anyio.sleep(step)
        status = await state.client.export_table(code, params)
    notes = []
    if status.status != "fresh":
        notes.append(
            "The export is still being built. Call this tool again with the same "
            "arguments in a minute to get the link."
        )
    if access_for(state, code, metadata) == "sample":
        notes.append("Premium table: a free key's export contains only the sample.")
    return to_tool_result(
        ExportResult(
            table=code,
            status=status.status,
            link=status.link if status.status == "fresh" else None,
            data_snapshot_time=status.data_snapshot_time,
            last_refreshed_time=status.last_refreshed_time,
            request=dict(params),
            notes=notes,
        )
    )


async def ndl_check_api_status(ctx: Context) -> Annotated[CallToolResult, ApiStatus]:
    """Check the API key, the remaining daily call quota and the enabled toolsets.

    Makes one small request to a free table. Useful when other tools fail with
    authentication or rate-limit errors.
    """
    state = app_state(ctx)

    def status(message: str, valid: bool | None) -> CallToolResult:
        info = state.client.rate_limit
        return to_tool_result(
            ApiStatus(
                server_version=__version__,
                api_key_configured=state.settings.has_api_key,
                api_key_valid=valid,
                daily_call_limit=info.limit if valid else None,
                daily_calls_remaining=info.remaining if valid else None,
                enabled_toolsets=list(state.toolsets),
                catalog_snapshot=state.catalog.generated_at,
                message=message,
            )
        )

    if not state.settings.has_api_key:
        return status(
            "NASDAQ_DATA_LINK_API_KEY is not set; without it only "
            "ndl_search_tables, prompts and resources work. Get a free key at "
            "https://data.nasdaq.com/sign-up.",
            None,
        )
    try:
        await state.client.get_table_page(
            "NDAQ/RTAT10", [("qopts.per_page", "1")], use_cache=False
        )
    except (InvalidApiKeyError, MissingApiKeyError) as exc:
        return status(f"[{exc.kind}] {exc}", False)
    except NdlError as exc:
        # Rate limits and outages say nothing about the key itself.
        return status(f"[{exc.kind}] {exc} The key could not be checked.", None)
    return status("The API key works.", True)


TOOLSET = Toolset(
    name="core",
    description="Catalog search, table schemas, generic queries, exports. Always on.",
    tools=(
        ToolSpec(ndl_search_tables, "Search Nasdaq Data Link tables", local=True),
        ToolSpec(ndl_describe_table, "Describe a table"),
        ToolSpec(ndl_query_table, "Query a table"),
        ToolSpec(ndl_export_table, "Export a table as CSV"),
        ToolSpec(ndl_check_api_status, "Check API key and quota"),
    ),
)
