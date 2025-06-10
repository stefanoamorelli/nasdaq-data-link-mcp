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
from nasdaq_data_link_mcp_os.resources.equities_360.fundamental_details import (
    get_fundamental_details,
    list_available_detail_fields,
)
from nasdaq_data_link_mcp_os.resources.equities_360.balance_sheet import (
    get_balance_sheet,
    list_available_balance_sheet_fields,
)
from nasdaq_data_link_mcp_os.resources.equities_360.cash_flow import (
    get_cash_flow,
    list_available_cash_flow_fields,
)
from nasdaq_data_link_mcp_os.resources.equities_360.corporate_actions import (
    get_corporate_actions,
    list_available_corporate_action_fields,
)
from nasdaq_data_link_mcp_os.resources.equities_360.reference_data import (
    get_reference_data,
    list_available_reference_fields,
)
from nasdaq_data_link_mcp_os.resources.trade_summary.trade_data import get_trade_summary
from nasdaq_data_link_mcp_os.resources.nfn.fund_master_report import (
    get_mfrfm_data,
    get_mfrfi_data,
    get_mfrsm_data,
    get_mfrsi_data,
    get_mfrph_data,
    get_mfrph10_data,
    get_mfrps_data,
    get_mfrprb_data,
    get_mfrpa_data,
    get_mfrpm_data,
    get_mfrmf_data
)
from nasdaq_data_link_mcp_os.config import initialize_api

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
def get_fundamental_data(
    symbol: Optional[str] = None,
    figi: Optional[str] = None,
    calendardate: Optional[str] = None,
    dimension: Optional[str] = None,
):
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


@mcp.tool()
def get_detailed_financials(
    symbol: Optional[str] = None,
    figi: Optional[str] = None,
    calendardate: Optional[str] = None,
    dimension: Optional[str] = None,
):
    """
    Retrieves detailed financial data from Nasdaq Equities 360 Fundamental Details database.

    Provides comprehensive financial statement data including balance sheet items, income statement
    components, cash flow statement details, and financial ratios.

    Either symbol or figi must be provided.

    Parameters:
      - symbol: Stock ticker symbol (e.g., 'MSFT')
      - figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
      - calendardate: Calendar date in YYYY-MM-DD format (e.g., '2022-12-31')
      - dimension: Data dimension (MRQ: quarterly, MRY: annual, MRT: trailing twelve months)

    Example: get_detailed_financials(symbol='MSFT', dimension='MRY')
    Example: get_detailed_financials(figi='BBG000BPH459', calendardate='2022-12-31')
    """
    return get_fundamental_details(symbol, figi, calendardate, dimension)


@mcp.tool()
def list_detailed_financial_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the fundamental details database with descriptions.

    This helps users understand what data is available through the get_detailed_financials tool,
    including balance sheet items, income statement components, cash flow details, and more.
    """
    return list_available_detail_fields()


@mcp.tool()
def get_balance_sheet_data(
    symbol: Optional[str] = None,
    figi: Optional[str] = None,
    calendardate: Optional[str] = None,
    dimension: Optional[str] = None,
):
    """
    Retrieves balance sheet data from Nasdaq Equities 360 Balance Sheet database.

    Provides comprehensive balance sheet data including assets, liabilities, equity,
    and detailed breakdowns of each category.

    Either symbol or figi must be provided.

    Parameters:
      - symbol: Stock ticker symbol (e.g., 'MSFT')
      - figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
      - calendardate: Calendar date in YYYY-MM-DD format (e.g., '2022-12-31')
      - dimension: Data dimension (MRQ: quarterly, MRY: annual, MRT: trailing twelve months)

    Example: get_balance_sheet_data(symbol='MSFT', dimension='MRY')
    Example: get_balance_sheet_data(figi='BBG000BPH459', calendardate='2022-12-31')
    """
    return get_balance_sheet(symbol, figi, calendardate, dimension)


@mcp.tool()
def list_balance_sheet_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the balance sheet database with descriptions.

    This helps users understand what data is available through the get_balance_sheet_data tool,
    including assets, liabilities, equity, and detailed breakdowns of each category.
    """
    return list_available_balance_sheet_fields()


@mcp.tool()
def get_cash_flow_data(
    symbol: Optional[str] = None,
    figi: Optional[str] = None,
    calendardate: Optional[str] = None,
    dimension: Optional[str] = None,
):
    """
    Retrieves cash flow statement data from Nasdaq Equities 360 Cash Flow database.

    Provides cash flow statement data including operating, investing, and financing
    activities, as well as free cash flow and capital expenditure information.

    Either symbol or figi must be provided.

    Parameters:
      - symbol: Stock ticker symbol (e.g., 'MSFT')
      - figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
      - calendardate: Calendar date in YYYY-MM-DD format (e.g., '2022-12-31')
      - dimension: Data dimension (MRQ: quarterly, MRY: annual, MRT: trailing twelve months)

    Example: get_cash_flow_data(symbol='MSFT', dimension='MRY')
    Example: get_cash_flow_data(figi='BBG000BPH459', calendardate='2022-12-31')
    """
    return get_cash_flow(symbol, figi, calendardate, dimension)


@mcp.tool()
def list_cash_flow_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the cash flow statement database with descriptions.

    This helps users understand what data is available through the get_cash_flow_data tool,
    including operating, investing, and financing cash flows, and related metrics.
    """
    return list_available_cash_flow_fields()


@mcp.tool()
def get_corporate_action_data(
    symbol: Optional[str] = None,
    figi: Optional[str] = None,
    date: Optional[str] = None,
    action: Optional[str] = None,
):
    """
    Retrieves corporate actions data from Nasdaq Equities 360 Corporate Actions database.

    Provides information about corporate events such as stock splits, mergers, acquisitions,
    and other significant company actions that can affect stock price and ownership.

    Parameters:
      - symbol: Stock ticker symbol (e.g., 'TSLA')
      - figi: Bloomberg FIGI identifier
      - date: Date of the corporate action in YYYY-MM-DD format (e.g., '2023-03-24')
      - action: Type of corporate action (e.g., 'split', 'merger')

    Example: get_corporate_action_data(symbol='TSLA', action='split')
    Example: get_corporate_action_data(date='2023-03-24')
    """
    return get_corporate_actions(symbol, figi, date, action)


@mcp.tool()
def list_corporate_action_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the corporate actions database with descriptions.

    This helps users understand what data is available through the get_corporate_action_data tool,
    including date, action type, value, and related company information.
    """
    return list_available_corporate_action_fields()


@mcp.tool()
def get_company_reference_data(
    symbol: Optional[str] = None, figi: Optional[str] = None
):
    """
    Retrieves company reference data from Nasdaq Equities 360 Reference Data database.

    Provides static information about companies including exchange, industry, sector,
    company website, SEC filings links, and location information.

    Either symbol or figi must be provided.

    Parameters:
      - symbol: Stock ticker symbol (e.g., 'AMD')
      - figi: Bloomberg FIGI identifier (e.g., 'BBG000BBQCY0')

    Example: get_company_reference_data(symbol='AMD')
    Example: get_company_reference_data(figi='BBG000BBQCY0')
    """
    return get_reference_data(symbol, figi)


@mcp.tool()
def list_reference_data_fields() -> List[Dict[str, str]]:
    """
    Lists all available fields in the company reference database with descriptions.

    This helps users understand what data is available through the get_company_reference_data tool,
    including exchange, industry, sector, company website, and location information.
    """
    return list_available_reference_fields()


@mcp.tool()
def get_trade_summary_data(**kwargs):
    """
    Retrieves Trade Summary data from Nasdaq Data Link NDAQ/TS datatable.

    Provides consolidated trade data including open, high, low, close, and volume.

    Examples:
      get_trade_summary_data() # Returns all available data (may be limited by API quotas)
    """
    return get_trade_summary(**kwargs)


@mcp.tool()
def get_fund_master_report(fund_id: Optional[str] = None, name: Optional[str] = None, 
                         investment_company_type: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Master Report (NFN/MFRFM) data from Nasdaq Fund Network.
    
    Provides basic information about live NFN funds, mutual funds and closed-end funds.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - name: Optional fund name
      - investment_company_type: Optional investment company type (N-1A for Open-Ended mutual funds, N-2 for Closed-End funds)
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_fund_master_report(fund_id='12345')
    Example: get_fund_master_report(investment_company_type='N-1A')
    """
    return get_mfrfm_data(fund_id, name, investment_company_type, **kwargs)


@mcp.tool()
def get_fund_information(fund_id: Optional[str] = None, name: Optional[str] = None, 
                       investment_company_type: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Information Report (NFN/MFRFI) data from Nasdaq Fund Network.
    
    Provides detailed information about funds including investment strategy, objectives,
    and classification data.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - name: Optional fund name
      - investment_company_type: Optional investment company type (N-1A for Open-Ended mutual funds, N-2 for Closed-End funds)
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_fund_information(fund_id='12345')
    Example: get_fund_information(investment_company_type='N-1A')
    """
    return get_mfrfi_data(fund_id, name, investment_company_type, **kwargs)


@mcp.tool()
def get_share_class_master(fund_id: Optional[str] = None, name: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Share Class Master (NFN/MFRSM) data from Nasdaq Fund Network.
    
    Provides basic information about fund share classes, including identifiers and name.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - name: Optional fund name
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_share_class_master(fund_id='12345')
    Example: get_share_class_master(name='Growth Fund')
    """
    return get_mfrsm_data(fund_id, name, **kwargs)


@mcp.tool()
def get_share_class_information(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Share Class Information (NFN/MFRSI) data from Nasdaq Fund Network.
    
    Provides detailed information about fund share classes including minimum investments,
    fees, and other attributes.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_share_class_information(fund_id='12345')
    Example: get_share_class_information(ticker='ABCDX')
    """
    return get_mfrsi_data(fund_id, ticker, **kwargs)


@mcp.tool()
def get_price_history(fund_id: Optional[str] = None, ticker: Optional[str] = None, 
                    start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Price History (NFN/MFRPH) data from Nasdaq Fund Network.
    
    Provides historical NAV, offering, and redemption prices for funds.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - start_date: Optional start date for price history (YYYY-MM-DD format)
      - end_date: Optional end date for price history (YYYY-MM-DD format)
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_price_history(ticker='ABCDX', start_date='2024-01-01', end_date='2024-04-30')
    Example: get_price_history(fund_id='12345')
    """
    return get_mfrph_data(fund_id, ticker, start_date, end_date, **kwargs)


@mcp.tool()
def get_recent_price_history(fund_id: Optional[str] = None, ticker: Optional[str] = None, 
                           start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs):
    """
    Retrieves recent Fund Price History (NFN/MFRPH10) data from Nasdaq Fund Network.
    
    Provides historical NAV, offering, and redemption prices for funds for the last 10 trading days.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - start_date: Optional start date for price history (YYYY-MM-DD format)
      - end_date: Optional end date for price history (YYYY-MM-DD format)
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_recent_price_history(ticker='ABCDX')
    Example: get_recent_price_history(fund_id='12345')
    """
    return get_mfrph10_data(fund_id, ticker, start_date, end_date, **kwargs)


@mcp.tool()
def get_performance_statistics(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Performance Statistics (NFN/MFRPS) data from Nasdaq Fund Network.
    
    Provides performance returns for various time periods (1mo, 3mo, YTD, 1yr, 3yr, etc.).
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_performance_statistics(ticker='ABCDX')
    Example: get_performance_statistics(fund_id='12345')
    """
    return get_mfrps_data(fund_id, ticker, **kwargs)


@mcp.tool()
def get_performance_benchmark(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Performance Benchmark (NFN/MFRPRB) data from Nasdaq Fund Network.
    
    Provides information about fund benchmark indexes used for performance comparison.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_performance_benchmark(ticker='ABCDX')
    Example: get_performance_benchmark(fund_id='12345')
    """
    return get_mfrprb_data(fund_id, ticker, **kwargs)


@mcp.tool()
def get_performance_analytics(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Performance Analytics (NFN/MFRPA) data from Nasdaq Fund Network.
    
    Provides analytical metrics such as alpha, beta, R-squared, Sharpe ratio, etc.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_performance_analytics(ticker='ABCDX')
    Example: get_performance_analytics(fund_id='12345')
    """
    return get_mfrpa_data(fund_id, ticker, **kwargs)


@mcp.tool()
def get_fees_and_expenses(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Fee and Expense Data (NFN/MFRPM) from Nasdaq Fund Network.
    
    Provides information about fund fees, expenses, and sales charges.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_fees_and_expenses(ticker='ABCDX')
    Example: get_fees_and_expenses(fund_id='12345')
    """
    return get_mfrpm_data(fund_id, ticker, **kwargs)


@mcp.tool()
def get_monthly_flows(fund_id: Optional[str] = None, ticker: Optional[str] = None, **kwargs):
    """
    Retrieves Fund Monthly Flows (NFN/MFRMF) data from Nasdaq Fund Network.
    
    Provides historical fund flow data on a monthly basis.
    
    Parameters:
      - fund_id: Optional unique fund identifier 
      - ticker: Optional ticker symbol
      - Additional parameters supported by the Nasdaq Data Link API
      
    Example: get_monthly_flows(ticker='ABCDX')
    Example: get_monthly_flows(fund_id='12345')
    """
    return get_mfrmf_data(fund_id, ticker, **kwargs)


if __name__ == "__main__":
    mcp.run()
