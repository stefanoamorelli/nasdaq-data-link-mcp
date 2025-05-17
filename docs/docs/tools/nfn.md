---
sidebar_position: 5
title: Nasdaq Fund Network
---

# Nasdaq Fund Network (NFN)

The Nasdaq Fund Network (NFN) provides data about mutual funds, money market funds, unit investment trusts, and other investment funds. These tools give access to comprehensive information about NFN funds, including fund details, share classes, performance metrics, price history, and more.

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

Returns basic fund data from Nasdaq Fund Network for the given fund ID.

### `get_fund_information`

Retrieves Fund Information Report (NFN/MFRFI) data with detailed information about funds.

```json
{
  "action": "tool",
  "name": "get_fund_information",
  "params": {
    "fund_id": "12345"
  }
}
```

### `get_share_class_master`

Retrieves Fund Share Class Master (NFN/MFRSM) data with basic information about fund share classes.

```json
{
  "action": "tool",
  "name": "get_share_class_master",
  "params": {
    "fund_id": "12345"
  }
}
```

### `get_share_class_information`

Retrieves Fund Share Class Information (NFN/MFRSI) data with detailed share class attributes.

```json
{
  "action": "tool",
  "name": "get_share_class_information",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_price_history`

Retrieves Fund Price History (NFN/MFRPH) data with historical NAV and pricing.

```json
{
  "action": "tool",
  "name": "get_price_history",
  "params": {
    "ticker": "ABCDX",
    "start_date": "2024-01-01",
    "end_date": "2024-04-30"
  }
}
```

### `get_recent_price_history`

Retrieves recent Fund Price History (NFN/MFRPH10) data for the last 10 trading days.

```json
{
  "action": "tool",
  "name": "get_recent_price_history",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_performance_statistics`

Retrieves Fund Performance Statistics (NFN/MFRPS) data with performance returns.

```json
{
  "action": "tool",
  "name": "get_performance_statistics",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_performance_benchmark`

Retrieves Fund Performance Benchmark (NFN/MFRPRB) data about benchmark indexes.

```json
{
  "action": "tool",
  "name": "get_performance_benchmark",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_performance_analytics`

Retrieves Fund Performance Analytics (NFN/MFRPA) data with metrics like alpha, beta, etc.

```json
{
  "action": "tool",
  "name": "get_performance_analytics",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_fees_and_expenses`

Retrieves Fund Fee and Expense Data (NFN/MFRPM) about fees, expenses, and sales charges.

```json
{
  "action": "tool",
  "name": "get_fees_and_expenses",
  "params": {
    "ticker": "ABCDX"
  }
}
```

### `get_monthly_flows`

Retrieves Fund Monthly Flows (NFN/MFRMF) data showing historical fund flows.

```json
{
  "action": "tool",
  "name": "get_monthly_flows",
  "params": {
    "ticker": "ABCDX"
  }
}
```

## Data Structures

### Fund Master Report (MFRFM)

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

### Fund Information Report (MFRFI)

| Column                 | Type   | Description                                                             |
|------------------------|--------|-------------------------------------------------------------------------|
| fund_id                | string | Unique fund identifier                                                  |
| name                   | string | Fund name                                                               |
| investment_strategy    | string | Description of the fund's investment strategy                           |
| investment_objective   | string | Primary investment objective                                            |
| category               | string | Fund category classification                                            |
| asset_class            | string | Primary asset class                                                     |
| investment_focus       | string | Geographic or sector investment focus                                   |
| management_style       | string | Active or passive management style                                      |

### Share Class Information (MFRSI)

| Column                 | Type   | Description                                                             |
|------------------------|--------|-------------------------------------------------------------------------|
| fund_id                | string | Unique fund identifier                                                  |
| ticker                 | string | Share class ticker symbol                                               |
| cusip                  | string | CUSIP identifier                                                        |
| share_class_name       | string | Name of the share class                                                 |
| share_class_type       | string | Type of share class (e.g., A, B, C, I, etc.)                           |
| min_initial_investment | number | Minimum initial investment amount                                       |
| distribution_type      | string | Income distribution type (e.g., Income, Accumulation)                   |

### Price History (MFRPH/MFRPH10)

| Column                 | Type   | Description                                                             |
|------------------------|--------|-------------------------------------------------------------------------|
| fund_id                | string | Unique fund identifier                                                  |
| ticker                 | string | Share class ticker symbol                                               |
| date                   | date   | Price date                                                              |
| nav                    | number | Net Asset Value                                                         |
| offer_price            | number | Offering price (NAV + sales charge)                                     |
| redemption_price       | number | Redemption price                                                        |

### Performance Statistics (MFRPS)

| Column                 | Type   | Description                                                             |
|------------------------|--------|-------------------------------------------------------------------------|
| fund_id                | string | Unique fund identifier                                                  |
| ticker                 | string | Share class ticker symbol                                               |
| period_date            | date   | Date of performance reporting                                           |
| return_1mo             | number | 1-month return percentage                                               |
| return_3mo             | number | 3-month return percentage                                               |
| return_1yr             | number | 1-year return percentage                                                |
| return_3yr             | number | 3-year annualized return percentage                                     |
| return_5yr             | number | 5-year annualized return percentage                                     |
| return_10yr            | number | 10-year annualized return percentage                                    |
| return_ytd             | number | Year-to-date return percentage                                          |

## Example Conversations

> **You:** Can you show me information about some open-ended mutual funds?  
> **Claude:** *calls `get_fund_master_report(investment_company_type="N-1A")` and returns the fund information*

> **You:** I need details about fund ID 12345  
> **Claude:** *calls `get_fund_information(fund_id="12345")` and returns the detailed fund information*

> **You:** Can you show me the performance of fund ABCDX over the past year?  
> **Claude:** *calls `get_performance_statistics(ticker="ABCDX")` and displays the performance results*

> **You:** What fees are associated with the Growth Fund?  
> **Claude:** *first calls `get_fund_master_report(name="Growth Fund")` to find the fund ID, then calls `get_fees_and_expenses(fund_id="[found_id]")` to show the fee structure*

> **You:** Show me the NAV history for ABCDX for the first quarter of 2024  
> **Claude:** *calls `get_price_history(ticker="ABCDX", start_date="2024-01-01", end_date="2024-03-31")` and displays the price history*

> **You:** How does fund ABCDX compare to its benchmark?  
> **Claude:** *first calls `get_performance_benchmark(ticker="ABCDX")` to identify the benchmark, then calls `get_performance_statistics(ticker="ABCDX")` to compare performance*

> **You:** What are the recent fund flows for ABCDX?  
> **Claude:** *calls `get_monthly_flows(ticker="ABCDX")` and displays the monthly flow data*

## Learn More

- [Nasdaq Fund Network](https://www.nasdaq.com/solutions/nasdaq-fund-network)
- [Fund Information Report (NFN-MFRFI)](https://data.nasdaq.com/databases/MFR#anchor-fund-information-report-nfn-mfrfi-)
- [Return to Tools List](/tools)