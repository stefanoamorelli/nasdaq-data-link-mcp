from typing import Any

import nasdaqdatalink
import pandas as pd


def get_fundamental_summary(
    symbol: str | None = None,
    figi: str | None = None,
    calendardate: str | None = None,
    dimension: str | None = None,
) -> pd.DataFrame | str:
    """
    Fetch fundamental summary data from Nasdaq Data Link E360 NDAQ/FS table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
        calendardate: Calendar date in YYYY-MM-DD format
        dimension: MRQ (Quarterly), MRY (Annual), or MRT (Trailing-twelve-months)

    Returns:
        DataFrame containing fundamental data or error message
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

        # Fetch data from NDAQ/FS table
        data = nasdaqdatalink.get_table("NDAQ/FS", **params)

        if data.empty:
            return "No data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching fundamental summary: {e!s}"


def list_available_fundamental_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/FS table with descriptions.

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
                "Dimensional view of data (MRQ: Quarterly, MRY: annual, "
                "MRT: trailing-twelve-months)"
            ),
            "type": "String",
            "filterable": True,
            "primary_key": True,
        },
        {"name": "fcfps", "description": "Free Cash Flow per Share", "type": "Double"},
        {
            "name": "ps",
            "description": "Price to Sales ratio between marketcap and revenue",
            "type": "Double",
        },
        {
            "name": "pe",
            "description": "Price to Earnings ratio between marketcap and netinccmn",
            "type": "Double",
        },
        {
            "name": "revenue",
            "description": (
                "Amount of Revenue recognized from goods sold, services rendered, etc."
            ),
            "type": "BigInt",
        },
        {
            "name": "currentratio",
            "description": "The ratio between assetsc and liabilitiesc",
            "type": "Double",
        },
        {
            "name": "de",
            "description": "Debt to Equity ratio between liabilities and equity",
            "type": "Double",
        },
        {
            "name": "roa",
            "description": "Return on Assets (netinccmn relative to total assets)",
            "type": "Double",
        },
        {
            "name": "roe",
            "description": ("Return on Equity (netinccmn as percentage of equityavg)"),
            "type": "Double",
        },
        {
            "name": "ros",
            "description": "Return on Sales (ebit divided by revenue)",
            "type": "Double",
        },
        {
            "name": "gp",
            "description": "Gross Profit (revenue less cost of revenue)",
            "type": "BigInt",
        },
        {
            "name": "opinc",
            "description": (
                "Operating income (before deduction of intexp, taxexp, etc.)"
            ),
            "type": "BigInt",
        },
        {
            "name": "netmargin",
            "description": "Net Margin (ratio between netinccmn and revenue)",
            "type": "Double",
        },
        {
            "name": "ebitda",
            "description": (
                "Earnings Before Interest, Taxes, Depreciation and Amortization"
            ),
            "type": "BigInt",
        },
        {
            "name": "bvps",
            "description": ("Book Value Per Share (ratio between equity and shareswa)"),
            "type": "Double",
        },
        {
            "name": "evebit",
            "description": "Enterprise Value to EBIT ratio",
            "type": "BigInt",
        },
        {
            "name": "evebitda",
            "description": "Enterprise Value to EBITDA ratio",
            "type": "Double",
        },
        {
            "name": "tbvps",
            "description": "Tangible Book Value Per Share",
            "type": "Double",
        },
    ]
    return fields
