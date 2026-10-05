# Changelog

All notable changes to the Nasdaq Data Link MCP project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - Unreleased

A rewrite on the Nasdaq Data Link Tables API and MCP SDK 2.x. Nasdaq retired
the time-series API (`/api/v3/datasets`, `/api/v3/databases`), so the five
tools added in #16 failed on every call, and the server no longer imported
once MCP SDK 2.x was released. The README maps every old tool to its
replacement.

### Breaking

- Every tool is replaced; the new tools are named `ndl_*`.
  - The five tools from #16 (`search_datasets`, `get_dataset`,
    `get_dataset_metadata`, `list_databases`, `export_dataset`) and the
    `nasdaq://databases` resource are removed; they called the retired
    time-series API.
  - The 32 tools of 0.2.x and 1.0.0 are removed. Their data is now read by
    `ndl_get_retail_trading_activity` (`get_rtat`, `get_rtat10`),
    `ndl_get_world_bank_data` and `ndl_search_world_bank_indicators` (the World
    Bank tools and `country_code`), `ndl_get_equities360` (the Equities 360
    tools), `ndl_search_mutual_funds` and `ndl_get_mutual_fund_report` (the
    Nasdaq Fund Network tools), `ndl_describe_table` (the `list_*_fields`
    tools) and `ndl_query_table` (`get_trade_summary_data`, NDAQ/TS).
- Legacy dataset codes such as `WIKI/AAPL`, `FRED/GDP` or
  `WORLDBANK/GDP_MKTP_CD` no longer work; only `VENDOR/TABLE` codes of the
  Tables API do.
- Python 3.11 or newer is required (0.2.0 declared 3.10).
- The server is built on MCP SDK 2.x (`mcp>=2.3,<3`). The `nasdaq-data-link`
  SDK and `pycountry` are no longer dependencies.
- The server starts from the `nasdaq-data-link-mcp` or
  `nasdaq-data-link-mcp-os` console script (`uvx nasdaq-data-link-mcp-os`),
  not from `mcp install nasdaq_data_link_mcp_os/server.py` with a
  `PYTHONPATH`.
- Docker image tags no longer start with `v`: release 2.0.0 is tagged `2.0.0`,
  `2.0`, `2` and `latest` (0.2.1 was tagged `v0.2.1`).
- The conda package is removed; it shipped an empty package.

### Added

- 38 read-only tools in 11 toolsets: `core` (catalog search, table metadata,
  queries on any table, CSV exports, an API key check), `sql`, `nasdaq`,
  `equities`, `funds`, `world_bank`, `macro`, `commodities`, `crypto`,
  `housing` and `carbon`. `NDL_TOOLSETS` or `--toolsets` selects them; `core`
  is always on.
- A bundled catalog of the tables the tools read plus every table a free key
  reads in full, with what a free key gets from each (full data, a fixed
  sample, or nothing) and descriptions written for the project, searched by
  `ndl_search_tables`. `scripts/refresh_catalog.py` revalidates it through the
  documented metadata endpoint.
- `ndl_sql_query` for DataLink SQL (Trino), read-only.
- Typed tools for Nasdaq RTAT retail activity, ticker changes, Equities 360,
  Sharadar (tickers, fundamentals, prices, valuation, corporate actions, S&P
  500 membership, insider transactions, 13F holdings, 8-K events), Zacks
  analyst estimates, Nasdaq Fund Network mutual fund reports, World Bank
  indicators, IMF World Economic Outlook, ICE BofA bond indices, CFTC
  Commitments of Traders, JODI, OPEC, LME warehouse stocks, USDA WASDE,
  Bitfinex prices, Bitcoin blockchain metrics, Zillow housing data and
  Puro.earth carbon removal certificates.
- Six prompts (`retail_sentiment_brief`, `company_snapshot`, `fund_snapshot`,
  `country_economic_profile`, `cot_positioning_review`,
  `zillow_housing_snapshot`) and three resources (`ndl://catalog`,
  `ndl://catalog/{vendor}/{table}`, `ndl://guides/query-syntax`).
- Streamable HTTP and SSE transports (`--transport`, `--host`, `--port`).
- Settings as environment variables: `NDL_BASE_URL`, `NDL_TIMEOUT_SECONDS`,
  `NDL_SQL_TIMEOUT_SECONDS`, `NDL_TOOL_DEADLINE_SECONDS`, `NDL_MAX_RETRIES`,
  `NDL_MAX_CONCURRENCY`, `NDL_CACHE_TTL_SECONDS`,
  `NDL_METADATA_CACHE_TTL_SECONDS`, `NDL_DEFAULT_LIMIT`, `NDL_MAX_LIMIT`,
  `NDL_MAX_RESPONSE_BYTES`, `NDL_LOG_LEVEL`, `NDL_HTTP_TOKEN` and
  `NDL_ALLOWED_HOSTS`; `--env-file` to read them from a file.
- Tool results carry structured content with an output schema, the table's
  access level, its last refresh date, and notes on samples and stale tables.
- `server.json` and a release workflow that publishes to PyPI with Trusted
  Publishing, pushes a multi-arch Docker image with SBOM and provenance
  attestations, and registers the server in the MCP Registry.
- Live API tests (`pytest -m live`), run weekly in CI.
- `scripts/generate_tool_docs.py`, which writes the tool reference in the
  README and the documentation site from the server's own tool listing; CI
  fails when the reference is out of date.

### Changed

- An async HTTP client replaces the `nasdaq-data-link` SDK, which was last
  released in 2022, has no request timeout, targets the retired API and can
  echo the API key in exception messages. It queues requests to the free-key
  concurrency limit, retries rate limits and server errors with backoff, and
  caches pages and metadata.
- Filters, columns and dates are checked against the table's live metadata
  before a request is spent.
- Errors reach the model as text with a short label (`[AUTH]`,
  `[RATE_LIMIT]`, `[SUBSCRIPTION]`, `[NOT_FOUND]`, `[INVALID_REQUEST]`,
  `[UPSTREAM]`, `[BLOCKED]`) and say what to do next.
- Results are capped by `limit` and by a response-size budget
  (`NDL_MAX_RESPONSE_BYTES`), and each tool call has an overall deadline
  (`NDL_TOOL_DEADLINE_SECONDS`, 50 s) below common client timeouts.
- Unknown tool arguments are rejected instead of silently ignored.
- The Docker image is a multi-stage build from `uv.lock` that runs the console
  script as a non-root user.
- Packaging moves to hatchling; `uv.lock` is committed.
- The documentation site moves from Docusaurus to Mintlify (`docs/`).

### Removed

- The `nasdaq-data-link` and `pycountry` dependencies.
- The conda recipe and package.
- The Docusaurus documentation site.

### Fixed

- The server failed to import with MCP SDK 2.x, because the unpinned `mcp`
  dependency resolved to a version without `mcp.server.fastmcp`.
- Country `UK` resolved to Ukraine; the indicator search returned
  merchandise trade for `GDP`.
- The Nasdaq Fund Network tools described tables wrongly: NFN/MFRPH holds
  portfolio holdings, not price history, and NFN/MFRPM holds portfolio
  managers, not fees. The benchmark tool read NFN/MFRPRB, which does not
  exist.

### Security

- The `v0.2.1` Docker image (`stefanoamorelli/nasdaq-data-link-mcp:v0.2.1`,
  also `latest` until this release) was built with `COPY . .` and no
  `.dockerignore`, so it contains the files of the build directory, including
  `.env`, `.secrets` and `.git`. Do not use it. Images you built yourself from
  a checkout of 0.2.1 to 1.0.0 have the same problem with your own files:
  rebuild them, and rotate any key that was in the build directory. A
  `.dockerignore` allowlist now admits only the files the image needs, and CI
  checks the image for stray files and a non-root user.
- `ndl_sql_query` accepts a single read-only statement, rejects control
  characters (Trino ends `--` comments at a carriage return), and blocks
  `current_user`, `session_user`, `current_groups` and the `system` catalog,
  because Trino reports the API key as the session user.
- The API key is sent only in request headers, never in URLs, and is removed
  from every tool result and error message, including reversed, case-changed,
  hex and base64 forms.
- `.env` is read only from the working directory (or `--env-file`), never
  from parent directories, and cannot set `NDL_BASE_URL`; `NDL_BASE_URL` must
  be a bare `https://` origin.
- The HTTP transports require `NDL_HTTP_TOKEN` (bearer token) for any
  non-loopback bind, check the `Host` header on loopback, and accept
  `NDL_ALLOWED_HOSTS` behind a public name.

## [0.2.0] - 2025-05-17

### Added
- Added comprehensive Nasdaq Fund Network (NFN) tools:
  - `get_fund_information` - Fund Information Report (MFRFI)
  - `get_share_class_master` - Fund Share Class Master (MFRSM)
  - `get_share_class_information` - Fund Share Class Information (MFRSI)
  - `get_price_history` - Fund Price History (MFRPH)
  - `get_recent_price_history` - Fund Price History 10-day (MFRPH10)
  - `get_performance_statistics` - Fund Performance Statistics (MFRPS)
  - `get_performance_benchmark` - Fund Performance Benchmark (MFRPRB)
  - `get_performance_analytics` - Fund Performance Analytics (MFRPA)
  - `get_fees_and_expenses` - Fund Fee and Expense Data (MFRPM)
  - `get_monthly_flows` - Fund Monthly Flows (MFRMF)
- Enhanced NFN documentation with detailed data structures for each tool
- Added new example conversations demonstrating NFN tool usage
- Updated architecture diagram to include all NFN modules

## [0.1.3] - 2025-04-30

### Added
- Initial release with support for:
  - Equities 360 database
  - Retail Trading Activity Tracker (RTAT)
  - Trade Summary database (NDAQ/TS)
  - World Bank dataset
  - Basic Nasdaq Fund Network support (MFRFM only)

[2.0.0]: https://github.com/stefanoamorelli/nasdaq-data-link-mcp/compare/v1.0.0...HEAD
[0.2.0]: https://github.com/stefanoamorelli/nasdaq-data-link-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/stefanoamorelli/nasdaq-data-link-mcp/releases/tag/v0.1.3
