from typing import List
from mcp.server.fastmcp import FastMCP
from nasdaq_data_link_mcp_os.resources.common.countries import get_country_code
from nasdaq_data_link_mcp_os.resources.world_data_bank.indicators import (
    get_indicator_value as get_wb_indicator,
    search_indicators,
    list_all_indicators,
)
from nasdaq_data_link_mcp_os.resources.rtat.retail_activity import (
    get_rtat10_data,
    get_rtat_data,
)
from config import initialize_api

# Initialize API configuration
initialize_api()

mcp = FastMCP("NASDAQ Data Link MCP", dependencies=["nasdaq-data-link", "pycountry"])


@mcp.tool()
def get_indicator_value(country: str, indicator: str) -> str:
    return get_wb_indicator(country, indicator)


@mcp.tool()
def country_code(countryName: str) -> str:
    return get_country_code(countryName)


@mcp.tool()
def list_worldbank_indicators() -> List[str]:
    return list_all_indicators()


@mcp.tool()
def search_worldbank_indicators(keyword: str) -> List[str]:
    return search_indicators(keyword)


@mcp.tool()
def get_rtat10(dates: str, tickers: str = None):
    """
    Retrieves Retail Trading Activity Tracker 10 (RTAT10) data for specific dates and optional tickers.

    Example: get_rtat10(dates='2025-03-31,2025-03-28,2025-03-27', tickers='TSLA,TQQQ,SQQQ')
    """
    return get_rtat10_data(dates, tickers)


@mcp.tool()
def get_rtat(dates: str, tickers: str = None):
    """
    Retrieves Retail Trading Activity (RTAT) data for specific dates and optional tickers.

    Example: get_rtat(dates='2025-03-31,2025-03-28,2025-03-27', tickers='TSLA,TQQQ,SQQQ')
    """
    return get_rtat_data(dates, tickers)
