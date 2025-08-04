from typing import Any

import nasdaqdatalink
import pandas as pd


def get_corporate_actions(
    symbol: str | None = None,
    figi: str | None = None,
    date: str | None = None,
    action: str | None = None,
) -> pd.DataFrame | str:
    """
    Fetch corporate actions data from Nasdaq Data Link E360 NDAQ/CA table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
        date: Date of the corporate action in YYYY-MM-DD format
        action: Type of corporate action (e.g., 'split', 'merger')

    Returns:
        DataFrame containing corporate actions data or error message
    """
    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        if figi:
            params["figi"] = figi
        if date:
            params["date"] = date
        if action:
            params["action"] = action

        # Fetch data from NDAQ/CA table
        data = nasdaqdatalink.get_table("NDAQ/CA", **params)

        if data.empty:
            return "No corporate action data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching corporate actions data: {e!s}"


def list_available_corporate_action_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/CA table with descriptions.

    Returns:
        List of dictionaries containing field name, description, and type
    """
    fields = [
        {
            "name": "date",
            "description": "The date of the corporate action",
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
            "name": "action",
            "description": "Corporate action type (e.g., 'split', 'merger')",
            "type": "String",
            "primary_key": True,
        },
        {
            "name": "value",
            "description": "The total USD value of the action",
            "type": "Double",
        },
        {
            "name": "contrasymbol",
            "description": "The contra symbol of the action, or N/A if not applicable",
            "type": "String",
            "primary_key": True,
        },
        {
            "name": "contraname",
            "description": "The name of the contra company, or N/A if not applicable",
            "type": "String",
            "primary_key": True,
        },
    ]
    return fields
