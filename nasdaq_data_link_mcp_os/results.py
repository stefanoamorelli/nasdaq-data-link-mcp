"""Output models shared by the tools, and the helper that serializes them.

Tool results carry the same payload twice: as compact JSON text (what most
clients show the model) and as ``structured_content`` (validated against the
tool's output schema). Pydantic's default text rendering is indented, which
roughly doubles the size, so tools build the ``CallToolResult`` themselves.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str
    type: str | None = None


class TableResult(BaseModel):
    """Rows from one Nasdaq Data Link table."""

    table: str = Field(description="VENDOR/TABLE code that was read.")
    name: str | None = Field(default=None, description="Table name.")
    access: str | None = Field(
        default=None,
        description="What a free API key gets: free, sample, subscription or unknown.",
    )
    columns: list[ColumnInfo] = Field(description="Columns, in row order.")
    rows: list[list[Any]] = Field(description="Row values, aligned with `columns`.")
    row_count: int = Field(description="Number of rows in `rows`.")
    has_more: bool = Field(
        description="True when more rows matched than were returned."
    )
    next_cursor: str | None = Field(
        default=None, description="Pass back as `cursor` to read the next page."
    )
    refreshed_at: str | None = Field(
        default=None, description="When Nasdaq last refreshed the table."
    )
    notes: list[str] = Field(
        default_factory=list, description="Caveats about the data."
    )
    docs_url: str | None = Field(default=None, description="Product page on Nasdaq.")
    request: dict[str, Any] = Field(
        default_factory=dict, description="Filters and options that were sent."
    )


def _clean(value: Any) -> Any:
    """Replace NaN/inf with None and drop None-valued dict keys (not list items)."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        cleaned = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v is not None}
    return value


def dump(model: BaseModel) -> dict[str, Any]:
    return _clean(model.model_dump(mode="json"))  # type: ignore[no-any-return]


def to_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def to_tool_result(model: BaseModel) -> CallToolResult:
    data = dump(model)
    return CallToolResult(
        content=[TextContent(type="text", text=to_json(data))],
        structured_content=data,
    )


_TRIM_NOTE_PREFIX = "Output trimmed to "


def fit_rows(result: TableResult, max_bytes: int) -> TableResult:
    """Drop trailing rows until the serialized result fits in ``max_bytes``.

    Safe to call again on an already trimmed result (for example after a tool
    adds fields): the single trim note keeps the original row count, and its
    own size is part of the budget.
    """
    if len(to_json(dump(result)).encode()) <= max_bytes or not result.rows:
        return result
    # This module owns the note text, so recognising it here is safe.
    previous = [n for n in result.notes if n.startswith(_TRIM_NOTE_PREFIX)]
    notes = [n for n in result.notes if not n.startswith(_TRIM_NOTE_PREFIX)]
    total = result.row_count
    if previous:
        match = re.search(r" of (\d+) rows", previous[0])
        total = int(match.group(1)) if match else total

    def trimmed(kept: int) -> TableResult:
        note = (
            f"{_TRIM_NOTE_PREFIX}{kept} of {total} rows to stay under "
            f"{max_bytes:,} bytes. Select fewer columns or lower `limit` to see more."
        )
        return result.model_copy(
            update={
                "rows": result.rows[:kept],
                "row_count": kept,
                "has_more": True,
                "next_cursor": None,
                "notes": [*notes, note],
            }
        )

    lo, hi = 0, len(result.rows)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(to_json(dump(trimmed(mid))).encode()) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return trimmed(lo)
