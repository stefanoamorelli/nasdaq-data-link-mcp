# Nasdaq Data Link MCP

[![PyPI](https://img.shields.io/pypi/v/nasdaq-data-link-mcp-os)](https://pypi.org/project/nasdaq-data-link-mcp-os/)
[![Python versions](https://img.shields.io/pypi/pyversions/nasdaq-data-link-mcp-os)](https://pypi.org/project/nasdaq-data-link-mcp-os/)
[![CI](https://github.com/stefanoamorelli/nasdaq-data-link-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/stefanoamorelli/nasdaq-data-link-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker pulls](https://img.shields.io/docker/pulls/stefanoamorelli/nasdaq-data-link-mcp)](https://hub.docker.com/r/stefanoamorelli/nasdaq-data-link-mcp)

<!-- mcp-name: io.github.stefanoamorelli/nasdaq-data-link-mcp -->

An open-source [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server for the [Nasdaq Data Link](https://data.nasdaq.com) Tables API. It runs
next to your MCP client (Claude Desktop, Claude Code, Cursor, VS Code and
others) with your own API key and gives the model 38 read-only tools: search
over a bundled catalog of Nasdaq Data Link tables, generic table queries and
exports, DataLink SQL, and typed tools for US equities, mutual funds, World Bank
and IMF statistics, commodities, crypto, US housing and carbon removal markets.
A free Nasdaq Data Link API key is enough for most of them.

> [!IMPORTANT]
> This is a community project. It is not affiliated with, endorsed by or
> supported by Nasdaq, Inc. Nasdaq® is a registered trademark of Nasdaq, Inc.
> What you can read through it is decided by your Nasdaq Data Link account and
> its terms of use.

**Contents:**
[Official Nasdaq server](#official-nasdaq-data-link-mcp-server) ·
[What changed in 2.0](#what-changed-in-20) ·
[Quick start](#quick-start) ·
[Free API key](#what-a-free-api-key-gets) ·
[Tools](#tools) ·
[Resources and prompts](#resources-and-prompts) ·
[Configuration](#configuration) ·
[HTTP mode](#http-mode) ·
[Example questions](#example-questions) ·
[Troubleshooting](#troubleshooting) ·
[Development](#development) ·
[Releasing](#releasing) ·
[Security](#security) ·
[Citation](#citation)

## Official Nasdaq Data Link MCP server

Nasdaq now runs its own MCP server for Data Link
([overview](https://data.nasdaq.com/model-context-protocol),
[product page](https://www.nasdaq.com/products/data/data-link/mcp)). Going by
Nasdaq's pages, it is a hosted service for Data Link clients: you request
access from Nasdaq through the product page ("Get Connected", "Contact Us"),
its ClientSuccess team (ClientSuccess@nasdaq.com) handles support, Nasdaq
issues an OAuth client ID with Okta-based identity verification during
onboarding, and your product entitlements are enforced on every call. Its tools search data providers, list the data in your
subscription, return product documentation and table metadata, and run SQL
queries.

This project is independent of it:

| | Nasdaq's MCP server | This project |
|---|---|---|
| Runs | Hosted by Nasdaq | On your machine (stdio) or on a server you run (HTTP, Docker); MIT-licensed |
| Access | Onboarding through Nasdaq; OAuth client and Okta sign-in | Your Nasdaq Data Link API key; a free key works |
| Entitlements | Enforced by Nasdaq's server | Those of your API key, enforced by the Nasdaq API |
| Tools | Provider search, subscribed-data discovery, product documentation, table metadata, SQL | Catalog search, table metadata, generic queries and exports, DataLink SQL, and 32 typed tools for specific datasets |

If you are a Nasdaq Data Link client and want a service Nasdaq supports, start
with Nasdaq's server. This one fits local or self-hosted setups, free API keys,
and questions that the typed tools answer directly (a company's fundamentals,
COT positioning, a country's GDP, a ZIP code's home values).

## What changed in 2.0

Version 2.0 is a rewrite. Nasdaq retired the time-series API (the
`datasets`/`databases` endpoints and codes such as `WIKI/AAPL` or `FRED/GDP`).
The five tools on `main` since PR #16, which the Docker MCP Catalog image also
runs, called that API, so every call failed with HTTP 403 or 410; the server
also stopped importing once MCP SDK 2.x was released. 2.0 is built on the
Tables API, which Nasdaq still serves, and on MCP SDK 2.x:

- 38 tools named `ndl_*`, grouped in 11 toolsets that you can enable
  selectively.
- A bundled list of the tables the tools read plus every free table, with
  what a free key gets from each (full data, a fixed sample, or nothing),
  since Nasdaq has no search endpoint. The names and descriptions in it are
  written for this project.
- Compact JSON results with structured content, row limits, a response-size
  budget, and errors that start with a short label (`[AUTH]`,
  `[SUBSCRIPTION]`, ...).
- Installable with `uvx` or Docker, Python 3.11 or newer.
- stdio by default; Streamable HTTP and SSE with bearer-token authentication.

[CHANGELOG.md](CHANGELOG.md) lists every change.

### Migrating from earlier versions

Tools from PR #16 (on `main` since October 2025, and in the Docker MCP Catalog
image):

| Old tool | Use instead |
|---|---|
| `search_datasets` | `ndl_search_tables` (searches the bundled catalog) |
| `get_dataset` | `ndl_query_table` with a `VENDOR/TABLE` code, or a typed tool |
| `get_dataset_metadata` | `ndl_describe_table` |
| `list_databases` | `ndl_search_tables` with `vendor`, or the `ndl://catalog` resource |
| `export_dataset` | `ndl_export_table` (returns a zipped CSV link) |
| resource `nasdaq://databases` | resource `ndl://catalog` |

Tools from 0.x and 1.0 (PyPI 0.2.0, Docker image `v0.2.1`):

| Old tool | Use instead |
|---|---|
| `get_rtat10`, `get_rtat` | `ndl_get_retail_trading_activity` with `dataset="rtat10"` or `"rtat"` |
| `get_indicator_value` | `ndl_get_world_bank_data` |
| `list_worldbank_indicators`, `search_worldbank_indicators` | `ndl_search_world_bank_indicators` |
| `country_code` | not needed: `countries` takes names, ISO2/ISO3 codes and aggregates |
| `get_stock_stats` | `ndl_get_equities360` with `dataset="statistics"` |
| `get_fundamental_data` | `ndl_get_equities360` with `dataset="fundamentals_summary"` |
| `get_detailed_financials` | `ndl_get_equities360` with `dataset="fundamentals_details"` |
| `get_balance_sheet_data` | `ndl_get_equities360` with `dataset="balance_sheet"` |
| `get_cash_flow_data` | `ndl_get_equities360` with `dataset="cash_flow"` |
| `get_corporate_action_data` | `ndl_get_equities360` with `dataset="corporate_actions"` |
| `get_company_reference_data` | `ndl_get_equities360` with `dataset="reference_data"` |
| `list_stock_stat_fields` and the six other `list_*_fields` tools | `ndl_describe_table` with the table code, e.g. `NDAQ/STAT` |
| `get_trade_summary_data` | `ndl_query_table` on `NDAQ/TS` (subscription only) |
| `get_fund_master_report` | `ndl_search_mutual_funds`, or `ndl_get_mutual_fund_report` with `report="fund_master"` |
| `get_fund_information` | `ndl_get_mutual_fund_report` with `report="fund_info"` |
| `get_share_class_master` | `ndl_get_mutual_fund_report` with `report="share_classes"` |
| `get_share_class_information` | `ndl_get_mutual_fund_report` with `report="fees"` (NFN/MFRSI) |
| `get_price_history` | `ndl_get_mutual_fund_report` with `report="holdings"`: it read NFN/MFRPH, which holds portfolio holdings, not prices |
| `get_recent_price_history` | `ndl_get_mutual_fund_report` with `report="top_holdings"` (NFN/MFRPH10, top 10 holdings) |
| `get_performance_statistics` | `ndl_get_mutual_fund_report` with `report="pricing"` (NFN/MFRPS) |
| `get_performance_benchmark` | `ndl_get_mutual_fund_report` with `report="benchmarks"` (it read NFN/MFRPRB, which does not exist; benchmarks are NFN/MFRPB) |
| `get_performance_analytics` | `ndl_get_mutual_fund_report` with `report="performance"` (NFN/MFRPA) |
| `get_fees_and_expenses` | `ndl_get_mutual_fund_report` with `report="fees"`; the old tool read NFN/MFRPM, which is `report="managers"` |
| `get_monthly_flows` | `ndl_get_mutual_fund_report` with `report="flows"` (subscription only) |

Equities 360 needs a paid subscription. With a free key, use
`ndl_search_tickers`, `ndl_get_fundamentals` and `ndl_get_stock_prices`, which
read Sharadar's free ticker list and samples.

Other changes when upgrading:

- No more `mcp install nasdaq_data_link_mcp_os/server.py` or `PYTHONPATH`: run
  the published package with `uvx nasdaq-data-link-mcp-os`, or the
  `nasdaq-data-link-mcp` command from a checkout.
- Python 3.11 or newer, MCP SDK 2.x. The `nasdaq-data-link` SDK and `pycountry`
  are no longer dependencies.
- Docker tags drop the `v`: a release `2.0.0` is tagged `2.0.0`, `2.0`, `2` and
  `latest`.
- The conda package is gone; it shipped an empty package.

## Quick start

1. Create a free API key at <https://data.nasdaq.com/sign-up>. It is shown in
   your account settings on data.nasdaq.com.
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), whose
   `uvx` command runs the server from PyPI without a separate install. Check
   that it works:

   ```bash
   uvx nasdaq-data-link-mcp-os --version
   ```

3. Add the server to your client as shown below, restart the client, and ask
   "Check my Nasdaq Data Link API status." The `ndl_check_api_status` tool
   reports whether the key works and how many calls it has left today.

### Claude Desktop

Open Settings > Developer > Edit Config and add the server to
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nasdaq-data-link": {
      "command": "uvx",
      "args": ["nasdaq-data-link-mcp-os"],
      "env": {
        "NASDAQ_DATA_LINK_API_KEY": "your_api_key"
      }
    }
  }
}
```

If Claude Desktop reports that it cannot start `uvx`, use the absolute path
that `which uvx` prints: apps started from the dock do not see your shell's
`PATH`.

### Claude Code

```bash
claude mcp add nasdaq-data-link -e NASDAQ_DATA_LINK_API_KEY=your_api_key -- uvx nasdaq-data-link-mcp-os
```

Add `--scope user` to make it available in every project.

### Cursor

Put the same `mcpServers` block as for Claude Desktop in `~/.cursor/mcp.json`
(all projects) or `.cursor/mcp.json` (one project).

### VS Code

`.vscode/mcp.json` in your workspace; VS Code asks for the key on first start
and stores it:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "ndl-api-key",
      "description": "Nasdaq Data Link API key",
      "password": true
    }
  ],
  "servers": {
    "nasdaq-data-link": {
      "type": "stdio",
      "command": "uvx",
      "args": ["nasdaq-data-link-mcp-os"],
      "env": {
        "NASDAQ_DATA_LINK_API_KEY": "${input:ndl-api-key}"
      }
    }
  }
}
```

### Docker

The image `stefanoamorelli/nasdaq-data-link-mcp` (linux/amd64 and linux/arm64)
runs the same server over stdio as a non-root user. For any client that takes
an `mcpServers` block:

```json
{
  "mcpServers": {
    "nasdaq-data-link": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "NASDAQ_DATA_LINK_API_KEY",
        "stefanoamorelli/nasdaq-data-link-mcp:2"
      ],
      "env": {
        "NASDAQ_DATA_LINK_API_KEY": "your_api_key"
      }
    }
  }
}
```

`-e NASDAQ_DATA_LINK_API_KEY` without a value passes the variable from the
client's environment into the container, so the key does not appear in the
`docker run` arguments. Other [settings](#configuration) work the same way:
add `"-e", "NDL_TOOLSETS"` to `args` and the value to `env`.

The server is also listed in the Docker MCP Catalog as
[`nasdaq-data-link`](https://hub.docker.com/mcp/server/nasdaq-data-link/overview)
(image `mcp/nasdaq-data-link`). Docker builds that image from a commit pinned
in [docker/mcp-registry](https://github.com/docker/mcp-registry/tree/main/servers/nasdaq-data-link);
until the pin moves to a 2.x release, the catalog image runs the five pre-2.0
tools, which no longer work. Use the image above in the meantime.

### From a checkout

```bash
git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
cd nasdaq-data-link-mcp
uv sync
uv run nasdaq-data-link-mcp --version
```

In the client configuration, use `"command": "uv"` and
`"args": ["--directory", "/absolute/path/to/nasdaq-data-link-mcp", "run", "nasdaq-data-link-mcp"]`.

## What a free API key gets

Nasdaq Data Link has three kinds of tables for a key without subscriptions. The
bundled table list records which kind each listed table is, `ndl_search_tables`
can filter on it, and every result carries an `access` field:

| Access | A free key gets | Examples |
|---|---|---|
| `free` | Full data | World Bank indicators, Nasdaq RTAT10 retail activity, ticker changes, the Sharadar ticker list, CFTC Commitments of Traders, crypto, Zillow, IMF WEO, carbon removal registry |
| `sample` | A fixed sample; queries outside it return 0 rows, not an error | Sharadar fundamentals, prices, insider and 8-K data (about 30 large US stocks; prices for late 2018 only), Zacks estimates (about 30 large US stocks), Nasdaq Fund Network fund data (a few dozen funds), the full RTAT universe (a few tickers on one day in 2016) |
| `subscription` | An access error (`[SUBSCRIPTION]`) | Nasdaq company fundamentals, Sharadar 13F holdings, mutual fund flows and monthly returns, carbon removal reference prices |
| `unknown` | Tables outside the bundled list; depends on your subscriptions | Premium tables that no typed tool reads |

A free key also has rate limits: one request at a time, 300 calls per 10
seconds, 2,000 per 10 minutes and 50,000 per day. The server queues its own
requests to stay inside them (`NDL_MAX_CONCURRENCY=1`).

Several free tables are no longer updated by Nasdaq. The tools say where their
data ends, and results add a note when a table has not been refreshed for more
than 45 days. As of the catalog snapshot: the CFTC COT reports end with the
2026-06-09 report, Bitfinex prices and Bitcoin blockchain metrics in June 2026,
Zillow home values in the first half of 2025 and rents in July 2022, the ICE
BofA bond indices on 2025-02-27, JODI in December 2024, the LME warehouse
stocks on 2024-07-30, the USDA WASDE reports with the February 2024 report,
the OPEC basket price on 2024-01-25, and the IMF data is the April 2023 World
Economic Outlook. World Bank data runs to 2023. Retail activity (RTAT10),
ticker changes, the Sharadar ticker list and the carbon removal tables are
current.

<!-- free-tables:start -->
<!-- Generated by scripts/generate_tool_docs.py; do not edit by hand. -->

The catalog snapshot of 2026-10-05 has 77 tables: 34 free, 29 sample, 14 subscription. These are the 34 that a free key reads in full. A table counts as current when Nasdaq refreshed it within 45 days of the snapshot; tool results add a staleness note past that age.

| Table | Contents | Read with | Last refreshed by Nasdaq |
|---|---|---|---|
| `AR/MWIF` | ICE futures contract list | `ndl_query_table` | 2026-10-03 (current) |
| `AR/OWIF` | ICE options-on-futures contract list | `ndl_query_table` | 2026-10-03 (current) |
| `BC/FUT` | Futures commodity codes (Barchart) | `ndl_query_table` | 2023-06-27 |
| `EDI/PITSTY` | Security type codes (EDI) | `ndl_query_table` | 2025-11-29 |
| `NDAQ/COLT` | Carbon removal certificate transactions | `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/FAFD` | Carbon removal facilities | `ndl_get_carbon_removal_facilities`, `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/FIRC` | Carbon removal volumes by facility and year | `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/IRBM` | Carbon removal volumes by methodology and year | `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/RITM` | Carbon removal certificate retirements | `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/RTAT10` | Retail trading activity, daily top 10 (Nasdaq) | `ndl_get_retail_trading_activity`, `ndl_sql_query` | 2026-10-03 (current) |
| `NDAQ/SYVW` | Carbon removal certificate bundles | `ndl_get_carbon_removal_data` | 2026-10-03 (current) |
| `NDAQ/TC` | US ticker changes (Nasdaq) | `ndl_get_ticker_changes` | 2026-10-02 (current) |
| `QDL/BCHAIN` | Bitcoin network metrics | `ndl_get_blockchain_metrics` | 2026-06-23 |
| `QDL/BITFINEX` | Crypto exchange rates (Bitfinex) | `ndl_get_crypto_prices` | 2026-06-22 |
| `QDL/CITS` | CFTC index trader supplement | `ndl_get_cot_report` | 2026-06-20 |
| `QDL/FCR` | CFTC concentration ratios | `ndl_get_cot_report` | 2026-06-20 |
| `QDL/FON` | CFTC disaggregated commitments of traders | `ndl_get_cot_report` | 2026-06-20 |
| `QDL/JODI` | Oil and gas statistics by country (JODI) | `ndl_get_jodi_energy_data` | 2025-02-24 |
| `QDL/LFON` | CFTC legacy commitments of traders | `ndl_get_cot_report` | 2026-06-20 |
| `QDL/LME` | Metal warehouse stocks (LME) | `ndl_get_lme_warehouse_stocks` | 2024-08-01 |
| `QDL/ML` | Corporate bond index yields | `ndl_get_bond_index_yields` | 2025-03-02 |
| `QDL/ODA` | IMF country macro series | `ndl_get_imf_weo_data` | 2023-10-31 |
| `QDL/OPEC` | OPEC crude basket price | `ndl_get_opec_basket_price` | 2024-01-26 |
| `QUOTEMEDIA/TICKERS` | Ticker list (QuoteMedia) | `ndl_query_table` | 2025-05-31 |
| `SHARADAR/INDICATORS` | Column dictionary (Sharadar) | `ndl_search_financial_metrics`, `ndl_get_company_events` | 2026-09-25 (current) |
| `SHARADAR/TICKERS` | US ticker master (Sharadar) | `ndl_search_tickers` | 2026-10-03 (current) |
| `WASDE/DATA` | USDA supply and demand estimates | `ndl_get_wasde_data` | 2024-02-14 |
| `WASDE/METADATA` | USDA WASDE report tables | `ndl_get_wasde_data` | 2024-02-14 |
| `WB/DATA` | World Bank development indicators | `ndl_get_world_bank_data` | 2025-08-23 |
| `WB/METADATA` | World Bank indicator list | `ndl_search_world_bank_indicators`, `ndl_get_world_bank_data` | 2026-06-23 |
| `WIKI/PRICES` | US stock prices, community data (WIKI) | `ndl_query_table` | 2018-03-27 |
| `ZILLOW/DATA` | Zillow housing series | `ndl_get_zillow_data` | 2025-07-20 |
| `ZILLOW/INDICATORS` | Zillow indicator list | `ndl_get_zillow_data`, `ndl_search_zillow_indicators` | 2025-07-20 |
| `ZILLOW/REGIONS` | Zillow region list | `ndl_search_zillow_regions`, `ndl_get_zillow_data` | 2025-07-20 |

<!-- free-tables:end -->

## Tools

<!-- tools:start -->
<!-- Generated by scripts/generate_tool_docs.py; do not edit by hand. -->

38 tools in 11 toolsets. `core` is always on; `NDL_TOOLSETS` or `--toolsets` picks the others. Bold parameters are required. *Free key* is what a free API key gets from the tables the tool reads (catalog snapshot 2026-10-05).

### core

Catalog search, table schemas, generic queries, exports. Always on. Reference: [docs/tools/core.mdx](docs/tools/core.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_search_tables` | Search a bundled list of Nasdaq Data Link tables by keyword. | `query`, `access`, `vendor` | No API call |
| `ndl_describe_table` | Show a table's columns, filterable columns, primary key and freshness. | **`table_code`** | Depends on the table |
| `ndl_query_table` | Read rows from any Nasdaq Data Link table, with filters and paging. | **`table_code`**, `filters`, `sort_by` | Depends on the table |
| `ndl_export_table` | Request a full (filtered) table export as a zipped CSV download link. | **`table_code`**, `filters`, `wait_seconds` | Depends on the table |
| `ndl_check_api_status` | Check the API key, the remaining daily call quota and the enabled toolsets. | none | Free (one request to NDAQ/RTAT10) |

### sql

DataLink SQL (Trino) queries over the tables your key can read. Reference: [docs/tools/sql.mdx](docs/tools/sql.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_sql_query` | Run a read-only SQL statement on DataLink SQL (Nasdaq's Trino endpoint). | **`sql`** | Usually NDAQ/RTAT and NDAQ/RTAT10 only |

### nasdaq

Nasdaq datasets: retail trading activity, ticker changes, Equities 360. Reference: [docs/tools/nasdaq.mdx](docs/tools/nasdaq.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_get_retail_trading_activity` | Daily retail activity share and net sentiment for US tickers (Nasdaq RTAT). | `tickers`, `dataset`, `start_date`/`end_date` | Free: NDAQ/RTAT10; sample: NDAQ/RTAT |
| `ndl_get_ticker_changes` | US ticker symbol changes and new listings, keyed by FIGI (NDAQ/TC, free, daily). | `tickers`, `figis`, `resolve_history`, `start_date`/`end_date` | Free |
| `ndl_get_equities360` | Nasdaq Equities 360 company data; needs a paid subscription (no free sample). | **`dataset`**, `tickers`, `dimension`, `contra_tickers`, `start_date`/`end_date` | Subscription only |

### equities

US equities from Sharadar and Zacks: tickers, fundamentals, prices, estimates. Reference: [docs/tools/equities.mdx](docs/tools/equities.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_search_tickers` | Find US stocks and ETFs by ticker or company name (free Sharadar ticker master). | `tickers`, `query`, `security_type`, `exchange`, `category`, +2 more | Free |
| `ndl_get_fundamentals` | Get income statement, balance sheet, cash flow and ratio data from Sharadar SF1. | **`tickers`**, `dimension`, `date_field`, `metrics`, `start_date`/`end_date` | Sample |
| `ndl_search_financial_metrics` | Search the Sharadar data dictionary for field codes, titles, units and meaning. | `query`, `table` | Free |
| `ndl_get_stock_prices` | Get daily open/high/low/close/volume for US stocks (SEP) or funds and ETFs (SFP). | **`tickers`**, `security_type`, `start_date`/`end_date` | Sample |
| `ndl_get_valuation_metrics` | Get daily market cap, enterprise value and P/E, P/B, P/S, EV/EBIT, EV/EBITDA. | **`tickers`**, `start_date`/`end_date` | Sample |
| `ndl_get_corporate_actions` | Get dividends, splits, M&A, ticker changes and delistings (SHARADAR/ACTIONS). | `tickers`, `actions`, `start_date`/`end_date` | Sample |
| `ndl_get_sp500_constituents` | List S&P 500 members now, at a past quarter-end, or the history of index changes. | `view`, `tickers`, `as_of`, `start_date`/`end_date` | Sample |
| `ndl_get_insider_transactions` | Get insider purchases, sales, grants and holdings from SEC Forms 3/4/5 (SF2). | `tickers`, `owner_name`, `security`, `transactions_only`, `start_date`/`end_date` | Sample |
| `ndl_get_institutional_holdings` | Needs a paid Sharadar SF3 subscription (no free sample): 13F holdings data. | `dataset`, `tickers`, `investor_id`, `investor_name`, `security_type`, +1 more | Subscription only |
| `ndl_get_company_events` | Get material corporate events reported on SEC Form 8-K, with decoded event names. | `tickers`, `event_codes`, `start_date`/`end_date` | Sample: SHARADAR/EVENTS; free: SHARADAR/INDICATORS |
| `ndl_get_analyst_estimates` | Get Zacks consensus estimates, surprises, ratings, price targets, report dates. | **`tickers`**, `dataset`, `period_type`, `start_date`/`end_date` | Sample |

### funds

Nasdaq Fund Network mutual fund and closed-end fund reports (NFN/MFR*): fund search, fees, returns, holdings, managers. Reference: [docs/tools/funds.mdx](docs/tools/funds.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_search_mutual_funds` | Find mutual funds and their share classes by ticker, name, CUSIP or id. | `query` | Sample |
| `ndl_get_mutual_fund_report` | Read a Nasdaq Fund Network mutual fund report (NFN/MFR*). | **`report`**, `tickers`, `security_ids`, `fund_ids`, `benchmark_ids`, +1 more | Sample (10 tables); subscription: NFN/MFRMF, NFN/MFRMR |

### world_bank

World Bank World Development Indicators (WB/DATA, WB/METADATA), free. Reference: [docs/tools/world_bank.mdx](docs/tools/world_bank.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_search_world_bank_indicators` | Find World Bank indicator series_ids by keyword (GDP, inflation, literacy, CO2). | **`query`** | Free, last refreshed 2026-06-23 |
| `ndl_get_world_bank_data` | Get yearly World Bank indicator values for countries and aggregates (WB/DATA). | **`indicators`**, **`countries`**, `start_date`/`end_date` | Free, last refreshed 2025-08-23 |

### macro

Macro series: IMF World Economic Outlook (April 2023 edition, annual to 2028) and ICE BofA corporate bond index yields (daily, ending 2025-02-27). Reference: [docs/tools/macro.mdx](docs/tools/macro.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_get_imf_weo_data` | Get IMF World Economic Outlook annual data (GDP, growth, inflation, debt). | `indicators`, `countries`, `include_projections`, `series_codes`, `start_date`/`end_date` | Free, last refreshed 2023-10-31 |
| `ndl_get_bond_index_yields` | Get ICE BofA corporate bond index yields, spreads and returns (ends 2025-02-27). | `series`, `start_date`/`end_date` | Free, last refreshed 2025-03-02 |

### commodities

Commodities: CFTC Commitments of Traders, JODI energy, OPEC basket price, LME warehouse stocks, USDA WASDE. Reference: [docs/tools/commodities.mdx](docs/tools/commodities.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_get_cot_report` | Weekly CFTC Commitments of Traders positions for one futures market. | **`contract`**, `report`, `measure`, `include_options`, `crop`, +1 more | Free, last refreshed 2026-06-20 |
| `ndl_get_jodi_energy_data` | Monthly oil and gas production, demand, trade and stocks by country (JODI). | **`countries`**, `product`, `flow`, `unit`, `codes`, +1 more | Free, last refreshed 2025-02-24 |
| `ndl_get_opec_basket_price` | Daily OPEC Reference Basket crude oil price in US dollars per barrel. | `start_date`/`end_date` | Free, last refreshed 2024-01-26 |
| `ndl_get_lme_warehouse_stocks` | Daily LME warehouse stock levels in tonnes by metal and location; no prices. | `metals`, `location`, `breakdown`, `start_date`/`end_date` | Free, last refreshed 2024-08-01 |
| `ndl_get_wasde_data` | USDA World Agricultural Supply and Demand Estimates (WASDE) report tables. | **`query`**, `report_month`, `region`, `item` | Free, last refreshed 2024-02-14 |

### crypto

Crypto: Bitfinex daily prices and Bitcoin on-chain metrics (free). Reference: [docs/tools/crypto.mdx](docs/tools/crypto.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_get_crypto_prices` | Daily Bitfinex crypto prices (last, bid, ask, mid, high, low, volume) by pair. | **`pairs`**, `fields`, `start_date`/`end_date` | Free, last refreshed 2026-06-22 |
| `ndl_get_blockchain_metrics` | Daily Bitcoin network metrics: price, hash rate, difficulty, fees, transactions. | **`metrics`**, `start_date`/`end_date` | Free, last refreshed 2026-06-23 |

### housing

US housing from Zillow (free): home values, rents, inventory and sales by state, metro, county, city, ZIP and neighborhood, 1996 to mid-2025. Reference: [docs/tools/housing.mdx](docs/tools/housing.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_search_zillow_regions` | Find Zillow region ids (state, metro, county, city, ZIP, neighborhood) by name. | **`query`**, `region_type` | Free, last refreshed 2025-07-20 |
| `ndl_get_zillow_data` | Get Zillow home values, rents, inventory or sales for up to 10 US regions. | **`indicator`**, **`regions`**, `region_type`, `start_date`/`end_date` | Free, last refreshed 2025-07-20 |
| `ndl_search_zillow_indicators` | Search the 56 Zillow indicators by keyword, category or region type. | `query`, `category`, `region_type` | Free, last refreshed 2025-07-20 |

### carbon

Carbon removal certificates (Puro.earth CORC) published by Nasdaq. Reference: [docs/tools/carbon.mdx](docs/tools/carbon.mdx).

| Tool | What it does | Main parameters | Free key |
|---|---|---|---|
| `ndl_get_carbon_removal_facilities` | List Puro.earth carbon removal facilities: location, methodology, owner, auditor. | `facilities`, `country`, `region`, `methodology`, `durability_category` | Free |
| `ndl_get_carbon_removal_data` | Get Puro.earth carbon removal (CORC) volumes, retirements, transactions, prices. | **`dataset`**, `facilities`, `methodology`, `durability_category`, `transaction_type`, +3 more | Free (6 tables); subscription: NDAQ/TRAN |

<!-- tools:end -->

## Resources and prompts

Prompts are templates that a client offers as commands; each one walks the
model through the tools for a common question. Claude Code lists them as slash
commands such as `/mcp__nasdaq-data-link__company_snapshot`. Resources are
read-only documents a client can attach to a conversation.

<!-- prompts-resources:start -->
<!-- Generated by scripts/generate_tool_docs.py; do not edit by hand. -->

Prompts (a prompt is offered only when its toolset is enabled):

| Prompt | Toolset | Arguments | What it asks for |
|---|---|---|---|
| `retail_sentiment_brief` | `nasdaq` | `tickers` (optional), `days` (optional) | Brief on recent retail trading activity and sentiment from Nasdaq RTAT10. |
| `company_snapshot` | `equities` | `ticker` | Build a one-page profile of a US company from the equities tools. |
| `fund_snapshot` | `funds` | `fund` | Profile a mutual fund: objective, fees, returns vs benchmark, top holdings. |
| `country_economic_profile` | `world_bank` | `country` | Economic profile of a country from World Bank indicators, set against World. |
| `cot_positioning_review` | `commodities` | `contract` | Review speculative positioning in one futures market from CFTC COT data. |
| `zillow_housing_snapshot` | `housing` | `place` | Summarize a US housing market from Zillow data on Nasdaq Data Link. |

Resources:

| URI | Type | Contents |
|---|---|---|
| `ndl://catalog` | application/json | The bundled table list: counts by access level and vendor, and every free table. |
| `ndl://guides/query-syntax` | text/markdown | Filter syntax, paging, limits and error labels. |
| `ndl://catalog/{vendor}/{table}` | application/json | Bundled entry (access, filters, notes) for VENDOR/TABLE. |

<!-- prompts-resources:end -->

## Configuration

Every setting is an environment variable, so it can go in the `env` block of
the client configuration. Invalid values stop the server at startup with
`Invalid configuration: ...`.

| Variable | Default | Values | Effect |
|---|---|---|---|
| `NASDAQ_DATA_LINK_API_KEY` | none | your key | Required for every tool that calls Nasdaq. Without it, `ndl_search_tables` still answers (it works offline), `ndl_check_api_status` reports the missing key, and the other tools fail with `[AUTH]`. |
| `NDL_TOOLSETS` | `all` | comma-separated toolset names, or `all` | Toolsets to load. `core` is always loaded. Fewer tools means less context for the model. |
| `NDL_BASE_URL` | `https://data.nasdaq.com` | an `https://` origin, no path | Where requests, and the API key, are sent. Read only from the real environment, never from a `.env` file. |
| `NDL_TIMEOUT_SECONDS` | `30` | 1 or more | Timeout for one HTTP request. |
| `NDL_SQL_TIMEOUT_SECONDS` | `50` | 5 or more | How long a DataLink SQL statement may run before it is cancelled. |
| `NDL_TOOL_DEADLINE_SECONDS` | `50` | 5 or more | Limit for a whole tool call, retries included; below the 60 s request timeout many clients use. |
| `NDL_MAX_RETRIES` | `3` | 0 to 10 | Retries after rate limits and transient errors. |
| `NDL_MAX_CONCURRENCY` | `1` | 1 to 5 | Requests in flight at once. Free keys allow 1, premium keys up to 5. |
| `NDL_CACHE_TTL_SECONDS` | `300` | 0 or more | How long data pages stay cached; 0 disables the cache. |
| `NDL_METADATA_CACHE_TTL_SECONDS` | `21600` | 0 or more | How long table metadata stays cached (6 hours). |
| `NDL_DEFAULT_LIMIT` | `100` | 1 to 1000 | Rows returned when a call gives no `limit` (capped at `NDL_MAX_LIMIT`). A few tools have their own default, such as 52 weeks for COT reports. |
| `NDL_MAX_LIMIT` | `1000` | 1 to 1000 | Upper bound for any `limit`. |
| `NDL_MAX_RESPONSE_BYTES` | `100000` | 5000 to 5000000 | Size budget for one result; rows beyond it are dropped and `has_more` is set. 100 kB of compact JSON is roughly 25,000 to 35,000 tokens. |
| `NDL_LOG_LEVEL` | `WARNING` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Log level; logs go to stderr. |
| `NDL_HTTP_TOKEN` | none | any string | Bearer token for the HTTP transports. Required when binding anything but loopback. |
| `NDL_ALLOWED_HOSTS` | none | comma-separated host names | Host names the HTTP transports accept. See [HTTP mode](#http-mode). |

Command-line options of `nasdaq-data-link-mcp` (the same as
`nasdaq-data-link-mcp-os`):

| Option | Default | Effect |
|---|---|---|
| `--transport {stdio,streamable-http,sse}` | `stdio` | Transport. |
| `--host HOST` | `127.0.0.1` | Bind address for the HTTP transports. Any other address requires `NDL_HTTP_TOKEN`. |
| `--port PORT` | `8000` | Port for the HTTP transports. |
| `--toolsets LIST` | `NDL_TOOLSETS`, else all | Comma-separated toolsets; overrides `NDL_TOOLSETS`. |
| `--env-file PATH` | `./.env` | Read the API key and `NDL_*` settings from this file. The server exits if it does not exist. |
| `--version` | | Print the version and exit. |

`.env` files: at startup the server reads `.env` from its working directory,
not from parent directories, or the file given with `--env-file`. It takes
`NASDAQ_DATA_LINK_API_KEY` and `NDL_*` variables from it, except `NDL_BASE_URL`,
and variables already set in the environment win. MCP clients often start
servers in a directory you did not choose, so put settings in the client's
`env` block or pass `--env-file` with an absolute path.
[.env.example](.env.example) lists every variable.

## HTTP mode

stdio is the default and needs no network port. To share one server between
clients, or run it on another machine, use Streamable HTTP (or SSE for older
clients):

```bash
NASDAQ_DATA_LINK_API_KEY=your_api_key uvx nasdaq-data-link-mcp-os --transport streamable-http
```

This listens on `http://127.0.0.1:8000/mcp` (SSE: `--transport sse`, endpoint
`/sse`). On loopback no token is needed, and requests whose `Host` header is
not a loopback name are rejected with HTTP 421, which blocks DNS-rebinding
attacks from web pages.

Every tool call spends your API key's quota, and the HTTP transports have no
user accounts, so any other bind address requires a token:

```bash
export NDL_HTTP_TOKEN="$(openssl rand -hex 32)"
uvx nasdaq-data-link-mcp-os --transport streamable-http --host 0.0.0.0 --port 8000
```

Without `NDL_HTTP_TOKEN` the server refuses to start. Clients send
`Authorization: Bearer <token>`; anything else gets HTTP 401. With Claude Code:

```bash
claude mcp add --transport http nasdaq-data-link http://127.0.0.1:8000/mcp --header "Authorization: Bearer $NDL_HTTP_TOKEN"
```

When clients reach the server under a public name, for example behind a
reverse proxy, set `NDL_ALLOWED_HOSTS=mcp.example.com` (comma-separated) to
check the `Host` and `Origin` headers against that list. The list replaces the
default, so include `127.0.0.1` or `localhost` if local clients connect
directly. On a non-loopback bind without `NDL_ALLOWED_HOSTS`, host checks are
off and the token is the only control. The server speaks plain HTTP; put a TLS
proxy in front of it for anything beyond your own machine.

With Docker, the server has to bind `0.0.0.0` inside the container, so it needs
a token; publish the port on loopback only:

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -e NASDAQ_DATA_LINK_API_KEY -e NDL_HTTP_TOKEN \
  stefanoamorelli/nasdaq-data-link-mcp:2 \
  --transport streamable-http --host 0.0.0.0
```

## Example questions

Each of these works with a free key; the tool the model is likely to use is in
parentheses.

- "Which stocks had the largest share of retail trading yesterday, and was
  retail buying or selling them?" (`ndl_get_retail_trading_activity`)
- "Rank the tickers that appeared most often in the RTAT top 10 this year."
  (`ndl_sql_query`)
- "When did Facebook change its ticker to META?" (`ndl_get_ticker_changes`)
- "Show Apple's revenue, net income and free cash flow for 2022 and 2023."
  (`ndl_get_fundamentals`, free sample)
- "Compare GDP growth in Italy, Spain and the euro area since 2010."
  (`ndl_get_world_bank_data`)
- "What did the IMF project in April 2023 for Brazil's inflation in 2025?"
  (`ndl_get_imf_weo_data`)
- "How were money managers positioned in gold futures in the latest COT
  report?" (`ndl_get_cot_report`)
- "How did the typical home value (Zillow ZHVI) in Austin, TX change between
  2020 and 2025?" (`ndl_search_zillow_regions`, `ndl_get_zillow_data`)
- "Which Puro.earth facilities issued the most carbon removal certificates
  this year?" (`ndl_get_carbon_removal_data`)
- "Which free tables cover options or futures?" (`ndl_search_tables`)

## Troubleshooting

Tool errors start with a label that says what went wrong.

| Error or symptom | Cause | What to do |
|---|---|---|
| `[AUTH] NASDAQ_DATA_LINK_API_KEY is not set` | The server process has no key. | Add it to the client's `env` block and restart the client. |
| `[AUTH] Nasdaq rejected the API key` | The key is wrong or disabled. | Copy it again from your account settings on data.nasdaq.com; `ndl_check_api_status` tests it. |
| `[RATE_LIMIT]` | Free keys allow one request at a time, 2,000 calls per 10 minutes and 50,000 per day. | Wait and retry. `ndl_check_api_status` shows the calls left today. Several servers or scripts sharing one key compete for the single request slot. |
| `[SUBSCRIPTION]` | The table needs a paid subscription and has no free sample. | `ndl_describe_table` still shows its schema. `ndl_search_tables` with `access="free"` or `"sample"` finds alternatives. |
| 0 rows, with a note starting `Sample data:` | A premium table that gives free keys a fixed sample; the tickers or dates asked for are outside it. | Use the tickers and dates the tool description names (for example 2018-09-04 to 2018-12-31 for Sharadar prices), or a subscription. |
| `[UPSTREAM] The call did not finish within 50.0s` | Nasdaq answered slowly or kept rate limiting until the tool deadline. | Narrow the request (fewer tickers, a shorter date range) and retry. Raise `NDL_TOOL_DEADLINE_SECONDS` only if your client waits longer than 60 s. |
| `[NOT_FOUND] Table WIKI/AAPL does not exist` | A code from the retired time-series API. `FRED/...`, `WIKI/...` and `WORLDBANK/...` codes no longer exist. | Use a `VENDOR/TABLE` code from `ndl_search_tables`, or a typed tool: `ndl_get_stock_prices` for prices (`WIKI/PRICES` still exists but stopped on 2018-03-27), `ndl_get_world_bank_data` and `ndl_get_imf_weo_data` for macro series. |
| `[INVALID_REQUEST]` | A filter on a column that cannot be filtered, a bad date, or an unknown argument. | `ndl_describe_table` lists the filterable columns; dates are `YYYY-MM-DD`. |
| Old data | Some free tables are no longer updated by Nasdaq. | Check `refreshed_at` and `notes` in the result, and the table above. |
| The client lists no tools | The client could not start the server. | Run the configured command in a terminal; with `uvx`, use its absolute path. Claude Desktop writes server logs to `~/Library/Logs/Claude` on macOS. |
| `Refusing to serve on 0.0.0.0 without NDL_HTTP_TOKEN` | HTTP mode on a non-loopback address. | Set `NDL_HTTP_TOKEN`, or bind `127.0.0.1`. |

## Development

```bash
git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
cd nasdaq-data-link-mcp
uv sync                                    # runtime and dev dependencies in .venv
uv run pytest                              # offline tests; no API key needed
uv run ruff check . && uv run ruff format --check .
uv run mypy nasdaq_data_link_mcp_os scripts
uv run python scripts/generate_tool_docs.py   # after changing a tool, prompt or the catalog
uv run pre-commit install                  # ruff and file checks on every commit
```

`uv run pytest -m live` runs the tests marked `live` against the real API. They
need `NASDAQ_DATA_LINK_API_KEY` (a free key is enough), make a little under 200
API calls and take a few minutes; since a free key allows one request at a
time, do not run them while another client uses the same key.
`scripts/refresh_catalog.py` revalidates the access levels, filters and primary
keys in the bundled table list against the API with a free key
(`uv run python scripts/refresh_catalog.py --help`); names, descriptions and
notes in it are written by hand.

CI fails when the generated tool reference is out of date
(`uv run python scripts/generate_tool_docs.py --check`). The documentation site
in [docs/](docs/) uses [Mintlify](https://mintlify.com); preview it with
`npx mint dev` from that directory. [CONTRIBUTING.md](CONTRIBUTING.md) covers
adding a toolset.

## Releasing

1. Set the new version in `pyproject.toml` and `server.json` (its `version`,
   the PyPI package `version`, and the tag of the OCI image identifier), run
   `uv lock`, and replace `Unreleased` in the version's `CHANGELOG.md` heading
   with the release date.
2. Check that the versions agree:
   `uv run python .github/scripts/check_release_version.py vX.Y.Z`.
3. Merge to `main` and publish a GitHub release whose tag is `vX.Y.Z`.

Publishing the release starts two workflows. `publish_pypi.yml` builds the
distributions, uploads them to PyPI with Trusted Publishing, then registers
`server.json` with the MCP Registry once the PyPI release and the Docker image
exist (pre-releases skip the registry). `docker-publish.yml` smoke-tests the
image and pushes `X.Y.Z`, `X.Y`, `X` and `latest` for linux/amd64 and
linux/arm64, with SBOM and provenance attestations; a pre-release gets only its
full version tag.

One-time setup:

- PyPI: add a Trusted Publisher to the `nasdaq-data-link-mcp-os` project with
  owner `stefanoamorelli`, repository `nasdaq-data-link-mcp`, workflow
  `publish_pypi.yml` and environment `pypi`. No PyPI token is stored in GitHub.
- GitHub: create the environments `pypi` and `dockerhub`, each with a required
  reviewer so that every upload waits for approval; limit `dockerhub` to `v*`
  tags.
- Docker Hub: store `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (an access token
  with read and write access to the repository) as secrets of the `dockerhub`
  environment.
- MCP Registry: nothing to configure. The workflow logs in with GitHub OIDC;
  the registry checks the `mcp-name` comment in this README and the
  `io.modelcontextprotocol.server.name` label of the Docker image.
- Optional: the repository secret `NASDAQ_DATA_LINK_API_KEY` enables the weekly
  live tests (`live.yml`), and `CODECOV_TOKEN` the coverage upload.

## Security

- The API key is read from the environment, `./.env` or `--env-file`, and sent
  only to `NDL_BASE_URL` (by default `https://data.nasdaq.com`): in the
  `X-Api-Token` header for the Tables API and as the Trino user header for
  DataLink SQL, never in a URL. The server does not log it, and removes it
  from every tool result and error message, including reversed, case-changed,
  hex and base64 forms.
- `NDL_BASE_URL` must be a bare `https://` origin and cannot be set from a
  `.env` file, so a file in a cloned repository cannot redirect the key.
- `ndl_sql_query` runs one read-only statement per call and blocks
  `current_user`, `session_user` and the `system` catalog, because Trino
  reports the API key as the session user.
- The HTTP transports require `NDL_HTTP_TOKEN` on any non-loopback address
  and check the `Host` header on loopback.
- The Docker image runs as a non-root user and contains no credentials. The
  `v0.2.1` image published in June 2025 did contain files from the build
  directory; see [CHANGELOG.md](CHANGELOG.md#security) and
  [SECURITY.md](SECURITY.md).
- Tool results contain third-party data. The server's instructions tell the
  model to treat row values, names and upstream messages as data, not as
  instructions.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Citation

If you use this project in research, cite it with [CITATION.cff](CITATION.cff)
(GitHub's "Cite this repository" button reads it), or:

> Amorelli, S. (2025). *Nasdaq Data Link MCP (Model Context Protocol) Server*
> (Version 2.0.0) [Computer software].
> https://github.com/stefanoamorelli/nasdaq-data-link-mcp

## License

[MIT](LICENSE) © 2025 Stefano Amorelli. Nasdaq® is a registered trademark of
Nasdaq, Inc.; this project is not affiliated with Nasdaq, Inc.
