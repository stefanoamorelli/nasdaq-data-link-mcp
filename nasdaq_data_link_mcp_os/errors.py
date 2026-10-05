"""Errors raised by the Nasdaq Data Link client.

Every message is written for the model on the other side of the MCP connection: it
says what went wrong and what to do next, and it never contains the API key.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from nasdaq_data_link_mcp_os.config import API_KEY_ENV, SIGN_UP_URL


class NdlError(Exception):
    """Base class. ``kind`` is a short label shown in front of the message."""

    kind = "ERROR"

    def __init__(
        self, message: str, *, code: str | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def __str__(self) -> str:
        suffix = f" (Nasdaq code {self.code})" if self.code else ""
        return f"{self.message}{suffix}"


class MissingApiKeyError(NdlError):
    kind = "AUTH"

    def __init__(self) -> None:
        super().__init__(
            f"{API_KEY_ENV} is not set. Create a free key at {SIGN_UP_URL} and add it "
            "to this MCP server's environment."
        )


class InvalidApiKeyError(NdlError):
    kind = "AUTH"


class SubscriptionRequiredError(NdlError):
    kind = "SUBSCRIPTION"


class TableNotFoundError(NdlError):
    kind = "NOT_FOUND"


class InvalidRequestError(NdlError):
    kind = "INVALID_REQUEST"


class RateLimitError(NdlError):
    kind = "RATE_LIMIT"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, code=code, status=status)
        self.retry_after = retry_after


class BlockedError(NdlError):
    kind = "BLOCKED"


class UpstreamError(NdlError):
    kind = "UPSTREAM"


def redact(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return text.replace(secret, "<redacted>")
    return text


def _parse_error_body(body: str) -> tuple[str | None, str | None]:
    try:
        payload: Any = json.loads(body)
    except (ValueError, TypeError):
        return None, None
    err = payload.get("quandl_error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return None, None
    return err.get("code"), err.get("message")


def error_from_response(
    status: int,
    body: str,
    *,
    content_type: str = "",
    table: str | None = None,
    retry_after: float | None = None,
    api_key: str | None = None,
) -> NdlError:
    """Map an HTTP error response from Nasdaq Data Link to a typed error."""
    body = redact(body or "", api_key)
    code, message = _parse_error_body(body)
    message = redact(message or "", api_key).strip()
    subject = f"table {table}" if table else "this request"

    is_html = "html" in content_type.lower() or body.lstrip().startswith("<")
    if code is None and is_html and status == 429:
        return RateLimitError(
            "Nasdaq Data Link rate limit reached (HTTP 429). Wait a moment and retry.",
            status=status,
            retry_after=retry_after,
        )
    if code is None and is_html and status >= 500:
        return UpstreamError(
            f"Nasdaq Data Link returned HTTP {status} for {subject}. This is usually "
            "transient; retry shortly.",
            status=status,
        )
    if code is None and is_html:
        return BlockedError(
            f"Nasdaq's CDN blocked {subject} (HTTP {status}, HTML response). The "
            "legacy time-series API (datasets/databases) is no longer served; use "
            "the Tables API tools instead.",
            status=status,
        )

    if code == "QECx02" or (status == 404 and code is None):
        return TableNotFoundError(
            f"{subject[0].upper()}{subject[1:]} does not exist on Nasdaq Data Link. "
            "Use ndl_search_tables to find a valid VENDOR/TABLE code.",
            code=code,
            status=status,
        )
    if code == "QEPx04" and "api key" in message.lower():
        return MissingApiKeyError()
    if code == "QEPx04":
        return SubscriptionRequiredError(
            f"Your API key has no access to {subject}: it needs a paid Nasdaq Data "
            "Link subscription and offers no free sample. Its schema is still "
            "available through ndl_describe_table.",
            code=code,
            status=status,
        )
    if code == "QEPx06":
        return InvalidRequestError(
            f"A requested column does not exist in {subject}: {message} Call "
            "ndl_describe_table to list the valid columns.",
            code=code,
            status=status,
        )
    if code == "QELx06" and "disabled" in message.lower():
        return InvalidApiKeyError(
            f"Nasdaq rejected the API key: '{message}' This is also what Nasdaq "
            f"returns for an invalid key, so check {API_KEY_ENV} first.",
            code=code,
            status=status,
        )
    if status == 429 or ((code or "").startswith("QELx0") and status != 422):
        return RateLimitError(
            "Nasdaq Data Link rate limit reached (free keys allow 1 concurrent "
            "request, 2,000 calls per 10 minutes and 50,000 per day). Wait a "
            f"moment and retry. Detail: {message or 'HTTP 429'}",
            code=code,
            status=status,
            retry_after=retry_after,
        )
    if code == "QEAx01" or status == 401:
        return InvalidApiKeyError(
            f"Nasdaq rejected the API key ({message or 'HTTP 401'}). Check "
            f"{API_KEY_ENV}.",
            code=code,
            status=status,
        )
    if status >= 500:
        return UpstreamError(
            f"Nasdaq Data Link returned HTTP {status} for {subject}. This is "
            f"usually transient; retry shortly. Detail: {message or 'server error'}",
            code=code,
            status=status,
        )
    hint = ""
    if code == "QESx08":
        hint = " Only the table's filterable columns can be used as filters."
    elif code == "QESx07":
        hint = " Supported range operators are gt, gte, lt and lte."
    elif code == "QESx04":
        hint = " Dates must be written as YYYY-MM-DD."
    elif code == "QELx06":
        hint = " Ask for fewer rows or narrow the filters."
    return InvalidRequestError(
        f"Nasdaq Data Link rejected {subject}: {message or f'HTTP {status}'}.{hint}",
        code=code,
        status=status,
    )


def to_tool_error(exc: NdlError) -> ToolError:
    """Convert a client error into the ToolError the model will see."""
    return ToolError(f"[{exc.kind}] {exc}")
