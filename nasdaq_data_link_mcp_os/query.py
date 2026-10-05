"""Build Tables API query parameters from tool arguments.

The Tables API accepts equality filters (``ticker=AAPL``), comma-separated OR lists
(``ticker=AAPL,MSFT``) and four range operators (``date.gte=2024-01-01``). Only
columns listed in a table's ``filters`` metadata can be filtered. Anything else is
rejected here with a message that names the valid options, before a request is
spent on it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from nasdaq_data_link_mcp_os.client import TableMetadata
from nasdaq_data_link_mcp_os.errors import InvalidRequestError

RANGE_OPS = ("gt", "gte", "lt", "lte")
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
_DATE_TYPES = ("date", "datetime", "timestamp")


def encode_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def is_date_column(metadata: TableMetadata | None, column: str) -> bool:
    if metadata is None:
        return column in {"date", "calendardate", "datekey", "reportperiod"}
    col_type = (metadata.column_type(column) or "").lower()
    return col_type.startswith(_DATE_TYPES)


def check_date(column: str, value: str) -> str:
    if not _DATE_RE.match(value):
        raise InvalidRequestError(
            f"Filter {column}={value!r}: dates must be written as YYYY-MM-DD "
            "(Nasdaq silently reads 04/10/2026 as April 10)."
        )
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        raise InvalidRequestError(
            f"Filter {column}={value!r} is not a real date."
        ) from None
    return value


def _encode(column: str, value: Any, metadata: TableMetadata | None) -> str:
    if isinstance(value, Mapping):
        raise InvalidRequestError(
            f"Filter {column!r} has a nested value it cannot use."
        )
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InvalidRequestError(
            f"Filter {column!r} has no value; drop it or give a value."
        )
    if isinstance(value, list | tuple | set):
        items = [encode_value(v) for v in value if encode_value(v)]
        if not items:
            raise InvalidRequestError(f"Filter {column!r} has an empty list.")
    else:
        items = [encode_value(value)]
    if is_date_column(metadata, column):
        items = [check_date(column, v) for v in items]
    return ",".join(items)


def _check_column(column: str, metadata: TableMetadata | None) -> None:
    if metadata is None or not metadata.columns:
        return
    if not metadata.filters:
        raise InvalidRequestError(
            f"{metadata.code} has no filterable columns. Drop the filters, or use "
            "ndl_sql_query if your key has SQL access to the table."
        )
    if column not in metadata.filters:
        raise InvalidRequestError(
            f"{column!r} cannot be used as a filter on {metadata.code}. Filterable "
            f"columns: {', '.join(metadata.filters)}. Other columns can only be "
            "selected, not filtered."
        )


def build_filter_params(
    filters: Mapping[str, Any] | None, metadata: TableMetadata | None
) -> list[tuple[str, str]]:
    """Translate ``{"date.gte": "2024-01-01", "ticker": ["A", "B"]}`` into query pairs.

    ``{"date": {"gte": "2024-01-01", "lte": "2024-03-31"}}`` is accepted too.
    """
    params: list[tuple[str, str]] = []
    for raw_key, value in (filters or {}).items():
        key = str(raw_key).strip()
        column, _, op = key.partition(".")
        op = op.lower()
        if not column:
            raise InvalidRequestError(f"Filter key {raw_key!r} has no column name.")
        if op and op not in RANGE_OPS:
            raise InvalidRequestError(
                f"Unsupported operator {op!r} in {key!r}. Nasdaq supports equality "
                "plus gt, gte, lt and lte, e.g. 'date.gte'."
            )
        _check_column(column, metadata)
        if isinstance(value, Mapping):
            if op:
                raise InvalidRequestError(
                    f"Use either '{column}.gte' style keys or a nested mapping for "
                    f"{column!r}, not both."
                )
            for sub_op, sub_value in value.items():
                norm = str(sub_op).strip().lower().lstrip("$.")
                if norm in ("eq", "="):
                    params.append((column, _encode(column, sub_value, metadata)))
                elif norm in RANGE_OPS:
                    if isinstance(sub_value, list | tuple | set):
                        raise InvalidRequestError(
                            f"Range filter {column}.{norm} needs a single value."
                        )
                    params.append(
                        (f"{column}.{norm}", _encode(column, sub_value, metadata))
                    )
                else:
                    raise InvalidRequestError(
                        f"Unsupported operator {sub_op!r} for {column!r}; use gt, gte, "
                        "lt or lte."
                    )
            continue
        if op and isinstance(value, list | tuple | set):
            raise InvalidRequestError(f"Range filter {key!r} needs a single value.")
        params.append(
            (f"{column}.{op}" if op else column, _encode(column, value, metadata))
        )
    return params


def build_column_params(
    columns: Sequence[str] | None, metadata: TableMetadata | None
) -> list[tuple[str, str]]:
    if not columns:
        return []
    wanted = list(dict.fromkeys(c.strip() for c in columns if c and c.strip()))
    if metadata is not None and metadata.columns:
        known = set(metadata.column_names)
        unknown = [c for c in wanted if c not in known]
        if unknown:
            raise InvalidRequestError(
                f"Unknown column(s) for {metadata.code}: {', '.join(unknown)}. Valid "
                f"columns: {', '.join(metadata.column_names)}."
            )
    return [("qopts.columns", ",".join(wanted))] if wanted else []


def sort_rows(
    column_names: Sequence[str], rows: list[list[Any]], by: str, descending: bool
) -> list[list[Any]]:
    """Sort rows by one column. Empty values always go last."""
    try:
        index = list(column_names).index(by)
    except ValueError:
        raise InvalidRequestError(
            f"Cannot sort by {by!r}: it is not among the returned columns "
            f"({', '.join(column_names)})."
        ) from None

    def present(row: list[Any]) -> bool:
        value = row[index] if index < len(row) else None
        return value is not None and not (
            isinstance(value, float) and math.isnan(value)
        )

    filled = [r for r in rows if present(r)]
    empty = [r for r in rows if not present(r)]
    try:
        filled.sort(key=lambda r: r[index], reverse=descending)
    except TypeError:
        filled.sort(key=lambda r: str(r[index]), reverse=descending)
    return filled + empty


def sort_rows_by(
    column_names: Sequence[str],
    rows: list[list[Any]],
    keys: Sequence[tuple[str, bool]],
) -> list[list[Any]]:
    """Sort by several (column, descending) keys; the first key matters most."""
    for column, descending in reversed(keys):
        rows = sort_rows(column_names, rows, column, descending)
    return rows
