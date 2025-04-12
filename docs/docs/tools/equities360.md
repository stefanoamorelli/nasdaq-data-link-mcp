---
sidebar_position: 3
title: Equities 360 Tools
---

# Equities 360 Tools

Nasdaq Equities 360 provides comprehensive financial data for companies, including statistics, fundamentals, financial statements, corporate actions, and reference data.

## Available Tools

### Company Statistics

#### `get_stock_stats`

Retrieves comprehensive statistics for a company from the Nasdaq Equities 360 database.

```json
{
  "action": "tool",
  "name": "get_stock_stats",
  "params": {
    "symbol": "MSFT"
  }
}
```

#### `list_stock_stat_fields`

Lists all available fields in the stock statistics database with descriptions.

```json
{
  "action": "tool",
  "name": "list_stock_stat_fields"
}
```

### Fundamental Summary

#### `get_fundamental_data`

Retrieves fundamental financial data from the Nasdaq Equities 360 Fundamental Summary database.

```json
{
  "action": "tool",
  "name": "get_fundamental_data",
  "params": {
    "symbol": "MSFT",
    "dimension": "MRY"
  }
}
```

#### `list_fundamental_fields`

Lists all available fields in the fundamental summary database with descriptions.

```json
{
  "action": "tool",
  "name": "list_fundamental_fields"
}
```

### Fundamental Details

#### `get_detailed_financials`

Retrieves detailed financial data from the Nasdaq Equities 360 Fundamental Details database.

```json
{
  "action": "tool",
  "name": "get_detailed_financials",
  "params": {
    "symbol": "MSFT",
    "dimension": "MRQ"
  }
}
```

#### `list_detailed_financial_fields`

Lists all available fields in the fundamental details database with descriptions.

```json
{
  "action": "tool",
  "name": "list_detailed_financial_fields"
}
```

### Balance Sheet

#### `get_balance_sheet_data`

Retrieves balance sheet data from the Nasdaq Equities 360 Balance Sheet database.

```json
{
  "action": "tool",
  "name": "get_balance_sheet_data",
  "params": {
    "symbol": "MSFT",
    "dimension": "MRQ"
  }
}
```

#### `list_balance_sheet_fields`

Lists all available fields in the balance sheet database with descriptions.

```json
{
  "action": "tool",
  "name": "list_balance_sheet_fields"
}
```

### Cash Flow

#### `get_cash_flow_data`

Retrieves cash flow statement data from the Nasdaq Equities 360 Cash Flow database.

```json
{
  "action": "tool",
  "name": "get_cash_flow_data",
  "params": {
    "symbol": "MSFT",
    "dimension": "MRQ"
  }
}
```

#### `list_cash_flow_fields`

Lists all available fields in the cash flow statement database with descriptions.

```json
{
  "action": "tool",
  "name": "list_cash_flow_fields"
}
```

### Corporate Actions

#### `get_corporate_action_data`

Retrieves corporate actions data from the Nasdaq Equities 360 Corporate Actions database.

```json
{
  "action": "tool",
  "name": "get_corporate_action_data",
  "params": {
    "symbol": "TSLA",
    "action": "split"
  }
}
```

#### `list_corporate_action_fields`

Lists all available fields in the corporate actions database with descriptions.

```json
{
  "action": "tool",
  "name": "list_corporate_action_fields"
}
```

### Reference Data

#### `get_company_reference_data`

Retrieves company reference data from the Nasdaq Equities 360 Reference Data database.

```json
{
  "action": "tool",
  "name": "get_company_reference_data",
  "params": {
    "symbol": "AMD"
  }
}
```

#### `list_reference_data_fields`

Lists all available fields in the company reference database with descriptions.

```json
{
  "action": "tool",
  "name": "list_reference_data_fields"
}
```

## Example Conversations

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

## Learn More

- [Equities 360 on Nasdaq Data Link](https://data.nasdaq.com/databases/E360)
- [Return to Tools List](/tools)