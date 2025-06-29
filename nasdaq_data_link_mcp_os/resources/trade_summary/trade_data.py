from typing import Any

import nasdaqdatalink


def get_trade_summary(**kwargs: dict[str, Any]):
    """
    Fetch Trade Summary data with optional filtering parameters.

    This function accesses the NDAQ/TS datatable which contains consolidated
    trade data including open, high, low, close, and volume for various symbols.

    Args:
        **kwargs: Optional filtering parameters to pass to the API:
            - symbol: Filter by symbol
            - timestamp: Filter by timestamp
            - qopts.columns: Specify which columns to return

    Returns:
        DataFrame with Trade Summary data or error message
    """
    try:
        # All parameters are passed directly to the API
        df = nasdaqdatalink.get_table("NDAQ/TS", **kwargs)

        if df.empty:
            return "No Trade Summary data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching Trade Summary data: {e!s}"
