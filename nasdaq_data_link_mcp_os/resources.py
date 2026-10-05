"""MCP resources: the bundled table list and reference notes."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from nasdaq_data_link_mcp_os.catalog import ACCESS_LEVELS, ACCESS_NOTES, Catalog
from nasdaq_data_link_mcp_os.instructions import OFFICIAL_MCP_URL

QUERY_GUIDE = """\
# Nasdaq Data Link Tables API: query reference

Table codes look like `VENDOR/TABLE` (for example `NDAQ/RTAT10`, `WB/DATA`).

## Filters (`filters` argument of ndl_query_table / ndl_export_table)

| Want | Write |
|---|---|
| equality | `{"ticker": "AAPL"}` |
| any of several values | `{"ticker": ["AAPL", "MSFT"]}` |
| range | `{"date.gte": "2024-01-01", "date.lte": "2024-03-31"}` |
| range, nested form | `{"date": {"gte": "2024-01-01", "lt": "2024-04-01"}}` |

- Only the columns listed as filterable by ndl_describe_table can be filtered.
- Range operators: `gt`, `gte`, `lt`, `lte`. There is no "not equal".
- Dates are `YYYY-MM-DD`.

## Paging and size

- `limit` caps rows per call (max 1,000); `next_cursor` continues from there.
- Nasdaq returns at most 10,000 rows per request and does not sort them.
  `sort_by` sorts locally after reading up to 10,000 matching rows.
- For bigger extracts use ndl_export_table, which returns a zipped CSV link
  that expires after 30 minutes.

## Limits for a free key

300 calls per 10 seconds, 2,000 per 10 minutes, 50,000 per day, and one
request at a time. The server queues its own requests to stay inside this.

## Errors

| Label | Meaning |
|---|---|
| NOT_FOUND | the table code does not exist |
| SUBSCRIPTION | the key needs a paid subscription for this table |
| INVALID_REQUEST | a filter, column, operator or date was rejected |
| RATE_LIMIT | too many calls; wait and retry |
| AUTH | missing or invalid API key |
| UPSTREAM | Nasdaq timed out or failed; retry or narrow the request |
| BLOCKED | Nasdaq's CDN refused the request (retired endpoint or WAF) |
"""


def register_resources(server: MCPServer, catalog: Catalog) -> None:
    @server.resource(
        "ndl://catalog",
        name="catalog",
        title="Nasdaq Data Link table list overview",
        description="The bundled table list: counts by access level and vendor, "
        "and every free table.",
        mime_type="application/json",
    )
    def catalog_overview() -> str:
        counts = Counter(e.access for e in catalog.entries)
        vendors = catalog.vendors()
        payload: dict[str, Any] = {
            "snapshot": catalog.generated_at,
            "scope": (
                "The tables this server's tools read plus every table a free key "
                "reads in full; ndl_query_table reads any VENDOR/TABLE code."
            ),
            "tables": len(catalog.entries),
            "by_access": {level: counts.get(level, 0) for level in ACCESS_LEVELS},
            "access_levels": ACCESS_NOTES,
            "vendors": dict(vendors.most_common()),
            "free_tables": [e.summary() for e in catalog.entries if e.access == "free"],
            "official_nasdaq_mcp": OFFICIAL_MCP_URL,
        }
        return json.dumps(payload, separators=(",", ":"))

    @server.resource(
        "ndl://catalog/{vendor}/{table}",
        name="catalog-table",
        title="Catalog entry for one table",
        description="Bundled entry (access, filters, notes) for VENDOR/TABLE.",
        mime_type="application/json",
    )
    def catalog_table(vendor: str, table: str) -> str:
        entry = catalog.get(f"{vendor}/{table}")
        if entry is None:
            raise ResourceNotFoundError(
                f"{vendor}/{table} is not in the bundled list; ndl_describe_table "
                "reads any table's schema."
            )
        data = entry.summary() | {
            "primary_key": list(entry.primary_key),
            "refreshed_at_snapshot": entry.refreshed_at,
        }
        return json.dumps(data, separators=(",", ":"))

    @server.resource(
        "ndl://guides/query-syntax",
        name="query-syntax",
        title="Tables API query reference",
        description="Filter syntax, paging, limits and error labels.",
        mime_type="text/markdown",
    )
    def query_syntax() -> str:
        return QUERY_GUIDE
