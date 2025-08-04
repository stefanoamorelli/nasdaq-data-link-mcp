from typing import Any

import nasdaqdatalink
import pandas as pd


def get_balance_sheet(
    symbol: str | None = None,
    figi: str | None = None,
    calendardate: str | None = None,
    dimension: str | None = None,
) -> pd.DataFrame | str:
    """
    Fetch balance sheet data from Nasdaq Data Link E360 NDAQ/BS table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
        calendardate: Calendar date in YYYY-MM-DD format
        dimension: MRQ (Quarterly), MRY (Annual), or MRT (Trailing-twelve-months)

    Returns:
        DataFrame containing balance sheet data or error message
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

        # Fetch data from NDAQ/BS table
        data = nasdaqdatalink.get_table("NDAQ/BS", **params)

        if data.empty:
            return "No data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching balance sheet data: {e!s}"


def list_available_balance_sheet_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/BS table with descriptions.

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
            "name": "assets",
            "description": "Total assets recognized on the balance sheet",
            "type": "BigInt",
        },
        {
            "name": "bvps",
            "description": "Book Value Per Share (ratio between equity and shareswa)",
            "type": "Double",
        },
        {
            "name": "cashneq",
            "description": "Cash and equivalents on hand",
            "type": "BigInt",
        },
        {
            "name": "debt",
            "description": "Total current and non-current debt",
            "type": "BigInt",
        },
        {
            "name": "liabilities",
            "description": "Total liabilities recognized on the balance sheet",
            "type": "BigInt",
        },
        {
            "name": "equity",
            "description": "Total stockholders' equity",
            "type": "BigInt",
        },
        {
            "name": "accoci",
            "description": "Accumulated other comprehensive income",
            "type": "BigInt",
        },
        {
            "name": "currency",
            "description": "The company functional reporting currency",
            "type": "String",
        },
        {
            "name": "investmentsnc",
            "description": "Non-current portion of investments",
            "type": "BigInt",
        },
        {
            "name": "investmentsc",
            "description": "Current portion of investments",
            "type": "BigInt",
        },
        {
            "name": "receivables",
            "description": "Trade and non-trade receivables",
            "type": "BigInt",
        },
        {
            "name": "inventory",
            "description": "Inventory expected to be sold within one year",
            "type": "BigInt",
        },
        {"name": "assetsnc", "description": "Non-current assets", "type": "BigInt"},
        {"name": "assetsc", "description": "Current assets", "type": "BigInt"},
        {
            "name": "investments",
            "description": (
                "Total marketable and non-marketable securities and other "
                "invested assets"
            ),
            "type": "BigInt",
        },
        {
            "name": "ppnenet",
            "description": "Property, plant, and equipment (net of depreciation)",
            "type": "BigInt",
        },
        {
            "name": "intangibles",
            "description": "Intangible assets and goodwill",
            "type": "BigInt",
        },
        {
            "name": "tangibles",
            "description": "Tangible assets (assets minus intangibles)",
            "type": "BigInt",
        },
        {
            "name": "payables",
            "description": "Trade and non-trade payables",
            "type": "BigInt",
        },
        {
            "name": "liabilitiesnc",
            "description": "Non-current liabilities",
            "type": "BigInt",
        },
        {
            "name": "liabilitiesc",
            "description": "Current liabilities",
            "type": "BigInt",
        },
        {"name": "debtc", "description": "Current portion of debt", "type": "BigInt"},
        {
            "name": "debtnc",
            "description": "Non-current portion of debt",
            "type": "BigInt",
        },
        {
            "name": "deferredrev",
            "description": (
                "Deferred revenue (unrecognized revenue from received payments)"
            ),
            "type": "BigInt",
        },
        {
            "name": "retearn",
            "description": (
                "Retained earnings (cumulative undistributed earnings/deficit)"
            ),
            "type": "BigInt",
        },
        {
            "name": "taxassets",
            "description": "Tax assets and receivables",
            "type": "BigInt",
        },
        {
            "name": "taxliabilities",
            "description": "Outstanding tax liabilities",
            "type": "BigInt",
        },
        {
            "name": "cashnequsd",
            "description": "Cash and equivalents in USD",
            "type": "BigInt",
        },
    ]
    return fields
