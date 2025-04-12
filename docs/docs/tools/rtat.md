---
sidebar_position: 1
title: Retail Trading Activity Tracker
---

# Retail Trading Activity Tracker

The Retail Trading Activity Tracker (RTAT) database provides information about retail trading patterns and behavior. This data is useful for understanding retail investor sentiment and activity in the market.

## Available Tools

### `get_rtat10`

Retrieves Retail Trading Activity Tracker 10 (RTAT10) data for specific dates and optional tickers.

```json
{
  "action": "tool",
  "name": "get_rtat10",
  "params": {
    "dates": "2025-03-31,2025-03-28,2025-03-27",
    "tickers": "TSLA,TQQQ,SQQQ"
  }
}
```

Returns RTAT10 data from Nasdaq Data Link for the given dates and tickers.

### `get_rtat`

Retrieves Retail Trading Activity (RTAT) data for specific dates and optional tickers.

```json
{
  "action": "tool",
  "name": "get_rtat",
  "params": {
    "dates": "2025-03-31,2025-03-28,2025-03-27",
    "tickers": "TSLA,TQQQ,SQQQ"
  }
}
```

Returns RTAT data from Nasdaq Data Link for the given dates and tickers.

## Example Conversations

> **You:** What were the most traded stocks by retailers yesterday?  
> **Claude:** *calls `get_rtat(<yetserday>)` and returns relevant matches*

## Learn More

- [Nasdaq RTAT Database](https://data.nasdaq.com/databases/RTAT)
- [Return to Tools List](/tools)