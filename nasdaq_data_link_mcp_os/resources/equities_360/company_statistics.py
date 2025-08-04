import nasdaqdatalink
import pandas as pd


def get_company_stats(
    symbol: str | None = None, figi: str | None = None
) -> pd.DataFrame | str:
    """
    Fetch company statistics from Nasdaq Data Link E360 NDAQ/STAT table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')

    Returns:
        DataFrame containing company statistics or error message
    """
    if not symbol and not figi:
        return "Error: Either symbol or figi must be provided."

    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        if figi:
            params["figi"] = figi

        # Fetch data from NDAQ/STAT table
        data = nasdaqdatalink.get_table("NDAQ/STAT", **params)

        if data.empty:
            return "No data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching company statistics: {e!s}"


def list_available_fields() -> list[dict[str, str]]:
    """
    List available fields in the NDAQ/STAT table with descriptions.

    Returns:
        List of dictionaries containing field name and description
    """
    fields = [
        {"name": "symbol", "description": "Symbol of the company"},
        {"name": "figi", "description": "Unique Identifier given by Bloomberg"},
        {
            "name": "marketcap",
            "description": (
                "Market cap of the security calculated as shares outstanding * "
                "previous day close"
            ),
        },
        {
            "name": "high52week",
            "description": (
                "Highest fully adjusted price observed during trading hours over "
                "the past 52 calendar weeks"
            ),
        },
        {
            "name": "high52week_date",
            "description": (
                "The date when the highest fully adjusted price was observed "
                "over the past 52 weeks"
            ),
        },
        {
            "name": "low52week",
            "description": (
                "Lowest fully adjusted price observed during trading hours over "
                "the past 52 calendar weeks"
            ),
        },
        {
            "name": "low52week_date",
            "description": (
                "The date when the lowest fully adjusted price was observed "
                "over the past 52 weeks"
            ),
        },
        {
            "name": "avgvolume1m",
            "description": "Average 1 month volume based on calendar days",
        },
        {
            "name": "avgvolume3m",
            "description": "Average 3-month volume based on calendar days",
        },
        {
            "name": "divyield",
            "description": (
                "Dividend Yield measures the ratio between a company's "
                "dividendPerShare and its price"
            ),
        },
        {
            "name": "dividendpershare",
            "description": (
                "The dividends per share unit, adjusted for stock splits and "
                "stock dividends"
            ),
        },
        {
            "name": "nextdividenddate",
            "description": "Expected ex date of the next dividend",
        },
        {"name": "exdividenddate", "description": "Ex date of the last dividend"},
        {
            "name": "nextearningsdate",
            "description": "Expected next earnings report date",
        },
        {
            "name": "pe",
            "description": "Measures the ratio between marketcap and netinccmn",
        },
        {
            "name": "epsdil",
            "description": (
                "Earnings per diluted share as calculated and reported by the company"
            ),
        },
        {
            "name": "eps",
            "description": (
                "Earnings per share as calculated and reported by the company"
            ),
        },
        {
            "name": "pe1",
            "description": (
                "An alternative to pe representing the ratio between price and eps"
            ),
        },
        {
            "name": "pb",
            "description": "Measures the ratio between marketcap and equity",
        },
        {
            "name": "freefloat",
            "description": (
                "The free float percentage of shares available for trading (0-1)"
            ),
        },
    ]
    return fields
