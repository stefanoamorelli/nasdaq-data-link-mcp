"""Async client for the Nasdaq Data Link Tables API and DataLink SQL.

The official ``nasdaq-data-link`` SDK is not used: its last release dates from
2022, it has no request timeout, it targets the retired time-series API, and it
writes the API key into some exception messages. The REST surface this server
needs is small, so it is called directly.
"""

from __future__ import annotations

import random
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import anyio
import httpx2

from nasdaq_data_link_mcp_os import __version__
from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.errors import (
    BlockedError,
    InvalidRequestError,
    MissingApiKeyError,
    NdlError,
    RateLimitError,
    SubscriptionRequiredError,
    UpstreamError,
    error_from_response,
    redact,
)

Params = Sequence[tuple[str, str]]

TABLE_CODE_RE = re.compile(r"^[A-Z0-9_]+/[A-Z0-9_]+$")
MAX_PAGE_SIZE = 10_000
CACHE_MAX_BYTES = 64 * 1024 * 1024
# A Retry-After longer than this is reported to the model instead of waited out.
MAX_RETRY_WAIT_SECONDS = 10.0

# Monotonic deadline of the tool call in progress (set by the tool wrapper).
# Requests shorten their timeout to fit and skip retries that cannot finish.
CALL_DEADLINE: ContextVar[float | None] = ContextVar("ndl_call_deadline", default=None)


def normalize_table_code(code: str) -> str:
    """Upper-case and validate a ``VENDOR/TABLE`` code."""
    cleaned = (code or "").strip().upper()
    if not TABLE_CODE_RE.match(cleaned):
        raise InvalidRequestError(
            f"{code!r} is not a table code. Codes look like VENDOR/TABLE, for "
            "example NDAQ/RTAT10 or WB/DATA; use ndl_search_tables to find one."
        )
    return cleaned


@dataclass(frozen=True)
class Column:
    name: str
    type: str | None = None


@dataclass
class TablePage:
    code: str
    columns: list[Column]
    rows: list[list[Any]]
    next_cursor: str | None


@dataclass
class TableMetadata:
    code: str
    name: str | None
    description: str | None
    columns: list[Column]
    filters: list[str]
    primary_key: list[str]
    premium: bool | None
    refreshed_at: str | None
    update_frequency: str | None
    status: str | None

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column_type(self, name: str) -> str | None:
        for column in self.columns:
            if column.name == name:
                return column.type
        return None


@dataclass
class ExportStatus:
    code: str
    status: str | None
    link: str | None
    data_snapshot_time: str | None
    last_refreshed_time: str | None


@dataclass
class SqlResult:
    columns: list[Column]
    rows: list[list[Any]]
    truncated: bool
    state: str | None


@dataclass
class RateLimitInfo:
    limit: int | None = None
    remaining: int | None = None


class _TTLCache:
    """LRU cache with per-entry expiry, bounded by entry count and payload bytes."""

    def __init__(
        self, maxsize: int, clock: Callable[[], float], max_bytes: int = CACHE_MAX_BYTES
    ) -> None:
        self._data: OrderedDict[Any, tuple[float, int, Any]] = OrderedDict()
        self._maxsize = maxsize
        self._max_bytes = max_bytes
        self._bytes = 0
        self._clock = clock

    def get(self, key: Any) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, _size, value = item
        if expires < self._clock():
            self._drop(key)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any, ttl: float, size: int = 0) -> None:
        if ttl <= 0 or size > self._max_bytes // 4:
            return
        self._drop(key)
        now = self._clock()
        for stale in [k for k, (exp, _, _) in self._data.items() if exp < now]:
            self._drop(stale)
        self._data[key] = (now + ttl, size, value)
        self._bytes += size
        while len(self._data) > self._maxsize or self._bytes > self._max_bytes:
            self._drop(next(iter(self._data)))

    def _drop(self, key: Any) -> None:
        item = self._data.pop(key, None)
        if item is not None:
            self._bytes -= item[1]

    def clear(self) -> None:
        self._data.clear()
        self._bytes = 0


def _retry_after(response: httpx2.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class NasdaqDataLinkClient:
    """Thin async wrapper over the REST endpoints the tools use."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._http = httpx2.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx2.Timeout(settings.timeout_seconds),
            transport=transport,
            headers={
                "User-Agent": f"nasdaq-data-link-mcp/{__version__}",
                "Accept": "application/json",
            },
            follow_redirects=False,
        )
        self._sleep = sleep or anyio.sleep
        self._cache = _TTLCache(maxsize=256, clock=clock)
        self._limiter: anyio.Semaphore | None = None
        self.rate_limit = RateLimitInfo()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> NasdaqDataLinkClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ public

    async def get_table_page(
        self, code: str, params: Params = (), *, use_cache: bool = True
    ) -> TablePage:
        """Fetch one page of a table. ``params`` are already-encoded query pairs."""
        code = normalize_table_code(code)
        ttl = self.settings.data_cache_ttl if use_cache else 0.0
        payload = await self._get_json(
            f"/api/v3/datatables/{code}.json", params, ttl=ttl, table=code
        )
        table = payload.get("datatable") or {}
        columns = [
            Column(str(c.get("name")), c.get("type"))
            for c in table.get("columns") or []
        ]
        meta = payload.get("meta") or {}
        return TablePage(
            code=code,
            columns=columns,
            rows=list(table.get("data") or []),
            next_cursor=meta.get("next_cursor_id") or None,
        )

    async def get_metadata(self, code: str) -> TableMetadata:
        """Fetch a table's schema. Works even for tables the key cannot read."""
        code = normalize_table_code(code)
        payload = await self._get_json(
            f"/api/v3/datatables/{code}/metadata",
            (),
            ttl=self.settings.metadata_cache_ttl,
            table=code,
        )
        table = payload.get("datatable") or {}
        status = table.get("status") or {}
        return TableMetadata(
            code=code,
            name=table.get("name"),
            description=table.get("description"),
            columns=[
                Column(str(c.get("name")), c.get("type"))
                for c in table.get("columns") or []
            ],
            filters=list(table.get("filters") or []),
            primary_key=list(table.get("primary_key") or []),
            premium=table.get("premium"),
            refreshed_at=status.get("refreshed_at"),
            update_frequency=status.get("update_frequency"),
            status=status.get("status"),
        )

    async def export_table(self, code: str, params: Params = ()) -> ExportStatus:
        """Ask Nasdaq to build a zipped CSV export of a (filtered) table."""
        code = normalize_table_code(code)
        payload = await self._get_json(
            f"/api/v3/datatables/{code}.json",
            [*params, ("qopts.export", "true")],
            ttl=0.0,
            table=code,
        )
        bulk = payload.get("datatable_bulk_download") or {}
        file = bulk.get("file") or {}
        table = bulk.get("datatable") or {}
        return ExportStatus(
            code=code,
            status=file.get("status"),
            link=file.get("link"),
            data_snapshot_time=file.get("data_snapshot_time"),
            last_refreshed_time=table.get("last_refreshed_time"),
        )

    async def run_sql(
        self,
        query: str,
        *,
        max_rows: int,
        poll_delay: float = 0.25,
        deadline_seconds: float | None = None,
    ) -> SqlResult:
        """Run a statement on DataLink SQL (Trino) and collect up to ``max_rows``.

        Trino returns results through a chain of ``nextUri`` pages. Polling stops
        once more than ``max_rows`` rows have arrived, or at the deadline; either
        way the query is cancelled server-side, also when the tool call itself
        is cancelled.
        """
        key = self._require_key()
        deadline = (
            self.settings.sql_timeout_seconds
            if deadline_seconds is None
            else deadline_seconds
        )
        headers = {
            "X-Trino-User": key,
            "X-Trino-Catalog": "main",
            "X-Trino-Schema": "huron",
            "X-Trino-Source": "nasdaq-data-link-mcp",
            "Content-Type": "text/plain",
        }
        started = time.monotonic()
        response = await self._send(
            "POST", "/v1/statement", headers=headers, content=query.encode()
        )
        payload = self._parse_json(response, None)
        columns: list[Column] = []
        rows: list[list[Any]] = []
        truncated = False
        next_uri: str | None = None
        try:
            while True:
                error = payload.get("error")
                if error:
                    raise self._sql_error(error, key)
                if not columns and payload.get("columns"):
                    columns = [
                        Column(str(c.get("name")), c.get("type"))
                        for c in payload["columns"]
                    ]
                rows.extend(payload.get("data") or [])
                next_uri = payload.get("nextUri")
                if not next_uri:
                    break
                if not str(next_uri).startswith(self.settings.base_url + "/"):
                    next_uri = None
                    raise UpstreamError(
                        "DataLink SQL returned an unexpected nextUri host."
                    )
                # Trino keeps a nextUri on its last data page, so only a row
                # count above max_rows proves the result is truncated.
                if len(rows) > max_rows:
                    truncated = True
                    break
                if time.monotonic() - started > deadline:
                    raise UpstreamError(
                        f"The SQL query was still running after {deadline:.0f}s and "
                        "was cancelled. Add a LIMIT or filter on partition columns, "
                        "or raise NDL_SQL_TIMEOUT_SECONDS."
                    )
                if not payload.get("data"):
                    await self._sleep(poll_delay)
                response = await self._send("GET", next_uri, headers=headers)
                payload = self._parse_json(response, None)
        except BaseException:
            if next_uri:
                # Shielded so a cancelled call still frees the Trino query, but
                # bounded so the cleanup cannot outlive the call's deadline.
                with anyio.CancelScope(shield=True), anyio.move_on_after(3):
                    await self._cancel_sql(next_uri, headers)
            raise
        if truncated and next_uri:
            await self._cancel_sql(next_uri, headers)
        state = (payload.get("stats") or {}).get("state")
        return SqlResult(
            columns=columns,
            rows=rows[:max_rows],
            truncated=truncated or len(rows) > max_rows,
            state=state,
        )

    def clear_cache(self) -> None:
        self._cache.clear()

    # ----------------------------------------------------------------- helpers

    def _require_key(self) -> str:
        if not self.settings.api_key:
            raise MissingApiKeyError()
        return self.settings.api_key

    async def _get_json(
        self, path: str, params: Params, *, ttl: float, table: str | None
    ) -> dict[str, Any]:
        self._require_key()
        cache_key = (path, tuple(params))
        cached = self._cache.get(cache_key) if ttl > 0 else None
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        response = await self._send("GET", path, params=params, table=table)
        payload = self._parse_json(response, table)
        self._cache.set(cache_key, payload, ttl, size=len(response.content))
        return payload

    def _parse_json(
        self, response: httpx2.Response, table: str | None
    ) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        try:
            payload = response.json()
        except ValueError:
            if "html" in content_type.lower() or response.text.lstrip().startswith("<"):
                raise BlockedError(
                    "Nasdaq's CDN returned an HTML page instead of data. Retry later; "
                    "if it persists the endpoint may have been retired.",
                    status=response.status_code,
                ) from None
            raise UpstreamError(
                "Nasdaq Data Link returned a response that is not JSON.",
                status=response.status_code,
            ) from None
        if not isinstance(payload, dict):
            raise UpstreamError("Nasdaq Data Link returned an unexpected JSON shape.")
        return payload

    def _get_limiter(self) -> anyio.Semaphore:
        # Created lazily so the semaphore binds to the running event loop.
        if self._limiter is None:
            self._limiter = anyio.Semaphore(self.settings.max_concurrency)
        return self._limiter

    def _record_rate_limit(self, response: httpx2.Response) -> None:
        limit = _as_int(response.headers.get("x-ratelimit-limit"))
        remaining = _as_int(response.headers.get("x-ratelimit-remaining"))
        if limit is not None or remaining is not None:
            self.rate_limit = RateLimitInfo(limit=limit, remaining=remaining)

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, 60.0)
        jitter = random.uniform(0, 0.5)  # noqa: S311
        return float(min(2**attempt, 20)) + jitter

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: Params = (),
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        table: str | None = None,
    ) -> httpx2.Response:
        key = self._require_key()
        limiter = self._get_limiter()
        request_headers = {"X-Api-Token": key, **(headers or {})}
        attempt = 0
        deadline = CALL_DEADLINE.get()
        while True:
            error: NdlError
            timeout = self.settings.timeout_seconds
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining < 1.0:
                    raise UpstreamError(
                        "Ran out of time waiting for Nasdaq Data Link. Narrow the "
                        "request or retry shortly."
                    )
                timeout = min(timeout, remaining)
            try:
                async with limiter:
                    response = await self._http.request(
                        method,
                        url,
                        params=list(params) or None,
                        headers=request_headers,
                        content=content,
                        timeout=timeout,
                    )
            except httpx2.TimeoutException:
                error = UpstreamError(
                    f"Nasdaq Data Link did not answer within {timeout:.0f}s. Retry, "
                    "or narrow the query."
                )
            except httpx2.TransportError as exc:
                error = UpstreamError(
                    f"Could not reach Nasdaq Data Link ({type(exc).__name__}). Check "
                    "the network connection."
                )
            else:
                self._record_rate_limit(response)
                if response.status_code < 400:
                    return response
                error = error_from_response(
                    response.status_code,
                    response.text,
                    content_type=response.headers.get("content-type", ""),
                    table=table,
                    retry_after=_retry_after(response),
                    api_key=key,
                )
            retryable = isinstance(error, RateLimitError | UpstreamError)
            if not retryable or attempt >= self.settings.max_retries:
                raise error
            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None and retry_after > MAX_RETRY_WAIT_SECONDS:
                raise error
            delay = self._backoff(attempt, retry_after)
            if deadline is not None and time.monotonic() + delay + 2.0 > deadline:
                raise error
            await self._sleep(delay)
            attempt += 1

    async def _cancel_sql(self, next_uri: str, headers: dict[str, str]) -> None:
        try:
            async with self._get_limiter():
                await self._http.delete(
                    next_uri,
                    headers={"X-Api-Token": self._require_key(), **headers},
                    timeout=3.0,
                )
        except httpx2.HTTPError:
            pass

    def _sql_error(self, error: dict[str, Any], key: str) -> NdlError:
        name = str(error.get("errorName") or "")
        message = redact(str(error.get("message") or "query failed"), key)
        if name == "PERMISSION_DENIED" or "access denied" in message.lower():
            return SubscriptionRequiredError(
                "DataLink SQL denied access to a table in this query; your key is "
                f"not entitled to it. Detail: {message}"
            )
        return InvalidRequestError(f"DataLink SQL error ({name or 'ERROR'}): {message}")
