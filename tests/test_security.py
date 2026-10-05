"""Regression tests for the server's safety rules."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from nasdaq_data_link_mcp_os.client import _TTLCache
from nasdaq_data_link_mcp_os.config import Settings, parse_base_url
from nasdaq_data_link_mcp_os.errors import InvalidRequestError
from nasdaq_data_link_mcp_os.server import (
    BearerTokenMiddleware,
    build_http_app,
    create_server,
    load_env_file,
)
from nasdaq_data_link_mcp_os.tools._common import secret_variants, wrap_tool
from tests.fake_nasdaq import API_KEY

pytestmark = pytest.mark.anyio


# ------------------------------------------------------------ tool surface


async def test_input_schemas_reject_unknown_arguments() -> None:
    server = create_server(Settings(api_key=API_KEY))
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        for tool in tools:
            assert tool.input_schema.get("additionalProperties") is False, tool.name
            assert "title" not in tool.input_schema, tool.name
        result = await client.call_tool(
            "ndl_search_tables", {"query": "gold", "bogus_argument": 1}
        )
    assert result.is_error
    assert "bogus_argument" in result.content[0].text  # type: ignore[union-attr]


async def test_every_referenced_tool_exists() -> None:
    server = create_server(Settings(api_key=API_KEY))
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        prompts = (await client.list_prompts()).prompts
        instructions = client.instructions or ""
    names = {t.name for t in tools}
    texts = {"instructions": instructions}
    texts |= {t.name: t.description or "" for t in tools}
    texts |= {p.name: p.description or "" for p in prompts}
    for where, text in texts.items():
        for ref in re.findall(r"\bndl_[a-z0-9_]+", text):
            assert ref in names, f"{where} mentions unknown tool {ref}"


# --------------------------------------------------------------- deadlines


async def test_tool_deadline_turns_a_stall_into_an_error() -> None:
    async def slow() -> str:
        await anyio.sleep(5)
        return "done"

    wrapped = wrap_tool(slow, deadline_seconds=0.2)
    with pytest.raises(ToolError, match=r"\[UPSTREAM\].*did not finish"):
        await wrapped()


async def test_client_gives_up_inside_the_deadline() -> None:
    from nasdaq_data_link_mcp_os.client import CALL_DEADLINE, NasdaqDataLinkClient

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            json={"quandl_error": {"code": "QELx04", "message": "slow down"}},
            headers={"retry-after": "30"},
        )

    client = NasdaqDataLinkClient(
        Settings(api_key=API_KEY, max_retries=5),
        transport=httpx2.MockTransport(handler),
        sleep=fake_sleep,
    )
    token = CALL_DEADLINE.set(None)
    try:
        with pytest.raises(Exception, match="rate limit"):
            await client.get_table_page("NDAQ/RTAT10")
    finally:
        CALL_DEADLINE.reset(token)
    assert sleeps == []  # a 30 s Retry-After is reported, not waited out


# --------------------------------------------------------------- redaction


def test_secret_variants_cover_common_encodings() -> None:
    forms = secret_variants(API_KEY)
    assert API_KEY in forms and API_KEY[::-1] in forms
    assert API_KEY.encode().hex() in forms
    assert base64.b64encode(API_KEY.encode()).decode().rstrip("=") in forms
    assert secret_variants(None) == []


async def test_errors_are_redacted() -> None:
    async def leaky() -> str:
        raise InvalidRequestError(f"bad request for user {API_KEY[::-1]}")

    wrapped = wrap_tool(leaky, deadline_seconds=5, secret=API_KEY)
    with pytest.raises(ToolError) as info:
        await wrapped()
    assert API_KEY[::-1] not in str(info.value)
    assert "<redacted>" in str(info.value)


# ------------------------------------------------------------------- cache


def test_cache_is_bounded_by_bytes_and_drops_expired_entries() -> None:
    now = [0.0]
    cache = _TTLCache(maxsize=100, clock=lambda: now[0], max_bytes=1_000)
    cache.set("big", "x", ttl=60, size=600)  # more than a quarter: not cached
    assert cache.get("big") is None
    for i in range(6):
        cache.set(i, i, ttl=60, size=200)
    assert cache.get(0) is None  # evicted to stay under 1,000 bytes
    assert cache.get(5) == 5
    now[0] = 120
    cache.set("fresh", 1, ttl=60, size=10)
    assert cache._bytes == 10  # expired entries were purged


# ------------------------------------------------------------ configuration


@pytest.mark.parametrize(
    "url",
    [
        "http://data.nasdaq.com",
        "https://user:pw@data.nasdaq.com",
        "https://data.nasdaq.com/api",
        "ftp://data.nasdaq.com",
        "data.nasdaq.com",
    ],
)
def test_base_url_must_be_a_bare_https_origin(url: str) -> None:
    with pytest.raises(ValueError, match="NDL_BASE_URL"):
        parse_base_url(url)


def test_base_url_default_and_valid() -> None:
    assert parse_base_url(None) == "https://data.nasdaq.com"
    assert parse_base_url("https://example.test/") == "https://example.test"


def test_env_file_cannot_change_the_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "NASDAQ_DATA_LINK_API_KEY=from-file\n"
        "NDL_BASE_URL=https://attacker.example\n"
        "NDL_TOOLSETS=sql\n"
        "UNRELATED=1\n"
    )
    for key in (
        "NASDAQ_DATA_LINK_API_KEY",
        "NDL_BASE_URL",
        "NDL_TOOLSETS",
        "UNRELATED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    load_env_file(None)
    assert os.environ["NASDAQ_DATA_LINK_API_KEY"] == "from-file"
    assert os.environ["NDL_TOOLSETS"] == "sql"
    assert "NDL_BASE_URL" not in os.environ
    assert "UNRELATED" not in os.environ


def test_env_file_lookup_does_not_walk_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("NASDAQ_DATA_LINK_API_KEY=parent\n")
    child = tmp_path / "project"
    child.mkdir()
    monkeypatch.delenv("NASDAQ_DATA_LINK_API_KEY", raising=False)
    monkeypatch.chdir(child)
    load_env_file(None)
    assert "NASDAQ_DATA_LINK_API_KEY" not in os.environ


def test_explicit_env_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_env_file(tmp_path / "missing.env")


# --------------------------------------------------------------- HTTP mode


def test_public_bind_requires_a_token() -> None:
    server = create_server(Settings(api_key=API_KEY))
    with pytest.raises(SystemExit, match="NDL_HTTP_TOKEN"):
        build_http_app(server, Settings(api_key=API_KEY), "streamable-http", "0.0.0.0")


async def test_bearer_token_middleware() -> None:
    async def app(scope: dict, receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"ok"})  # type: ignore[operator]

    guarded = BearerTokenMiddleware(app, "s3cret")
    transport = httpx2.ASGITransport(app=guarded)
    async with httpx2.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/mcp")).status_code == 401
        wrong = await client.get("/mcp", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = await client.get("/mcp", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200


def test_token_protected_public_bind_builds_an_app() -> None:
    settings = Settings(api_key=API_KEY, http_token="s3cret")
    server = create_server(settings)
    app = build_http_app(server, settings, "streamable-http", "0.0.0.0")
    assert isinstance(app, BearerTokenMiddleware)


def test_env_file_names_are_normalised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # os.environ is case-insensitive on Windows: 'NDL_Base_URL' would become
    # NDL_BASE_URL there, so mixed-case names must be refused as well.
    (tmp_path / ".env").write_text(
        "NDL_Base_URL=https://attacker.example\n"
        "ndl_toolsets=sql\n"
        "NDL_LOG_LEVEL=${NASDAQ_DATA_LINK_API_KEY}\n"
    )
    for key in ("NDL_BASE_URL", "NDL_TOOLSETS", "NDL_LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NASDAQ_DATA_LINK_API_KEY", API_KEY)
    monkeypatch.chdir(tmp_path)
    load_env_file(None)
    assert "NDL_BASE_URL" not in os.environ
    assert os.environ["NDL_TOOLSETS"] == "sql"
    # ${VAR} is not expanded, so the key cannot be copied into a setting.
    assert os.environ["NDL_LOG_LEVEL"] == "${NASDAQ_DATA_LINK_API_KEY}"


def test_startup_errors_do_not_echo_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from nasdaq_data_link_mcp_os.server import main

    monkeypatch.setenv("NASDAQ_DATA_LINK_API_KEY", API_KEY)
    monkeypatch.setenv("NDL_LOG_LEVEL", API_KEY)
    with pytest.raises(SystemExit) as info:
        main([])
    assert API_KEY not in str(info.value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_numbers_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        Settings.from_env({"NDL_TOOL_DEADLINE_SECONDS": value})


async def test_bearer_scheme_is_case_insensitive() -> None:
    async def app(scope: dict, receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"ok"})  # type: ignore[operator]

    transport = httpx2.ASGITransport(app=BearerTokenMiddleware(app, "s3cret"))
    async with httpx2.AsyncClient(transport=transport, base_url="http://t") as client:
        for header in ("bearer s3cret", "BEARER  s3cret", "Bearer s3cret "):
            response = await client.get("/mcp", headers={"Authorization": header})
            assert response.status_code == 200, header
        bad = await client.get("/mcp", headers={"Authorization": "Basic s3cret"})
        assert bad.status_code == 401
