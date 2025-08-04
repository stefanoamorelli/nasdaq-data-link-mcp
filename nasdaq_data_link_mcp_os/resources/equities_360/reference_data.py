from typing import Any

import nasdaqdatalink
import pandas as pd


def get_reference_data(
    symbol: str | None = None, figi: str | None = None
) -> pd.DataFrame | str:
    """
    Fetch reference data from Nasdaq Data Link E360 NDAQ/RD table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')

    Returns:
        DataFrame containing reference data or error message
    """
    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        if figi:
            params["figi"] = figi

        # Fetch data from NDAQ/RD table
        data = nasdaqdatalink.get_table("NDAQ/RD", **params)

        if data.empty:
            return "No reference data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching reference data: {e!s}"


def list_available_reference_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/RD table with descriptions.

    Returns:
        List of dictionaries containing field name, description, and type
    """
    fields = [
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
            "name": "exchange",
            "description": (
                "The exchange on which the security trades (e.g., 'NASDAQ', 'NYSE')"
            ),
            "type": "String",
        },
        {
            "name": "category",
            "description": "Security category (e.g., 'Domestic Common Stock')",
            "type": "String",
        },
        {
            "name": "cusips",
            "description": (
                "Security identifier (space delimited for multiple identifiers)"
            ),
            "type": "String",
        },
        {
            "name": "name",
            "description": "Full legal name of the company",
            "type": "String",
        },
        {
            "name": "industry",
            "description": "Industry classification based on SIC codes",
            "type": "String",
        },
        {
            "name": "companysite",
            "description": "URL of the company website",
            "type": "String",
        },
        {
            "name": "sector",
            "description": "Sector classification based on SIC codes",
            "type": "String",
        },
        {
            "name": "sector_1",
            "description": "Primary sector exposure (TIIC level 1)",
            "type": "String",
        },
        {
            "name": "sector_2",
            "description": "Secondary sector exposure (TIIC level 1)",
            "type": "String",
        },
        {
            "name": "secfilings",
            "description": "URL to SEC filings with Central Index Key (CIK)",
            "type": "String",
        },
        {
            "name": "siccode",
            "description": "Standard Industrial Classification code",
            "type": "Integer",
        },
        {
            "name": "location",
            "description": "Company location as registered with the SEC",
            "type": "String",
        },
    ]
    return fields
