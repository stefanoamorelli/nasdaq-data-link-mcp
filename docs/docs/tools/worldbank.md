---
sidebar_position: 2
title: World Bank Tools
---

# World Bank Tools

The World Bank database provides access to a vast collection of economic and development indicators for countries around the world. This data is useful for understanding global economic trends, development metrics, and comparative country analysis.

## Available Tools

### `get_indicator_value`

Fetch the value for a specific indicator and country.

```json
{
  "action": "tool",
  "name": "get_indicator_value",
  "params": {
    "country": "Italy",
    "indicator": "NY.GDP.MKTP.CD"
  }
}
```

Returns the latest value for that indicator.

### `country_code`

Returns the ISO 3-letter country code (e.g., `"ITA"` for Italy).

```json
{
  "action": "tool",
  "name": "country_code",
  "params": {
    "countryName": "Italy"
  }
}
```

### `list_worldbank_indicators`

Returns a list of all 1500+ indicators available.

```json
{
  "action": "tool",
  "name": "list_worldbank_indicators"
}
```

### `search_worldbank_indicators`

Searches for indicators by keyword.

```json
{
  "action": "tool",
  "name": "search_worldbank_indicators",
  "params": {
    "keyword": "population"
  }
}
```

## Example Conversations

> **You:** What was the GDP of Italy in 2022?  
> **Claude:** Let me look that up... *calls `get_indicator_value` tool*  
> **Claude:** The GDP of Italy in 2022 was approximately `...` trillion USD.

> **You:** List all indicators related to CO₂ emissions.  
> **Claude:** *calls `search_worldbank_indicators("CO2")` and returns relevant matches*

## Learn More

- [World Bank dataset on Nasdaq Data Link](https://data.nasdaq.com/databases/WB)
- [Return to Tools List](/tools)