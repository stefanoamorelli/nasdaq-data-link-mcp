from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from nasdaq_data_link_mcp_os.client import NasdaqDataLinkClient, normalize_table_code
from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.errors import (
    BlockedError,
    InvalidApiKeyError,
    InvalidRequestError,
    MissingApiKeyError,
    RateLimitError,
    SubscriptionRequiredError,
    TableNotFoundError,
    UpstreamError,
    error_from_response,
    to_tool_error,
)
from tests.fake_nasdaq import API_KEY, FakeNasdaq

pytestmark = pytest.mark.anyio


def _err(code: str, message: str) -> str:
    return json.dumps({"quandl_error": {"code": code, "message": message}})


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, _err("QECx02", "does not exist"), TableNotFoundError),
        (
            403,
            _err("QEPx04", "You do not have permission ... subscribe"),
            SubscriptionRequiredError,
        ),
        (
            403,
            _err("QEPx04", "A valid API key is required to retrieve data."),
            MissingApiKeyError,
        ),
        (403, _err("QEPx06", "column 'x' does not exist"), InvalidRequestError),
        (422, _err("QESx08", "cannot filter"), InvalidRequestError),
        (
            422,
            _err("QELx06", "over the maximum limit of 10000 rows"),
            InvalidRequestError,
        ),
        (429, _err("QELx04", "reduce the number of requests"), RateLimitError),
        (
            429,
            _err("QELx06", "your account has temporarily been disabled"),
            InvalidApiKeyError,
        ),
        (503, _err("QEMx01", "maintenance"), UpstreamError),
        (403, "<html><body>Incapsula</body></html>", BlockedError),
    ],
)
def test_error_mapping(status: int, body: str, expected: type) -> None:
    error = error_from_response(status, body, table="NDAQ/RTAT10")
    assert isinstance(error, expected)
    assert str(to_tool_error(error)).startswith(f"[{error.kind}]")


def test_error_messages_never_contain_the_key() -> None:
    body = _err("QESx04", f"bad value in url ...&api_key={API_KEY}")
    error = error_from_response(422, body, api_key=API_KEY)
    assert API_KEY not in str(error)
    assert "<redacted>" in str(error)


def test_not_found_message_keeps_code_case() -> None:
    error = error_from_response(404, _err("QECx02", "x"), table="WIKI/AAPL")
    assert "WIKI/AAPL" in str(error)


@pytest.mark.parametrize("code", ["ndaq/rtat10", " NDAQ/RTAT10 "])
def test_normalize_table_code(code: str) -> None:
    assert normalize_table_code(code) == "NDAQ/RTAT10"


@pytest.mark.parametrize("code", ["WIKI", "", "a/b/c", "NDAQ RTAT"])
def test_normalize_table_code_rejects(code: str) -> None:
    with pytest.raises(InvalidRequestError):
        normalize_table_code(code)


def _client(handler: Any, **overrides: Any) -> tuple[NasdaqDataLinkClient, list[float]]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    settings = Settings(api_key=API_KEY, **overrides)
    return (
        NasdaqDataLinkClient(
            settings, transport=httpx2.MockTransport(handler), sleep=sleep
        ),
        sleeps,
    )


OK_BODY = {
    "datatable": {
        "data": [["2026-10-02", "AAPL"]],
        "columns": [
            {"name": "date", "type": "Date"},
            {"name": "ticker", "type": "text"},
        ],
    },
    "meta": {"next_cursor_id": None},
}


async def test_missing_key_raises_before_any_request() -> None:
    calls: list[Any] = []
    client = NasdaqDataLinkClient(
        Settings(api_key=None), transport=httpx2.MockTransport(calls.append)
    )
    with pytest.raises(MissingApiKeyError):
        await client.get_table_page("NDAQ/RTAT10")
    assert calls == []


async def test_key_is_sent_as_header_not_query() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=OK_BODY)

    client, _ = _client(handler)
    page = await client.get_table_page("NDAQ/RTAT10", [("ticker", "AAPL")])
    assert page.rows == [["2026-10-02", "AAPL"]]
    assert seen[0].headers["x-api-token"] == API_KEY
    assert API_KEY not in str(seen[0].url)


async def test_retries_rate_limits_then_succeeds() -> None:
    responses = [
        httpx2.Response(
            429, json={"quandl_error": {"code": "QELx04", "message": "slow"}}
        ),
        httpx2.Response(
            429,
            json={"quandl_error": {"code": "QELx01", "message": "slow"}},
            headers={"retry-after": "2"},
        ),
        httpx2.Response(200, json=OK_BODY),
    ]
    client, sleeps = _client(lambda request: responses.pop(0), max_retries=3)
    page = await client.get_table_page("NDAQ/RTAT10")
    assert len(page.rows) == 1
    assert len(sleeps) == 2
    assert sleeps[1] == 2.0  # Retry-After is honoured


async def test_does_not_retry_disabled_key() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(
            429,
            json={
                "quandl_error": {
                    "code": "QELx06",
                    "message": "account has temporarily been disabled",
                }
            },
        )

    client, sleeps = _client(handler, max_retries=3)
    with pytest.raises(InvalidApiKeyError):
        await client.get_table_page("NDAQ/RTAT10")
    assert calls == [1]
    assert sleeps == []


async def test_gives_up_after_max_retries() -> None:
    client, sleeps = _client(
        lambda r: httpx2.Response(502, text="bad gateway"), max_retries=2
    )
    with pytest.raises(UpstreamError):
        await client.get_table_page("NDAQ/RTAT10")
    assert len(sleeps) == 2


async def test_timeout_becomes_upstream_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    client, _ = _client(handler, max_retries=0)
    with pytest.raises(UpstreamError, match="did not answer"):
        await client.get_table_page("NDAQ/RTAT10")


async def test_responses_are_cached() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(200, json=OK_BODY)

    client, _ = _client(handler)
    await client.get_table_page("NDAQ/RTAT10", [("ticker", "AAPL")])
    await client.get_table_page("NDAQ/RTAT10", [("ticker", "AAPL")])
    assert len(calls) == 1
    await client.get_table_page("NDAQ/RTAT10", [("ticker", "AAPL")], use_cache=False)
    assert len(calls) == 2


async def test_rate_limit_headers_are_recorded() -> None:
    client, _ = _client(
        lambda r: httpx2.Response(
            200,
            json=OK_BODY,
            headers={"x-ratelimit-limit": "50000", "x-ratelimit-remaining": "123"},
        )
    )
    await client.get_table_page("NDAQ/RTAT10")
    assert client.rate_limit.limit == 50000
    assert client.rate_limit.remaining == 123


async def test_html_200_is_reported_as_blocked() -> None:
    client, _ = _client(
        lambda r: httpx2.Response(
            200, text="<html>blocked</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(BlockedError):
        await client.get_table_page("NDAQ/RTAT10")


async def test_sql_collects_pages_and_redacts_key() -> None:
    fake = FakeNasdaq()
    fake.sql_handler = lambda sql: [
        {"id": "q1", "stats": {"state": "QUEUED"}},
        {
            "columns": [{"name": "ticker", "type": "varchar"}],
            "data": [["AAPL"], ["MSFT"]],
            "stats": {"state": "RUNNING"},
        },
        {"data": [["TSLA"]], "stats": {"state": "FINISHED"}},
    ]
    client = NasdaqDataLinkClient(
        Settings(api_key=API_KEY), transport=fake.transport(), sleep=_no_sleep
    )
    result = await client.run_sql("SELECT ticker FROM ndaq_rtat10", max_rows=10)
    assert [c.name for c in result.columns] == ["ticker"]
    assert result.rows == [["AAPL"], ["MSFT"], ["TSLA"]]
    assert not result.truncated

    # More rows than wanted while Trino still has pages: stop and cancel.
    truncated = await client.run_sql("SELECT ticker FROM ndaq_rtat10", max_rows=1)
    assert truncated.truncated
    assert truncated.rows == [["AAPL"]]
    assert any(r.method == "DELETE" for r in fake.requests)

    exact = await client.run_sql("SELECT ticker FROM ndaq_rtat10", max_rows=3)
    assert not exact.truncated
    assert len(exact.rows) == 3


async def test_sql_last_page_over_limit_is_truncated() -> None:
    fake = FakeNasdaq()
    fake.sql_handler = lambda sql: [
        {
            "columns": [{"name": "n", "type": "integer"}],
            "data": [[1], [2], [3]],
            "stats": {"state": "FINISHED"},
        }
    ]
    client = NasdaqDataLinkClient(
        Settings(api_key=API_KEY), transport=fake.transport(), sleep=_no_sleep
    )
    result = await client.run_sql("SELECT n FROM t", max_rows=2)
    assert result.truncated and result.rows == [[1], [2]]


async def test_sql_permission_error_is_redacted() -> None:
    fake = FakeNasdaq()
    fake.sql_handler = lambda sql: [
        {
            "error": {
                "message": f"Access Denied: User {API_KEY} cannot select from qdl_opec",
                "errorName": "PERMISSION_DENIED",
            },
            "stats": {"state": "FAILED"},
        }
    ]
    client = NasdaqDataLinkClient(
        Settings(api_key=API_KEY), transport=fake.transport(), sleep=_no_sleep
    )
    with pytest.raises(SubscriptionRequiredError) as info:
        await client.run_sql("SELECT * FROM qdl_opec", max_rows=5)
    assert API_KEY not in str(info.value)


async def _no_sleep(seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("status", "expected"), [(502, UpstreamError), (429, RateLimitError)]
)
def test_html_gateway_errors_are_retryable(status: int, expected: type) -> None:
    error = error_from_response(
        status, "<html>Bad gateway</html>", content_type="text/html"
    )
    assert isinstance(error, expected)


def test_html_4xx_is_still_blocked() -> None:
    error = error_from_response(403, "<html>Incapsula</html>", content_type="text/html")
    assert isinstance(error, BlockedError)
