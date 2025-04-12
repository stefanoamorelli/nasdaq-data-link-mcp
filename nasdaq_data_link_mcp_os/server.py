from typing import List, Dict, Optional
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
from nasdaq_data_link_mcp_os.resources.equities_360.statistics import (
    get_company_stats,
    list_available_fields,
)
from nasdaq_data_link_mcp_os.resources.equities_360.fundamentals import (
    get_fundamental_summary,
    list_available_fundamental_fields,
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


@mcp.tool()
def get_stock_stats(symbol: Optional[str] = None, figi: Optional[str] = None):
    """
    Retrieves company statistics from Nasdaq Equities 360 database.
    
    Provides comprehensive statistics for a company including market cap, PE ratio, 
    52-week highs/lows, dividend information, and more.
    
    Either symbol or figi must be provided.
    
    Example: get_stock_stats(symbol='MSFT')
    Example: get_stock_stats(figi='BBG000BPH459')
    """
    return get_company_stats(symbol, figi)


@mcp.tool()
def list_stock_stat_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the stock statistics database with descriptions.
    
    This helps users understand what data is available through the get_stock_stats tool.
    """
    return list_available_fields()


@mcp.tool()
def get_fundamental_data(symbol: Optional[str] = None, figi: Optional[str] = None, calendardate: Optional[str] = None, dimension: Optional[str] = None):
    """
    Retrieves fundamental financial data from Nasdaq Equities 360 Fundamental Summary database.
    
    Provides comprehensive fundamental data including profitability ratios, valuation metrics,
    income statement items, and financial health indicators.
    
    Either symbol or figi must be provided.
    
    Parameters:
      - symbol: Stock ticker symbol (e.g., 'MSFT')
      - figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
      - calendardate: Calendar date in YYYY-MM-DD format (e.g., '2022-12-31')
      - dimension: Data dimension (MRQ: quarterly, MRY: annual, MRT: trailing twelve months)
    
    Example: get_fundamental_data(symbol='MSFT', dimension='MRY')
    Example: get_fundamental_data(figi='BBG000BPH459', calendardate='2022-12-31')
    """
    return get_fundamental_summary(symbol, figi, calendardate, dimension)


@mcp.tool()
def list_fundamental_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the fundamental summary database with descriptions.
    
    This helps users understand what data is available through the get_fundamental_data tool,
    including profitability ratios, valuation metrics, and financial health indicators.
    """
    return list_available_fundamental_fields()
