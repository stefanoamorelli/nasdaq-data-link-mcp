---
sidebar_position: 2
---

# Installation Guide

Follow these steps to set up the Nasdaq Data Link MCP server on your machine.

## 1. Clone the Repository

```bash
git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
cd nasdaq-data-link-mcp
```

## 2. Install Requirements

You'll need Python 3.13+ and the `mcp` CLI.

```bash
uv init mcp
uv add "mcp[cli]"
```

> **Links:**
> - MCP SDK: [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
> - Nasdaq Data Link SDK: [https://github.com/Nasdaq/data-link-python](https://github.com/Nasdaq/data-link-python)

## 3. Get Your API Key

Sign up on [https://data.nasdaq.com/](https://data.nasdaq.com/) and copy your API key.

<!-- The requirement to download World Bank metadata CSV has been removed as the server now fetches this data directly from Nasdaq Data Link WB/METADATA dataset -->

## 4. Configure the Environment

```bash
cp .env.example .env
```

Then edit `.env` and add your API key:

```
NASDAQ_DATA_LINK_API_KEY=your_api_key_here
```

## 5. Install the MCP Server

```bash
uv run mcp install nasdaq_data_link_mcp_os/server.py --env-file .env --name "Nasdaq Data Link MCP Server" --with nasdaq-data-link --with pycountry
```

This registers the server with your MCP client (e.g., Claude Desktop).

## Development & Debugging

To test the server locally with a UI:

```bash
mcp dev nasdaq_data_link_mcp_os/server.py --env-file .env
```

This opens the `MCP` Dev interface where you can call tools manually, inspect results, and troubleshoot.

## Next Steps

After installation, explore the available tools:
- [Retail Trading Activity Tracker](/tools/rtat)
- [World Bank Tools](/tools/worldbank)
- [Equities 360 Tools](/tools/equities360)
