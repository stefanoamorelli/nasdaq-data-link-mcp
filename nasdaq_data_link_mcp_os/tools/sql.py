"""DataLink SQL (Trino) queries over the tables your key can read."""

from __future__ import annotations

import re
from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from nasdaq_data_link_mcp_os.config import HARD_MAX_LIMIT
from nasdaq_data_link_mcp_os.errors import (
    InvalidRequestError,
    SubscriptionRequiredError,
)
from nasdaq_data_link_mcp_os.results import ColumnInfo, dump, to_json, to_tool_result
from nasdaq_data_link_mcp_os.tools._common import Toolset, ToolSpec, app_state

MAX_SQL_CHARS = 20_000

# Statements that only read. A parenthesised statement can only be a query.
READ_ONLY_KEYWORDS = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "VALUES")
QUERY_KEYWORDS = ("SELECT", "WITH", "VALUES")
ALLOWED_TEXT = "SELECT, WITH, SHOW, DESCRIBE, EXPLAIN or VALUES"

_FIRST_WORD_RE = re.compile(r"\s*((?:\(\s*)*)([A-Za-z_]+)")
# Trino reports the session user, which is the API key, through these; the
# system catalog's runtime tables expose it too.
_IDENTITY_RE = re.compile(
    r"\b(current_user|session_user|current_groups)\b|\bsystem\s*\.|\bruntime\s*\.",
    re.IGNORECASE,
)
_BLOCKED_IDENTIFIERS = frozenset(
    {"current_user", "session_user", "current_groups", "system", "runtime"}
)
# Line breaks other than \n end Trino comments too; no query needs them.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x85\u2028\u2029]")
_EXPLAIN_FLAG_RE = re.compile(r"\s*(ANALYZE|VERBOSE)\b", re.IGNORECASE)
_EXPLAIN_OPTIONS_RE = re.compile(r"\s*\(\s*(TYPE|FORMAT)\b", re.IGNORECASE)

SHOW_TABLES_NOTE = (
    "SHOW TABLES lists the tables this key can query with SQL; free keys "
    "typically see only ndaq_rtat and ndaq_rtat10. SQL entitlements can differ "
    "from the Tables API (QDL/OPEC is free through ndl_query_table but denied "
    "here). SQL names are lower-case vendor_table: ndaq_rtat10 is NDAQ/RTAT10."
)
DENIED_HINT = (
    " SHOW TABLES lists the tables this key can query with SQL. SQL entitlements "
    "can differ from the Tables API, so the same table may still be readable "
    "with ndl_query_table (QDL/OPEC is, for example)."
)
NOT_FOUND_ERRORS = ("TABLE_NOT_FOUND", "SCHEMA_NOT_FOUND", "CATALOG_NOT_FOUND")
NOT_FOUND_HINT = (
    " SQL table names are lower-case vendor_table (NDAQ/RTAT10 is ndaq_rtat10); "
    "SHOW TABLES lists the ones this key can query."
)


# ------------------------------------------------------------------ models


class SqlQueryResult(BaseModel):
    """Rows returned by one DataLink SQL statement."""

    columns: list[ColumnInfo] = Field(description="Result columns, in row order.")
    rows: list[list[Any]] = Field(description="Row values, aligned with `columns`.")
    row_count: int = Field(description="Number of rows in `rows`.")
    has_more: bool = Field(
        description="True when the statement produced more rows than were returned."
    )
    notes: list[str] = Field(
        default_factory=list, description="Caveats about the result."
    )


# ------------------------------------------------------------ read-only guard


def _mask(sql: str, identifiers: list[str] | None = None) -> str:
    """Blank out comments and the contents of string literals and quoted names.

    The result has the same length as ``sql``, so positions line up, and every
    ``;`` left in it separates statements. Quoted identifiers are appended to
    ``identifiers`` when a list is given.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        two = sql[i : i + 2]
        if two == "--":
            ends = [p for p in (sql.find("\n", i), sql.find("\r", i)) if p != -1]
            end = min(ends) if ends else n
            out.append(" " * (end - i))
            i = end
        elif two == "/*":
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(" " * (end - i))
            i = end
        elif sql[i] in "'\"":
            quote = sql[i]
            j = i + 1
            while j < n:
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:  # doubled quote escape
                        j += 2
                        continue
                    break
                j += 1
            end = min(j + 1, n)
            if quote == '"' and identifiers is not None:
                identifiers.append(sql[i + 1 : j].replace('""', '"'))
            out.append(quote + " " * (end - i - 2) + (quote if end - i > 1 else ""))
            i = end
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def _check_read_only(masked: str, *, inside_explain: bool = False) -> None:
    match = _FIRST_WORD_RE.match(masked)
    if match is None:
        raise InvalidRequestError(
            f"The statement must start with {ALLOWED_TEXT}; found "
            f"{masked.strip()[:20]!r}."
        )
    parenthesised, word = bool(match.group(1)), match.group(2).upper()
    valid: tuple[str, ...] = QUERY_KEYWORDS if parenthesised else READ_ONLY_KEYWORDS
    if word not in valid or (inside_explain and word == "EXPLAIN"):
        raise InvalidRequestError(
            "DataLink SQL is read-only through this tool: the statement must start "
            f"with {ALLOWED_TEXT}; it starts with {word}."
        )
    if word == "EXPLAIN":
        _check_explained(masked[match.end() :])


def _check_explained(rest: str) -> None:
    """Check the statement after EXPLAIN [ANALYZE] [VERBOSE] [(options)]."""
    while flag := _EXPLAIN_FLAG_RE.match(rest):
        rest = rest[flag.end() :]
    if _EXPLAIN_OPTIONS_RE.match(rest):
        close = rest.find(")")
        rest = rest[close + 1 :] if close != -1 else ""
    if not rest.strip():
        raise InvalidRequestError("EXPLAIN needs a statement to explain.")
    _check_read_only(rest, inside_explain=True)


def read_only_statement(sql: str) -> str:
    """Return the single read-only statement in ``sql``, ready to send to Trino.

    Comments and whitespace may surround it and one trailing ``;`` is allowed
    (Trino rejects it, so it is removed). Anything else raises
    InvalidRequestError.
    """
    if _CONTROL_RE.search(sql):
        raise InvalidRequestError(
            "The SQL contains control characters (such as a carriage return); "
            "use plain spaces and \\n line breaks."
        )
    identifiers: list[str] = []
    masked = _mask(sql, identifiers)
    if not masked.strip().strip(";").strip():
        raise InvalidRequestError("The SQL statement is empty.")
    cut = masked.find(";")
    if cut != -1:
        if masked[cut:].replace(";", "").strip():
            raise InvalidRequestError(
                "Only one SQL statement per call is accepted; remove everything "
                "after the first ';' or send the statements one at a time."
            )
        sql, masked = sql[:cut], masked[:cut]
    _check_read_only(masked)
    if _IDENTITY_RE.search(masked) or any(
        name.strip().lower() in _BLOCKED_IDENTIFIERS for name in identifiers
    ):
        raise InvalidRequestError(
            "Session and system information (current_user, system.runtime, ...) "
            "is not available through this tool."
        )
    return sql.strip()


# ------------------------------------------------------------------- tools


def _fit(result: SqlQueryResult, max_bytes: int) -> SqlQueryResult:
    """Drop trailing rows until the serialized result fits in ``max_bytes``."""

    def size(model: SqlQueryResult) -> int:
        return len(to_json(dump(model)).encode())

    if size(result) <= max_bytes or not result.rows:
        return result

    def trimmed(kept: int) -> SqlQueryResult:
        note = (
            f"Output trimmed to {kept} of {result.row_count} rows to stay under "
            f"{max_bytes:,} bytes. Select fewer columns or aggregate to see more."
        )
        return result.model_copy(
            update={
                "rows": result.rows[:kept],
                "row_count": kept,
                "has_more": True,
                "notes": [*result.notes, note],
            }
        )

    lo, hi = 0, len(result.rows)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if size(trimmed(mid)) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return trimmed(lo)


async def ndl_sql_query(
    ctx: Context,
    sql: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_SQL_CHARS,
            description=(
                "One read-only Trino statement (SELECT, WITH, SHOW, DESCRIBE, "
                "EXPLAIN or VALUES). Tables are lower-case vendor_table, e.g. "
                "'SELECT date, ticker, sentiment FROM ndaq_rtat10 ORDER BY date "
                "DESC LIMIT 10'. A trailing ';' is removed."
            ),
            examples=["SHOW TABLES", "DESCRIBE ndaq_rtat10"],
        ),
    ],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=HARD_MAX_LIMIT,
            description="Maximum rows to return (default 100, max 1000). Reading "
            "stops, and the query is cancelled, once more rows than this arrive.",
        ),
    ] = 100,
) -> Annotated[CallToolResult, SqlQueryResult]:
    """Run a read-only SQL statement on DataLink SQL (Nasdaq's Trino endpoint).

    Tables live in catalog main, schema huron, named lower-case vendor_table:
    NDAQ/RTAT10 is ndaq_rtat10. Unlike the Tables API, ORDER BY, GROUP BY,
    joins and window functions run on Nasdaq's side, which suits rankings and
    aggregates. Most statements finish in 2-5 seconds (SHOW TABLES takes about
    15); filtering large tables on date and adding LIMIT keeps them fast.

    SHOW TABLES lists the tables your key can query; a free key typically sees
    only ndaq_rtat and ndaq_rtat10. SQL entitlements differ from the Tables API:
    some tables a free key reads with ndl_query_table, such as QDL/OPEC, are
    denied here with a subscription error.
    """
    state = app_state(ctx)
    statement = read_only_statement(sql)
    limit = min(limit, state.settings.max_limit)
    try:
        # One extra row tells a complete result from a truncated one.
        result = await state.client.run_sql(statement, max_rows=limit + 1)
    except SubscriptionRequiredError as exc:
        raise SubscriptionRequiredError(
            exc.message.rstrip(". ") + "." + DENIED_HINT,
            code=exc.code,
            status=exc.status,
        ) from None
    except InvalidRequestError as exc:
        if not any(name in exc.message for name in NOT_FOUND_ERRORS):
            raise
        raise InvalidRequestError(
            exc.message.rstrip(". ") + "." + NOT_FOUND_HINT,
            code=exc.code,
            status=exc.status,
        ) from None

    has_more = len(result.rows) > limit
    notes: list[str] = []
    if re.match(r"SHOW\s+TABLES\b", _mask(statement).strip(), re.IGNORECASE):
        notes.append(SHOW_TABLES_NOTE)
    if has_more:
        notes.append(
            f"More than {limit} rows matched; only the first {limit} were read. "
            f"Aggregate, add a LIMIT or raise limit (max {state.settings.max_limit})."
        )
    output = SqlQueryResult(
        columns=[ColumnInfo(name=c.name, type=c.type) for c in result.columns],
        rows=result.rows[:limit],
        row_count=min(len(result.rows), limit),
        has_more=has_more,
        notes=notes,
    )
    return to_tool_result(_fit(output, state.settings.max_response_bytes))


TOOLSET = Toolset(
    name="sql",
    description="DataLink SQL (Trino) queries over the tables your key can read.",
    tools=(
        ToolSpec(
            ndl_sql_query,
            "Run a DataLink SQL query",
            tables=("NDAQ/RTAT", "NDAQ/RTAT10"),
        ),
    ),
)
