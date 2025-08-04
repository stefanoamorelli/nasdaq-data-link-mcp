import nasdaqdatalink


def get_rtat10_data(dates: str, tickers: str | None = None):
    """
    Fetch Retail Trading Activity Tracker 10 (RTAT10) data for specific dates
    and tickers.

    Args:
        dates: Comma-separated list of dates in format 'YYYY-MM-DD'
        tickers: Optional comma-separated list of ticker symbols

    Returns:
        DataFrame with RTAT10 data or error message
    """
    try:
        params = {"date": dates}
        if tickers:
            params["ticker"] = tickers

        df = nasdaqdatalink.get_table("NDAQ/RTAT10", **params)

        if df.empty:
            return "No RTAT10 data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching RTAT10 data: {e!s}"


def get_rtat_data(dates: str, tickers: str | None = None):
    """
    Fetch Retail Trading Activity (RTAT) data for specific dates and tickers.

    Args:
        dates: Comma-separated list of dates in format 'YYYY-MM-DD'
        tickers: Optional comma-separated list of ticker symbols

    Returns:
        DataFrame with RTAT data or error message
    """
    try:
        params = {"date": dates}
        if tickers:
            params["ticker"] = tickers

        df = nasdaqdatalink.get_table("NDAQ/RTAT", **params)

        if df.empty:
            return "No RTAT data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching RTAT data: {e!s}"
