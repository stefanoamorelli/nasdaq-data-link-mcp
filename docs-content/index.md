---
layout: default
title: Nasdaq Data Link MCP
permalink: /
---

# 📈 Nasdaq Data Link MCP 🤖

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/stefanoamorelli/nasdaq-data-link-mcp/blob/main/LICENSE)
[![PyPI version](https://img.shields.io/badge/PyPI-v0.1.1-blue.svg)](https://pypi.org/project/nasdaq-data-link-mcp-os/)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Build Status](https://img.shields.io/badge/build-passing-green.svg)
![Platform](https://img.shields.io/badge/platform-cross--platform-lightgrey.svg)
![](https://badge.mcpx.dev?type=server 'MCP Server')
![AI Powered](https://img.shields.io/badge/AI-powered-6f42c1?logo=anthropic&logoColor=white)

A community developed and maintained [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) server that provides access to [Nasdaq Data Link](https://data.nasdaq.com/). Built for use with MCP-compatible [clients](https://modelcontextprotocol.io/clients).

This project aims at making easy to access and explore Nasdaq Data Link's extensive and valuable financial and economic datasets through natural language interfaces and large language models (LLMs).

🐍 This project uses the official [nasdaq/data-link-python SDK](https://github.com/Nasdaq/data-link-python)

> **Disclaimer:** This is an open-source project *not affiliated with or endorsed by Nasdaq, Inc.* Nasdaq® is a registered trademark of Nasdaq, Inc.

## 🌐 Usage

| [![Retail Trading Activity](https://cdn.loom.com/sessions/thumbnails/b0299f6f6f1844669b5d2f73a86a3dcb-63f0e754bafcbe42-full-play.gif)](https://www.loom.com/share/b0299f6f6f1844669b5d2f73a86a3dcb) | [![World Bank Data](https://cdn.loom.com/sessions/thumbnails/a07e518bb6eb4de4b5a06a5a1a112a24-ff58182656db7dca-full-play.gif)](https://www.loom.com/share/a07e518bb6eb4de4b5a06a5a1a112a24) |
|:--:|:--:|
| [Nasdaq Data Link MCP - Retail Trading Activity](https://www.loom.com/share/b0299f6f6f1844669b5d2f73a86a3dcb) | [Nasdaq Data Link MCP - World Bank Data](https://www.loom.com/share/a07e518bb6eb4de4b5a06a5a1a112a24) |

Once installed and connected to an `MCP`-compatible client (e.g., [Claude Desktop](https://claude.ai/download), this server exposes several tools that your AI assistant can use to fetch data.

In this version (`0.1.1`) the project supports the following databases:
- [World Bank dataset on Nasdaq Data Link](https://data.nasdaq.com/databases/WB) (freely available for personal use)
- [Nasdaq RTAT](https://data.nasdaq.com/databases/RTAT) (preview available for free, full data under subscription)
- [Equities 360](https://data.nasdaq.com/databases/E360) (company statistics and fundamental data)

<details>
<summary><strong>Example conversations</strong></summary>

> **You:** What were the most traded stocks by retailers yesterday?  
> **Claude:** *calls `get_rtat(<yetserday>)` and returns relevant matches*

> **You:** What was the GDP of Italy in 2022?  
> **Claude:** Let me look that up... *calls `get_indicator_value` tool*  
> **Claude:** The GDP of Italy in 2022 was approximately `...` trillion USD.

> **You:** List all indicators related to CO₂ emissions.  
> **Claude:** *calls `search_worldbank_indicators("CO2")` and returns relevant matches*

> **You:** What's the market cap and P/E ratio of Microsoft?  
> **Claude:** *calls `get_stock_stats(symbol="MSFT")` and presents the key statistics*

> **You:** Show me Microsoft's profitability ratios for the most recent annual report.  
> **Claude:** *calls `get_fundamental_data(symbol="MSFT", dimension="MRY")` and presents profitability metrics*

> **You:** What's Microsoft's cash flow and R&D spending for the last quarter?  
> **Claude:** *calls `get_detailed_financials(symbol="MSFT", dimension="MRQ")` and presents cash flow and R&D data*

> **You:** What's Microsoft's asset breakdown and debt-to-equity ratio from the latest balance sheet?  
> **Claude:** *calls `get_balance_sheet_data(symbol="MSFT", dimension="MRQ")` and presents relevant balance sheet items*

> **You:** How has Microsoft's free cash flow and capital expenditure changed over the past year?  
> **Claude:** *calls `get_cash_flow_data(symbol="MSFT", dimension="MRY")` and analyzes free cash flow trends*

> **You:** Has Tesla had any stock splits in the last two years?  
> **Claude:** *calls `get_corporate_action_data(symbol="TSLA", action="split")` and presents the split history*

> **You:** What industry and sector is AMD in, and where is the company located?  
> **Claude:** *calls `get_company_reference_data(symbol="AMD")` and presents industry, sector, and location information*
</details>

## 📦 Installation

For detailed installation instructions, visit the [Installation Guide](installation.html).

## 🛠️ Tools

After installation, the following tools are exposed to MCP clients:

- [Retail Trading Activity Tracker](tools/rtat.html)
- [World Bank Tools](tools/worldbank.html)
- [Equities 360 Tools](tools/equities360.html)

## 📊 Architecture

```mermaid
graph TD
  subgraph "Local Machine"
    A[MCP Server: Nasdaq Data Link MCP] --> C[MCP Client, ie. Claude Desktop]
  end

  C -->|user prompt| D[LLM ie. Claude 3.7 Sonnet]
  D -->|calls tool| A
  A -->|fetches data| B[Nasdaq Data Link API]
  B -.-> E[Retail Trading Activity Tracker]
  B -.-> F[World Bank Metadata]
  
  subgraph "Equities 360"
    G[Statistics NDAQ/STAT]
    H[Fundamentals NDAQ/FS]
    I[Fundamental Details NDAQ/FD]
    J[Balance Sheet NDAQ/BS]
    K[Cash Flow NDAQ/CF]
    L[Corporate Actions NDAQ/CA]
    M[Reference Data NDAQ/RD]
  end
  
  B -.-> Equities 360
```

## 📚 References

- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Nasdaq Data Link Python SDK](https://github.com/Nasdaq/data-link-python)
- [GitHub Repository](https://github.com/stefanoamorelli/nasdaq-data-link-mcp)

## 📄 License

[MIT License](https://github.com/stefanoamorelli/nasdaq-data-link-mcp/blob/main/LICENSE) © 2025 [Stefano Amorelli](https://github.com/stefanoamorelli)