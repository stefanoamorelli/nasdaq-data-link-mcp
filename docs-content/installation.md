---
layout: default
title: Installation Guide
---

# Installation Guide

Follow these steps to set up the Nasdaq Data Link MCP server on your machine.

## 1. Clone the Repository

```bash
git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
cd nasdaq-data-link-mcp
```

## 2. Install Requirements

You'll need Python 3.10+ and the `mcp` CLI.

```bash
pip install mcp nasdaq-data-link pycountry
```

> **Links:**
> - MCP SDK: [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
> - Nasdaq Data Link SDK: [https://github.com/Nasdaq/data-link-python](https://github.com/Nasdaq/data-link-python)

## 3. Get Your API Key

Sign up on [https://data.nasdaq.com/](https://data.nasdaq.com/) and copy your API key.

## 4. Download World Bank metadata CSV (Optional)

<details>
<summary>Click here if you plan to use the World Bank database</summary>

Download the `World Bank metadata` from [Nasdaq Data Link](https://data.nasdaq.com/databases/WB):

![Nasdaq Data Link World Bank metadata export](https://github.com/user-attachments/assets/411f4f9b-6f19-4b13-bde8-688b39458e18)

And save it as `metadata.csv` in the following directory:

```
nasdaq-data-link-mcp/nasdaq_data_link_mcp_os/resources/world_data_bank/metadata/metadata.csv
```
</details>

## 5. Configure the Environment

```bash
cp .env.example .env
```

Then edit `.env` and add your API key:

```
NASDAQ_DATA_LINK_API_KEY=your_api_key_here
```

## 6. Install the MCP Server

```bash
mcp install nasdaq_data_link_mcp_os/server.py --env-file .env --name "Nasdaq Data Link MCP Server"
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
- [Retail Trading Activity Tracker](tools/rtat.html)
- [World Bank Tools](tools/worldbank.html)
- [Equities 360 Tools](tools/equities360.html)

Or [return to the homepage](index.html).