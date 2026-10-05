from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from nasdaq_data_link_mcp_os.config import Settings
from nasdaq_data_link_mcp_os.server import create_server
from tests.fake_nasdaq import API_KEY, FakeNasdaq

ClientFactory = Callable[..., AbstractAsyncContextManager[Client]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake() -> FakeNasdaq:
    return FakeNasdaq()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_key=API_KEY, max_retries=0, data_cache_ttl=0, metadata_cache_ttl=0
    )


@pytest.fixture
def make_client(fake: FakeNasdaq, settings: Settings) -> ClientFactory:
    """``async with make_client(**settings_overrides) as client: ...``"""

    @asynccontextmanager
    async def _make(**overrides: Any) -> AsyncIterator[Client]:
        server = create_server(
            replace(settings, **overrides), transport=fake.transport()
        )
        async with Client(server) as client:
            yield client

    return _make


def payload(result: CallToolResult) -> dict[str, Any]:
    """Parsed JSON of a successful tool result (asserts it succeeded)."""
    assert not result.is_error, result.content[0].text  # type: ignore[union-attr]
    text = result.content[0].text  # type: ignore[union-attr]
    data = json.loads(text)
    assert data == result.structured_content
    return data  # type: ignore[no-any-return]


def error_text(result: CallToolResult) -> str:
    assert result.is_error, "expected the tool call to fail"
    return result.content[0].text  # type: ignore[union-attr,no-any-return]
