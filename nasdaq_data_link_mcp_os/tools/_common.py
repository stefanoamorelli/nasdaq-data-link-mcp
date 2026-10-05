"""Shared building blocks for tool modules.

A tool module defines plain functions (sync or async, taking ``ctx: Context`` when
they need the API) and exposes them as a ``TOOLSET``. Registration wraps every
function so that client errors reach the model as ``ToolError`` text with a
short label (the SDK otherwise hides the message of unexpected exceptions).
"""

from __future__ import annotations

import base64
import functools
import inspect
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from nasdaq_data_link_mcp_os.catalog import ACCESS_NOTES, Catalog
from nasdaq_data_link_mcp_os.client import (
    CALL_DEADLINE,
    MAX_PAGE_SIZE,
    NasdaqDataLinkClient,
    TableMetadata,
    normalize_table_code,
)
from nasdaq_data_link_mcp_os.config import HARD_MAX_LIMIT, Settings
from nasdaq_data_link_mcp_os.errors import (
    InvalidRequestError,
    NdlError,
    TableNotFoundError,
    to_tool_error,
)
from nasdaq_data_link_mcp_os.query import (
    build_column_params,
    build_filter_params,
    check_date,
    sort_rows_by,
)
from nasdaq_data_link_mcp_os.results import ColumnInfo, TableResult, fit_rows

STALE_AFTER_DAYS = 45
# Pages a sorting/filtering read may follow before working on what it has.
# Nasdaq serves rows in key blocks (e.g. one ticker after another), so a
# single page can miss whole tickers of a multi-ticker request.
SCAN_MAX_PAGES = 3

READ_ONLY_REMOTE = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

# --------------------------------------------------------------------- state


@dataclass
class AppState:
    settings: Settings
    client: NasdaqDataLinkClient
    catalog: Catalog
    toolsets: list[str] = field(default_factory=list)
    # Table code -> names of the enabled typed tools that read it.
    table_tools: dict[str, list[str]] = field(default_factory=dict)


def app_state(ctx: Context) -> AppState:
    state = ctx.request_context.lifespan_context
    assert isinstance(state, AppState)  # noqa: S101 - set by the server lifespan
    return state


# ------------------------------------------------------------------ toolsets


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable[..., Any]
    title: str
    local: bool = False  # True when the tool never calls Nasdaq
    tables: tuple[str, ...] = ()  # VENDOR/TABLE codes the tool reads


@dataclass(frozen=True)
class PromptSpec:
    fn: Callable[..., Any]
    title: str


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str
    tools: tuple[ToolSpec, ...] = field(default_factory=tuple)
    prompts: tuple[PromptSpec, ...] = field(default_factory=tuple)
    # One-line routing hints added to the server instructions when enabled.
    hints: tuple[str, ...] = ()


def secret_variants(secret: str | None) -> list[str]:
    """Encodings of the API key that must never reach the model."""
    if not secret:
        return []
    raw = secret.encode()
    forms = {
        secret,
        secret[::-1],
        secret.lower(),
        secret.upper(),
        raw.hex(),
        raw.hex().upper(),
        base64.b64encode(raw).decode().rstrip("="),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
    }
    return sorted((f for f in forms if len(f) >= 8), key=len, reverse=True)


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret in value:
                value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


def redact_result(result: Any, secrets: Sequence[str]) -> Any:
    """Remove the API key from a tool result, whatever produced it."""
    if not secrets or not isinstance(result, CallToolResult):
        return result
    content = [
        TextContent(type="text", text=_redact(block.text, secrets))
        if isinstance(block, TextContent)
        else block
        for block in result.content
    ]
    structured = (
        _redact(result.structured_content, secrets)
        if result.structured_content is not None
        else None
    )
    return result.model_copy(
        update={"content": content, "structured_content": structured}
    )


def wrap_tool(
    fn: Callable[..., Any],
    *,
    deadline_seconds: float | None = None,
    secret: str | None = None,
) -> Callable[..., Any]:
    """Wrap a tool function for registration.

    - client errors become ToolError text with a short label (the SDK hides
      the message of any other exception);
    - async tools get an overall deadline, so a stalled upstream ends in a
      clear error before the MCP client gives up;
    - the API key is redacted from results and error messages.
    """
    secrets = secret_variants(secret)

    def fail(message: str) -> ToolError:
        return ToolError(_redact(message, secrets))

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            token = CALL_DEADLINE.set(
                time.monotonic() + deadline_seconds if deadline_seconds else None
            )
            try:
                if deadline_seconds:
                    with anyio.fail_after(deadline_seconds):
                        result = await fn(*args, **kwargs)
                else:
                    result = await fn(*args, **kwargs)
            except NdlError as exc:
                raise fail(str(to_tool_error(exc))) from None
            except TimeoutError:
                raise fail(
                    f"[UPSTREAM] The call did not finish within {deadline_seconds}s "
                    "(Nasdaq Data Link is slow or rate limiting). Narrow the "
                    "request or retry shortly."
                ) from None
            except ToolError as exc:
                raise fail(str(exc)) from None
            finally:
                CALL_DEADLINE.reset(token)
            return redact_result(result, secrets)

        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = fn(*args, **kwargs)
        except NdlError as exc:
            raise fail(str(to_tool_error(exc))) from None
        except ToolError as exc:
            raise fail(str(exc)) from None
        return redact_result(result, secrets)

    return sync_wrapper


# ---------------------------------------------------------- parameter types

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

TableCodeArg = Annotated[
    str,
    Field(
        description="Table code as VENDOR/TABLE, e.g. 'NDAQ/RTAT10' or 'WB/DATA'.",
        examples=["NDAQ/RTAT10", "WB/DATA", "SHARADAR/SF1"],
    ),
]
StartDateArg = Annotated[
    str | None,
    Field(description="Earliest date to include, YYYY-MM-DD.", pattern=DATE_PATTERN),
]
EndDateArg = Annotated[
    str | None,
    Field(description="Latest date to include, YYYY-MM-DD.", pattern=DATE_PATTERN),
]
YearOrDatePattern = r"^\d{4}(-\d{2}-\d{2})?$"
StartYearOrDateArg = Annotated[
    str | None,
    Field(
        description="Earliest period: YYYY or YYYY-MM-DD.", pattern=YearOrDatePattern
    ),
]
EndYearOrDateArg = Annotated[
    str | None,
    Field(description="Latest period: YYYY or YYYY-MM-DD.", pattern=YearOrDatePattern),
]
LimitArg = Annotated[
    int | None,
    Field(
        ge=1,
        le=HARD_MAX_LIMIT,
        description="Maximum rows to return (default 100, max 1000).",
    ),
]
TickersArg = Annotated[
    str | list[str],
    Field(
        description="One ticker or a list of tickers ('AAPL', ['AAPL', 'MSFT'] or "
        "'AAPL,MSFT').",
        examples=["AAPL", ["AAPL", "MSFT"]],
    ),
]
OptionalTickersArg = Annotated[
    str | list[str] | None,
    Field(description="Optional ticker or list of tickers to restrict the results to."),
]


def as_list(value: str | Sequence[str] | None, *, upper: bool = True) -> list[str]:
    """Normalize 'A,B', ['A', 'B'] or None into a de-duplicated list."""
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    cleaned = [str(v).strip() for v in items if str(v).strip()]
    if upper:
        cleaned = [v.upper() for v in cleaned]
    return list(dict.fromkeys(cleaned))


def period_bounds(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """Expand YYYY / YYYY-MM-DD bounds to full dates (Jan 1 / Dec 31 for years)."""
    lo = f"{start}-01-01" if start and len(start) == 4 else start
    hi = f"{end}-12-31" if end and len(end) == 4 else end
    if lo:
        check_date("start_date", lo)
    if hi:
        check_date("end_date", hi)
    if lo and hi and lo > hi:
        raise InvalidRequestError(f"start {start} is after end {end}.")
    return lo, hi


def date_range(column: str, start: str | None, end: str | None) -> dict[str, str]:
    """Filters for an inclusive date range on ``column``."""
    filters: dict[str, str] = {}
    if start:
        filters[f"{column}.gte"] = check_date(column, start)
    if end:
        filters[f"{column}.lte"] = check_date(column, end)
    if start and end and start[:10] > end[:10]:
        raise InvalidRequestError(f"start date {start} is after end date {end}.")
    return filters


# ------------------------------------------------------------ table access


async def get_metadata(state: AppState, code: str) -> TableMetadata | None:
    """Metadata used for validation. Missing tables raise; other failures don't."""
    try:
        return await state.client.get_metadata(code)
    except TableNotFoundError:
        if state.catalog.is_known_missing(code):
            raise TableNotFoundError(
                f"Table {code} was retired by Nasdaq. Use ndl_search_tables to find "
                "a current table."
            ) from None
        raise
    except InvalidRequestError:
        return None


def stale_note(refreshed_at: str | None) -> str | None:
    """A caveat when Nasdaq has not refreshed a table for a while, else None."""
    if not refreshed_at:
        return None
    try:
        when = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - when).days
    if age > STALE_AFTER_DAYS:
        return (
            f"Nasdaq last refreshed this table on {when.date().isoformat()} "
            f"({age} days ago); recent periods may be missing."
        )
    return None


def access_for(state: AppState, code: str, metadata: TableMetadata | None) -> str:
    entry = state.catalog.get(code)
    if entry is not None:
        return entry.access
    if metadata is not None and metadata.premium is False:
        return "free"
    return "unknown"


SortSpec = str | Sequence[str | tuple[str, bool]] | None


def sort_keys(sort_by: SortSpec, descending: bool = False) -> list[tuple[str, bool]]:
    """Normalize ``"date"`` or ``[("date", True), "ticker"]`` to (column, desc)."""
    if not sort_by:
        return []
    items = [sort_by] if isinstance(sort_by, str) else list(sort_by)
    return [
        (item, descending) if isinstance(item, str) else (item[0], bool(item[1]))
        for item in items
    ]


@dataclass
class TableRead:
    """Rows read from one table, before local filtering, sorting and limits."""

    code: str
    metadata: TableMetadata | None
    columns: list[ColumnInfo]
    rows: list[list[Any]]
    request: dict[str, Any]
    next_cursor: str | None
    page_size: int

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def records(self, rows: Sequence[list[Any]] | None = None) -> list[dict[str, Any]]:
        names = self.column_names
        source = self.rows if rows is None else rows
        return [dict(zip(names, row, strict=False)) for row in source]


async def read_table(
    ctx: Context,
    code: str,
    *,
    filters: Mapping[str, Any] | None = None,
    columns: Sequence[str] | None = None,
    page_size: int = MAX_PAGE_SIZE,
    cursor: str | None = None,
    max_pages: int = 1,
    use_cache: bool = True,
    validate: bool = True,
) -> TableRead:
    """Validate and read up to ``max_pages`` pages, with no limit or size budget.

    For tools that filter, merge or rank rows locally before building a result
    with :func:`build_result`. ``next_cursor`` is set when more pages remain.
    ``validate=False`` skips the metadata request; use it only for internal
    lookups whose filters and columns are fixed in code.
    """
    state = app_state(ctx)
    code = normalize_table_code(code)
    metadata = await get_metadata(state, code) if validate else None
    params = build_filter_params(filters, metadata)
    params += build_column_params(columns, metadata)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    base = [*params, ("qopts.per_page", str(page_size))]
    rows: list[list[Any]] = []
    page_columns: list[ColumnInfo] | None = None
    next_cursor = cursor
    for _ in range(max(1, max_pages)):
        page_params = list(base)
        if next_cursor:
            page_params.append(("qopts.cursor_id", next_cursor))
        page = await state.client.get_table_page(code, page_params, use_cache=use_cache)
        if page_columns is None:
            page_columns = [ColumnInfo(name=c.name, type=c.type) for c in page.columns]
        rows.extend(page.rows)
        next_cursor = page.next_cursor
        if not next_cursor:
            break
    request: dict[str, Any] = {k: v for k, v in params if not k.startswith("qopts.")}
    if columns:
        request["columns"] = list(columns)
    return TableRead(
        code=code,
        metadata=metadata,
        columns=page_columns or [],
        rows=rows,
        request=request,
        next_cursor=next_cursor,
        page_size=page_size,
    )


def _missing_values(
    read: TableRead, rows: list[list[Any]], names: list[str]
) -> list[str]:
    """Requested OR-list filter values with no row in a truncated read.

    ``names`` describes the layout of ``rows``, which a tool may have reshaped.
    """
    out: list[str] = []
    for key, value in read.request.items():
        if "." in key or not isinstance(value, str) or "," not in value:
            continue
        if key not in names:
            continue
        index = names.index(key)
        seen = {str(row[index]).casefold() for row in rows if index < len(row)}
        absent = [v for v in value.split(",") if v.casefold() not in seen]
        if absent:
            out.append(f"{key} {', '.join(absent)}")
    return out


def build_result(
    ctx: Context,
    read: TableRead,
    rows: list[list[Any]] | None = None,
    *,
    limit: int | None = None,
    columns: list[ColumnInfo] | None = None,
    notes: Sequence[str] = (),
    request: Mapping[str, Any] | None = None,
    next_cursor: str | None = None,
    has_more: bool = False,
    count_note: bool = True,
) -> TableResult:
    """Package rows (``read.rows`` by default) as a TableResult.

    Applies ``limit``, then adds the standard caveats (rows not shown, free-key
    sample, staleness) and trims the output to the response-size budget. Pass
    ``next_cursor`` only when rows are in API order and the caller can resume.
    """
    state = app_state(ctx)
    settings = state.settings
    limit = max(1, min(limit or settings.default_limit, settings.max_limit))
    rows = read.rows if rows is None else rows
    out_notes = list(notes)
    if read.next_cursor and next_cursor is None:
        out_notes.append(
            f"More than {len(read.rows):,} rows matched; only the first "
            f"{len(read.rows):,} returned by Nasdaq were considered. Narrow the "
            "filters."
        )
    elif count_note and len(rows) > limit:
        out_notes.append(f"{len(rows)} rows matched; showing the first {limit}.")
    if read.next_cursor and next_cursor is None:
        layout = [c.name for c in (columns if columns is not None else read.columns)]
        missing = _missing_values(read, rows, layout)
        if missing:
            out_notes.append(
                "Not in the rows read (more matched than one read covers): "
                + "; ".join(missing)
                + ". Ask for these separately or narrow the dates."
            )

    code = read.code
    metadata = read.metadata
    entry = state.catalog.get(code)
    access = access_for(state, code, metadata)
    if access == "sample":
        sample = f" Known free sample: {entry.notes}" if entry and entry.notes else ""
        out_notes.append(f"Sample data: {ACCESS_NOTES['sample']}{sample}")
        if not rows:
            out_notes.append(
                "0 rows: without a subscription to this product, the requested "
                "tickers or dates are probably outside the free sample."
            )
    refreshed_at = metadata.refreshed_at if metadata else None
    stale = stale_note(refreshed_at)
    if stale:
        out_notes.append(stale)

    result = TableResult(
        table=code,
        name=(metadata.name if metadata else None) or (entry.name if entry else None),
        access=access,
        columns=columns if columns is not None else read.columns,
        rows=rows[:limit],
        row_count=min(len(rows), limit),
        has_more=has_more or bool(read.next_cursor) or len(rows) > limit,
        next_cursor=next_cursor,
        refreshed_at=refreshed_at,
        notes=out_notes,
        docs_url=entry.docs_url if entry else None,
        request=dict(read.request if request is None else request),
    )
    return fit_rows(result, settings.max_response_bytes)


async def fetch_table(
    ctx: Context,
    code: str,
    *,
    filters: Mapping[str, Any] | None = None,
    columns: Sequence[str] | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    sort_by: SortSpec = None,
    descending: bool = False,
    row_filter: Callable[[dict[str, Any]], bool] | None = None,
    scan: bool = False,
    scan_size: int = MAX_PAGE_SIZE,
    notes: Sequence[str] = (),
    validate: bool = True,
) -> TableResult:
    """Read rows from a table with validation, size limits and caveat notes.

    ``sort_by`` takes a column or a list of columns / (column, descending)
    pairs; ``row_filter`` drops rows locally (for columns Nasdaq cannot filter).
    Either one implies ``scan``: one API page of up to ``scan_size`` rows (max
    10,000) is read and processed before ``limit`` is applied, because Nasdaq
    returns rows unsorted. Without a scan, ``next_cursor`` pages through the
    table in API order.
    """
    settings = app_state(ctx).settings
    limit = max(1, min(limit or settings.default_limit, settings.max_limit))
    keys = sort_keys(sort_by, descending)
    scan = scan or bool(keys) or row_filter is not None
    if scan and cursor:
        raise InvalidRequestError("`cursor` cannot be combined with sorting.")
    if keys and columns:
        columns = [*columns, *(k for k, _ in keys if k not in columns)]
    read = await read_table(
        ctx,
        code,
        filters=filters,
        columns=columns,
        page_size=max(limit, min(scan_size, MAX_PAGE_SIZE)) if scan else limit,
        cursor=cursor,
        max_pages=SCAN_MAX_PAGES if scan else 1,
        validate=validate,
    )
    rows = read.rows
    if row_filter is not None:
        names = read.column_names
        rows = [r for r in rows if row_filter(dict(zip(names, r, strict=False)))]
    if keys:
        rows = sort_rows_by(read.column_names, rows, keys)
    request = dict(read.request)
    if keys:
        request["sort_by"] = ", ".join(f"{k} {'desc' if d else 'asc'}" for k, d in keys)
    return build_result(
        ctx,
        read,
        rows,
        limit=limit,
        notes=notes,
        request=request,
        next_cursor=None if scan else read.next_cursor,
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
