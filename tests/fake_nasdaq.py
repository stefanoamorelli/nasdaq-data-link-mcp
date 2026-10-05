"""An in-process stand-in for the Nasdaq Data Link REST API.

It serves table metadata and data through ``httpx2.MockTransport`` and applies
the same filter semantics as the real Tables API (equality, comma OR lists,
gt/gte/lt/lte, qopts.columns, qopts.per_page, cursor paging), so tool tests
exercise real request building without network access.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

import httpx2

API_KEY = "test-key-0123456789"


@dataclass
class FakeTable:
    code: str
    columns: list[tuple[str, str]]
    filters: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    premium: bool = False
    name: str | None = None
    refreshed_at: str = "2099-01-01T00:00:00.000Z"
    forbidden: bool = False  # data calls return 403 QEPx04

    @property
    def column_names(self) -> list[str]:
        return [c for c, _ in self.columns]


def _error(status: int, code: str, message: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"quandl_error": {"code": code, "message": message}}
    )


def _matches(value: Any, op: str, target: str) -> bool:
    if value is None:
        return False
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            cmp_target: Any = float(target)
        except ValueError:
            cmp_target = target
            value = str(value)
    else:
        # The real Tables API compares text case-insensitively.
        value, cmp_target = str(value).casefold(), target.casefold()
    if op == "eq":
        return bool(value == cmp_target)
    return bool(
        {
            "gt": value > cmp_target,
            "gte": value >= cmp_target,
            "lt": value < cmp_target,
            "lte": value <= cmp_target,
        }[op]
    )


class FakeNasdaq:
    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}
        self.requests: list[httpx2.Request] = []
        self.sql_handler: Callable[[str], list[dict[str, Any]]] | None = None
        self.export_responses: list[dict[str, Any]] = []
        self.rate_limit_remaining = 49_000

    # --------------------------------------------------------------- setup

    def add_table(
        self,
        code: str,
        columns: list[tuple[str, str]],
        filters: list[str],
        rows: list[list[Any]] | None = None,
        **kwargs: Any,
    ) -> FakeTable:
        table = FakeTable(
            code=code, columns=columns, filters=filters, rows=rows or [], **kwargs
        )
        self.tables[code] = table
        return table

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def data_requests(self, code: str | None = None) -> list[dict[str, str]]:
        """Query params of data (not metadata) requests, optionally for one table."""
        out = []
        for request in self.requests:
            path = request.url.path
            if not path.endswith(".json") or "/datatables/" not in path:
                continue
            if code and not path.endswith(f"/{code}.json"):
                continue
            out.append(dict(parse_qsl(request.url.query.decode())))
        return out

    # ------------------------------------------------------------- handler

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.headers.get("x-api-token") != API_KEY:
            return _error(
                403, "QEPx04", "A valid API key is required to retrieve data."
            )
        path = request.url.path
        headers = {
            "x-ratelimit-limit": "50000",
            "x-ratelimit-remaining": str(self.rate_limit_remaining),
        }
        if path == "/v1/statement" or path.startswith("/v1/statement/"):
            return self._sql(request)
        prefix = "/api/v3/datatables/"
        if not path.startswith(prefix):
            return _error(400, "QECx01", "Unknown route.")
        rest = path[len(prefix) :]
        if rest.endswith("/metadata"):
            code = rest[: -len("/metadata")]
            table = self.tables.get(code)
            if table is None:
                return _error(
                    404, "QECx02", f"The following datatable '{code}' does not exist."
                )
            return httpx2.Response(200, json=self._metadata(table), headers=headers)
        if rest.endswith(".json"):
            code = rest[: -len(".json")]
            table = self.tables.get(code)
            if table is None:
                return _error(
                    404, "QECx02", f"The following datatable '{code}' does not exist."
                )
            params = parse_qsl(request.url.query.decode())
            if ("qopts.export", "true") in params:
                return self._export(code, headers)
            if table.forbidden:
                return _error(
                    403,
                    "QEPx04",
                    f"You do not have permission to view vendor datatable '{code}'. "
                    "Please subscribe to this database to get access to the data.",
                )
            return self._data(table, params, headers)
        return _error(400, "QECx01", "Unknown route.")

    def _metadata(self, table: FakeTable) -> dict[str, Any]:
        vendor, code = table.code.split("/")
        return {
            "datatable": {
                "vendor_code": vendor,
                "datatable_code": code,
                "name": table.name or table.code,
                "description": None,
                "columns": [{"name": n, "type": t} for n, t in table.columns],
                "filters": table.filters,
                "primary_key": table.primary_key,
                "premium": table.premium,
                "status": {
                    "refreshed_at": table.refreshed_at,
                    "status": "ON TIME",
                    "expected_at": "*",
                    "update_frequency": "DAILY",
                },
                "data_version": {"code": "1", "default": True, "description": None},
            }
        }

    def _data(
        self, table: FakeTable, params: list[tuple[str, str]], headers: dict[str, str]
    ) -> httpx2.Response:
        names = table.column_names
        rows = table.rows
        per_page = 10_000
        cursor = 0
        selected = names
        for key, value in params:
            if key == "qopts.per_page":
                per_page = int(value)
                if per_page > 10_000:
                    return _error(
                        422,
                        "QELx06",
                        "The number of rows per page that you have requested is over "
                        "the maximum limit of '10000' rows per page.",
                    )
                continue
            if key == "qopts.cursor_id":
                cursor = int(base64.b64decode(value).decode())
                continue
            if key == "qopts.columns":
                selected = value.split(",")
                missing = [c for c in selected if c not in names]
                if missing:
                    return _error(
                        403, "QEPx06", f"column '{missing[0]}' does not exist"
                    )
                continue
            if key.startswith("qopts."):
                continue
            column, _, op = key.partition(".")
            if column not in table.filters:
                return _error(
                    422,
                    "QESx08",
                    f"You cannot use the column '{column}' to filter this table.",
                )
            index = names.index(column)
            if op:
                rows = [r for r in rows if _matches(r[index], op, value)]
            else:
                options = value.split(",")
                rows = [
                    r for r in rows if any(_matches(r[index], "eq", o) for o in options)
                ]
        page = rows[cursor : cursor + per_page]
        idx = [names.index(c) for c in selected]
        next_cursor = None
        if cursor + per_page < len(rows):
            next_cursor = base64.b64encode(str(cursor + per_page).encode()).decode()
        body = {
            "datatable": {
                "data": [[r[i] for i in idx] for r in page],
                "columns": [
                    {"name": c, "type": dict(table.columns)[c]} for c in selected
                ],
            },
            "meta": {"next_cursor_id": next_cursor},
        }
        return httpx2.Response(200, content=json.dumps(body).encode(), headers=headers)

    def _export(self, code: str, headers: dict[str, str]) -> httpx2.Response:
        payload = (
            self.export_responses.pop(0)
            if self.export_responses
            else {"status": "fresh", "link": f"https://s3.example/{code}.zip"}
        )
        return httpx2.Response(
            200,
            json={
                "datatable_bulk_download": {
                    "file": {
                        "link": payload.get("link"),
                        "status": payload["status"],
                        "data_snapshot_time": "2026-10-03 00:00:00 UTC",
                    },
                    "datatable": {"last_refreshed_time": "2026-10-03 00:00:00 UTC"},
                }
            },
            headers=headers,
        )

    def _sql(self, request: httpx2.Request) -> httpx2.Response:
        if request.headers.get("x-trino-user") != API_KEY:
            return httpx2.Response(401, text="Unauthorized")
        if request.method == "DELETE":
            return httpx2.Response(204)
        if request.method == "POST":
            if self.sql_handler is None:
                return httpx2.Response(500, text="no sql handler")
            pages = self.sql_handler(request.content.decode())
            self._sql_pages = pages
            return httpx2.Response(200, json=self._sql_page(0))
        index = int(request.url.path.rsplit("/", 1)[-1])
        return httpx2.Response(200, json=self._sql_page(index))

    def _sql_page(self, index: int) -> dict[str, Any]:
        page = dict(self._sql_pages[index])
        if index + 1 < len(self._sql_pages):
            page["nextUri"] = f"https://data.nasdaq.com/v1/statement/q1/{index + 1}"
        return page
