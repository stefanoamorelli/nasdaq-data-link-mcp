# Nasdaq Data Link MCP server (stdio by default).
#
#   docker build -t nasdaq-data-link-mcp .
#   docker run --rm -i -e NASDAQ_DATA_LINK_API_KEY nasdaq-data-link-mcp
#
# MCP client configuration:
#
#   "nasdaq-data-link": {
#     "command": "docker",
#     "args": ["run", "--rm", "-i", "-e", "NASDAQ_DATA_LINK_API_KEY",
#              "stefanoamorelli/nasdaq-data-link-mcp:latest"],
#     "env": {"NASDAQ_DATA_LINK_API_KEY": "<your key>"}
#   }
#
# Optional settings are environment variables (NDL_TOOLSETS, NDL_LOG_LEVEL, ...,
# see .env.example). For Streamable HTTP instead of stdio, append
# "--transport streamable-http --host 0.0.0.0", set NDL_HTTP_TOKEN (clients send
# "Authorization: Bearer <token>"; the server refuses non-loopback binds without
# it) and publish the port on loopback only: -p 127.0.0.1:8000:8000.
# The image contains no credentials: the API key is read from the environment.

# Base images are pinned by tag and digest; Dependabot proposes updates.
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.14-slim-trixie@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS base

# ---------------------------------------------------------------------------
# Build stage: resolve exactly what uv.lock pins into a self-contained venv.
FROM base AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

# Dependencies first, so source edits do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The project itself, installed as a regular (non-editable) package.
COPY README.md LICENSE ./
COPY nasdaq_data_link_mcp_os ./nasdaq_data_link_mcp_os
RUN uv sync --frozen --no-dev --no-editable \
    && /opt/venv/bin/nasdaq-data-link-mcp --version

# ---------------------------------------------------------------------------
# Runtime stage: the venv only (no uv, no sources, no build tools), non-root.
FROM base AS runtime

LABEL org.opencontainers.image.title="nasdaq-data-link-mcp" \
      org.opencontainers.image.description="Community MCP server for the Nasdaq Data Link Tables API (unofficial)" \
      org.opencontainers.image.source="https://github.com/stefanoamorelli/nasdaq-data-link-mcp" \
      org.opencontainers.image.url="https://github.com/stefanoamorelli/nasdaq-data-link-mcp" \
      org.opencontainers.image.documentation="https://github.com/stefanoamorelli/nasdaq-data-link-mcp#readme" \
      org.opencontainers.image.authors="Stefano Amorelli <stefano@amorelli.tech>" \
      org.opencontainers.image.licenses="MIT" \
      io.modelcontextprotocol.server.name="io.github.stefanoamorelli/nasdaq-data-link-mcp"

RUN groupadd --system --gid 10001 mcp \
    && useradd --system --uid 10001 --gid mcp --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin mcp

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# An empty working directory: the server only reads a .env from its working
# directory, and none exists in the image.
WORKDIR /app
USER 10001:10001

ENTRYPOINT ["nasdaq-data-link-mcp"]
CMD []
