"""Nasdaq Data Link MCP server: construction and command-line entry point."""

import argparse
import hmac
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
from dotenv import dotenv_values
from mcp.server import MCPServer
from mcp.server.mcpserver import Icon
from mcp.server.transport_security import TransportSecuritySettings

from nasdaq_data_link_mcp_os import __version__
from nasdaq_data_link_mcp_os.catalog import Catalog
from nasdaq_data_link_mcp_os.client import NasdaqDataLinkClient
from nasdaq_data_link_mcp_os.config import (
    API_KEY_ENV,
    DEFAULT_BASE_URL,
    Settings,
    parse_toolsets,
)
from nasdaq_data_link_mcp_os.instructions import build_instructions
from nasdaq_data_link_mcp_os.resources import register_resources
from nasdaq_data_link_mcp_os.tools import (
    TOOLSETS,
    build_tools,
    register_prompts,
    resolve_toolsets,
    routing_hints,
    table_tools,
)
from nasdaq_data_link_mcp_os.tools._common import AppState, secret_variants

logger = logging.getLogger("nasdaq_data_link_mcp_os")

SERVER_NAME = "nasdaq-data-link-mcp"
REPO_URL = "https://github.com/stefanoamorelli/nasdaq-data-link-mcp"
ICON_URL = (
    "https://raw.githubusercontent.com/stefanoamorelli/nasdaq-data-link-mcp/"
    "main/nasdaq-mcp-server-logo.png"
)
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def create_server(
    settings: Settings | None = None,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> MCPServer[AppState]:
    """Build a server. ``transport`` lets tests swap in an httpx2 mock."""
    settings = settings or Settings.from_env()
    enabled = resolve_toolsets(settings.toolsets)
    catalog = Catalog.load()
    tools = build_tools(
        enabled,
        deadline_seconds=settings.tool_deadline_seconds,
        secret=settings.api_key,
    )
    tables = table_tools(enabled)

    @asynccontextmanager
    async def lifespan(_: MCPServer[AppState]) -> AsyncIterator[AppState]:
        client = NasdaqDataLinkClient(settings, transport=transport)
        try:
            yield AppState(
                settings=settings,
                client=client,
                catalog=catalog,
                toolsets=enabled,
                table_tools=tables,
            )
        finally:
            await client.aclose()

    server: MCPServer[AppState] = MCPServer(
        SERVER_NAME,
        title="Nasdaq Data Link (community MCP server)",
        description=(
            "Unofficial MCP server for the Nasdaq Data Link Tables API: catalog "
            "search, generic table queries, DataLink SQL and typed tools for "
            "specific datasets."
        ),
        instructions=build_instructions(routing_hints(enabled)),
        website_url=REPO_URL,
        icons=[Icon(src=ICON_URL, mime_type="image/png")],
        version=__version__,
        lifespan=lifespan,
        tools=tools,
        log_level=settings.log_level,  # type: ignore[arg-type]
    )
    register_prompts(server, enabled)
    register_resources(server, catalog)
    logger.debug(
        "Registered %d tools from toolsets: %s", len(tools), ", ".join(enabled)
    )
    return server


# --------------------------------------------------------------- .env files


def _env_file_allows(key: str) -> bool:
    # A .env file may come from an untrusted checkout, so it can never point the
    # server (and the API key) at another host. Names are compared upper-cased
    # because os.environ is case-insensitive on Windows.
    return key == API_KEY_ENV or (key.startswith("NDL_") and key != "NDL_BASE_URL")


def load_env_file(path: Path | None) -> None:
    """Load the API key and NDL_* settings from ``path`` or ./.env.

    Only the working directory is searched (no parent directories), variables
    already set in the environment win, ${VAR} references are not expanded,
    and NDL_BASE_URL is ignored.
    """
    explicit = path is not None
    path = path or Path.cwd() / ".env"
    if not path.is_file():
        if explicit:
            raise SystemExit(f"--env-file {path} does not exist")
        return
    for raw_key, value in dotenv_values(path, interpolate=False).items():
        key = raw_key.strip().upper()
        if value is None:
            continue
        if _env_file_allows(key):
            os.environ.setdefault(key, value)
        elif key == "NDL_BASE_URL":
            logger.warning(
                "Ignoring NDL_BASE_URL from %s; set it in the environment.", path
            )


def _safe(message: str) -> str:
    """Remove the API key from a startup error before it reaches stderr."""
    for secret in secret_variants(os.environ.get(API_KEY_ENV)):
        message = message.replace(secret, "<redacted>")
    return message


# ----------------------------------------------------------------- HTTP mode


class BearerTokenMiddleware:
    """Reject HTTP requests that lack ``Authorization: Bearer <token>``."""

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._token = token.encode()

    def _authorized(self, header: bytes) -> bool:
        scheme, _, credentials = header.strip().partition(b" ")
        # The auth scheme is case-insensitive (RFC 7235); the token is not.
        return scheme.lower() == b"bearer" and hmac.compare_digest(
            credentials.strip(), self._token
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not self._authorized(supplied):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": b'{"error":"unauthorized"}'}
                )
                return
        await self._app(scope, receive, send)


def build_http_app(
    server: MCPServer[AppState], settings: Settings, transport: str, host: str
) -> Any:
    """The ASGI app for an HTTP transport, with the server's safety rules applied.

    Binding anything but loopback requires NDL_HTTP_TOKEN: the HTTP transports
    have no authentication of their own, and every tool call spends the
    server's API key.
    """
    if host not in LOOPBACK_HOSTS and not settings.http_token:
        raise SystemExit(
            f"Refusing to serve on {host} without NDL_HTTP_TOKEN. Set a token "
            "(clients send it as 'Authorization: Bearer <token>') or bind 127.0.0.1."
        )
    security: TransportSecuritySettings | None = None
    if settings.allowed_hosts:
        names = settings.allowed_hosts
        security = TransportSecuritySettings(
            allowed_hosts=[*names, *(f"{h}:*" for h in names)],
            allowed_origins=[
                f"{scheme}://{h}" for h in names for scheme in ("https", "http")
            ],
        )
    elif host not in LOOPBACK_HOSTS:
        # Host checks need the public name; the bearer token is the control here.
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if transport == "sse":
        app = server.sse_app(host=host, transport_security=security)
    else:
        app = server.streamable_http_app(host=host, transport_security=security)
    if settings.http_token:
        return BearerTokenMiddleware(app, settings.http_token)
    return app


# ---------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nasdaq-data-link-mcp",
        description="Community MCP server for the Nasdaq Data Link Tables API.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for HTTP transports (default: 127.0.0.1). Any other "
        "address requires NDL_HTTP_TOKEN.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transports (default: 8000).",
    )
    parser.add_argument(
        "--toolsets",
        default=None,
        help=(
            "Comma-separated toolsets to enable (default: all, or NDL_TOOLSETS). "
            f"Available: {', '.join(TOOLSETS)}. 'core' is always enabled."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Read the API key and NDL_* settings from this file instead of ./.env.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Console entry point: ``nasdaq-data-link-mcp``."""
    args = _build_parser().parse_args(argv)
    load_env_file(args.env_file)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(_safe(f"Invalid configuration: {exc}")) from None
    if args.toolsets is not None:
        settings = replace(settings, toolsets=parse_toolsets(args.toolsets))
    if settings.base_url != DEFAULT_BASE_URL:
        logger.warning("Sending requests (and the API key) to %s", settings.base_url)
    if not settings.has_api_key:
        # The variable's name is written out: it is not a secret, but passing
        # API_KEY_ENV as a log argument reads like one to static analysis.
        logger.warning(
            "NASDAQ_DATA_LINK_API_KEY is not set: only ndl_search_tables, "
            "prompts and resources will work."
        )
    try:
        server = create_server(settings)
    except ValueError as exc:
        raise SystemExit(_safe(str(exc))) from None
    if args.transport == "stdio":
        server.run()
        return

    import uvicorn

    app = build_http_app(server, settings, args.transport, args.host)
    print(  # noqa: T201 - startup line on stderr; stdout is unused in HTTP mode
        f"nasdaq-data-link-mcp {__version__} on http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    uvicorn.run(
        app, host=args.host, port=args.port, log_level=settings.log_level.lower()
    )


_module_server: MCPServer[AppState] | None = None


def __getattr__(name: str) -> Any:
    # `mcp run` / `mcp dev` look for a module-level `mcp` object. Build it only
    # when asked, so importing this module (and the console script) does not
    # construct a second server or read the environment early.
    global _module_server
    if name == "mcp":
        if _module_server is None:
            _module_server = create_server()
        return _module_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    main()
