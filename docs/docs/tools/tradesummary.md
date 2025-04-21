---
title: Trade Summary
sidebar_position: 4
---

# Trade Summary

The Trade Summary tool provides access to Nasdaq Data Link's NDAQ/TS datatable, which includes consolidated trade data such as open, high, low, close, and volume information.

## Available Functions

### `get_trade_summary_data`

Fetch trade summary data from the NDAQ/TS datatable.

```python
def get_trade_summary_data(**kwargs)
```

**Parameters:**
- No required parameters. Any parameters supported by the Nasdaq Data Link API can be passed.

**Returns:**
- DataFrame with Trade Summary data or error message

**Example:**
```python
# Fetch trade summary data
get_trade_summary_data()
```

## Data Structure

The Trade Summary datatable (NDAQ/TS) contains the following columns:

| Column    | Type     | Description                                                 |
|-----------|----------|-------------------------------------------------------------|
| symbol    | Text     | Symbol                                                      |
| open      | Double   | The consolidated open price for the symbol in the given time|
| high      | Double   | The consolidated highest price for the symbol in the given time|
| low       | Double   | The consolidated lowest price for the symbol in the given time|
| close     | Double   | The consolidated close price for the symbol in the given time|
| volume    | Double   | The consolidated trading volume for the symbol in the given time|
| timestamp | Datetime | Trade timestamp, format: YYYY-MM-DDThh:mm:ss.s              |

## API Details

This tool interfaces with the [Nasdaq Data Link Trade Summary database](https://data.nasdaq.com/databases/TRDSUM) and specifically the [NDAQ/TS datatable](https://data.nasdaq.com/api/v3/datatables/NDAQ/TS).