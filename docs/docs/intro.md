---
sidebar_position: 1
---

# 📈 Nasdaq Data Link MCP 🤖

A community developed and maintained [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) server that provides access to [Nasdaq Data Link](https://data.nasdaq.com/). Built for use with MCP-compatible [clients](https://modelcontextprotocol.io/clients).

This project aims at making easy to access and explore Nasdaq Data Link's extensive and valuable financial and economic datasets through natural language interfaces and large language models (LLMs).

🐍 This project uses the official [nasdaq/data-link-python SDK](https://github.com/Nasdaq/data-link-python)

> **Disclaimer:** This is an open-source project *not affiliated with or endorsed by Nasdaq, Inc.* Nasdaq® is a registered trademark of Nasdaq, Inc.

## 🌐 Usage

Once installed and connected to an `MCP`-compatible client (e.g., [Claude Desktop](https://claude.ai/download), this server exposes several tools that your AI assistant can use to fetch data.

In this version (`0.1.1`) the project supports the following databases:
- [World Bank dataset on Nasdaq Data Link](https://data.nasdaq.com/databases/WB) (freely available for personal use)
- [Nasdaq RTAT](https://data.nasdaq.com/databases/RTAT) (preview available for free, full data under subscription)
- [Equities 360](https://data.nasdaq.com/databases/E360) (company statistics and fundamental data)

## Example conversations

> **You:** What were the most traded stocks by retailers yesterday?  
> **Claude:** *calls `get_rtat(<yetserday>)` and returns relevant matches*

> **You:** What was the GDP of Italy in 2022?  
> **Claude:** Let me look that up... *calls `get_indicator_value` tool*  
> **Claude:** The GDP of Italy in 2022 was approximately `...` trillion USD.

> **You:** List all indicators related to CO₂ emissions.  
> **Claude:** *calls `search_worldbank_indicators("CO2")` and returns relevant matches*

> **You:** What's the market cap and P/E ratio of Microsoft?  
> **Claude:** *calls `get_stock_stats(symbol="MSFT")` and presents the key statistics*

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