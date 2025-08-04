from typing import Any

import nasdaqdatalink
import pandas as pd


def get_cash_flow(
    symbol: str | None = None,
    figi: str | None = None,
    calendardate: str | None = None,
    dimension: str | None = None,
) -> pd.DataFrame | str:
    """
    Fetch cash flow statement data from Nasdaq Data Link E360 NDAQ/CF table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
        calendardate: Calendar date in YYYY-MM-DD format
        dimension: MRQ (Quarterly), MRY (Annual), or MRT (Trailing-twelve-months)

    Returns:
        DataFrame containing cash flow statement data or error message
    """
    if not symbol and not figi:
        return "Error: Either symbol or figi must be provided."

    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        if figi:
            params["figi"] = figi
        if calendardate:
            params["calendardate"] = calendardate
        if dimension:
            params["dimension"] = dimension

        # Fetch data from NDAQ/CF table
        data = nasdaqdatalink.get_table("NDAQ/CF", **params)

        if data.empty:
            return "No data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching cash flow statement data: {e!s}"


def list_available_cash_flow_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/CF table with descriptions.

    Returns:
        List of dictionaries containing field name, description, and type
    """
    fields = [
        {
            "name": "calendardate",
            "description": "The Calendar Date represents the normalized reportperiod",
            "type": "Date",
            "filterable": True,
            "primary_key": True,
        },
        {
            "name": "symbol",
            "description": "Symbol of the company",
            "type": "String",
            "filterable": True,
            "primary_key": True,
        },
        {
            "name": "figi",
            "description": "Unique Identifier given by Bloomberg",
            "type": "String",
            "filterable": True,
        },
        {
            "name": "reportperiod",
            "description": (
                "The Report Period represents the end date of the fiscal period"
            ),
            "type": "Date",
            "primary_key": True,
        },
        {
            "name": "dimension",
            "description": (
                "Dimensional view of data (MRQ: Quarterly, "
                "MRY: annual, MRT: trailing-twelve-months)"
            ),
            "type": "String",
            "filterable": True,
            "primary_key": True,
        },
        {
            "name": "opex",
            "description": "Operating expenses (excluding cost of revenue)",
            "type": "BigInt",
        },
        {
            "name": "ncfi",
            "description": "Net cash flow from investing activities",
            "type": "BigInt",
        },
        {
            "name": "ncff",
            "description": "Net cash flow from financing activities",
            "type": "BigInt",
        },
        {
            "name": "fcf",
            "description": "Free Cash Flow (ncfo minus capex)",
            "type": "BigInt",
        },
        {
            "name": "ncfo",
            "description": "Net cash flow from operating activities",
            "type": "BigInt",
        },
        {
            "name": "capex",
            "description": "Capital expenditure (acquisition of long-lived assets)",
            "type": "BigInt",
        },
        {
            "name": "ncfbus",
            "description": "Net cash flow from business acquisitions/disposals",
            "type": "BigInt",
        },
        {"name": "sbcomp", "description": "Stock-based compensation", "type": "BigInt"},
        {
            "name": "depamor",
            "description": "Depreciation, amortization, and accretion",
            "type": "BigInt",
        },
        {
            "name": "ncfcommon",
            "description": "Net cash flow from common equity changes",
            "type": "BigInt",
        },
        {
            "name": "ncfinv",
            "description": "Net cash flow from investments",
            "type": "BigInt",
        },
        {
            "name": "debttoassets",
            "description": "Net cash flow from debt issuance/repayment",
            "type": "BigInt",
        },
    ]
    return fields
