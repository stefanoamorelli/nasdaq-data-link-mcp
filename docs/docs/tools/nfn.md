---
sidebar_position: 5
title: Nasdaq Fund Network
---

# Nasdaq Fund Network (NFN)

The Nasdaq Fund Network (NFN) provides data about mutual funds, money market funds, unit investment trusts, and other investment funds. This tool gives access to the Fund Master Report (MFRFM), which contains basic information about live NFN funds, mutual funds, and closed-end funds.

## Available Tools

### `get_fund_master_report`

Retrieves Fund Master Report (NFN/MFRFM) data from Nasdaq Fund Network.

```json
{
  "action": "tool",
  "name": "get_fund_master_report",
  "params": {
    "fund_id": "12345"
  }
}
```

Returns fund data from Nasdaq Fund Network for the given fund ID.

You can also filter by other parameters:

```json
{
  "action": "tool",
  "name": "get_fund_master_report",
  "params": {
    "investment_company_type": "N-1A"
  }
}
```

## Data Structure

The Fund Master Report contains the following key columns:

| Column                 | Type   | Description                                                             |
|------------------------|--------|-------------------------------------------------------------------------|
| fund_id                | string | Unique fund identifier assigned by Cannon Valley Research               |
| name                   | string | Current/latest fund name                                                |
| investment_company_type| string | Investment company type: N-1A (Open-Ended mutual funds) or N-2 (Closed-End funds) |
| formation_date         | date   | Fund formation date (legal)                                             |
| termination_date       | date   | Fund termination date (legal)                                           |
| termination_comment    | string | Reason for fund termination (i.e. liquidation/merger)                   |
| lei                    | string | Legal Entity Identifier                                                 |
| edgar_series_id        | string | EDGAR series ID (Mutual Funds only)                                     |
| nasdaq_root_symbol     | string | Root symbol assigned to the fund by NASDAQ                              |
| cik                    | string | Central Index Key assigned by SEC                                       |

## Example Conversations

> **You:** Can you show me information about some open-ended mutual funds?  
> **Claude:** *calls `get_fund_master_report(investment_company_type="N-1A")` and returns the fund information*

> **You:** I need details about fund ID 12345  
> **Claude:** *calls `get_fund_master_report(fund_id="12345")` and returns the specific fund details*

> **You:** Find mutual funds formed in 2020  
> **Claude:** *calls `get_fund_master_report(formation_date="2020-01-01", formation_date.lte="2020-12-31")` and displays the results*

## Learn More

- [Nasdaq Fund Network](https://www.nasdaq.com/solutions/nasdaq-fund-network)
- [Return to Tools List](/tools)