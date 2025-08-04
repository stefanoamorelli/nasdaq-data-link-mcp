import nasdaqdatalink
import pandas as pd


def get_mfrfm_data(
    fund_id: str | None = None,
    name: str | None = None,
    investment_company_type: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch Fund Master Report (NFN/MFRFM) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        name: Optional fund name
        investment_company_type: Optional investment company type (
            N-1A for Open-Ended mutual funds, N-2 for Closed-End funds
        )
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Master Report data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if name:
            params["name"] = name
        if investment_company_type:
            params["investment_company_type"] = investment_company_type

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRFM table
        df = nasdaqdatalink.get_table("NFN/MFRFM", **params)

        if df.empty:
            return "No fund data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund data: {e!s}"


def get_mfrfi_data(
    fund_id: str | None = None,
    name: str | None = None,
    investment_company_type: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch Fund Information Report (NFN/MFRFI) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        name: Optional fund name
        investment_company_type: Optional investment company type (
            N-1A for Open-Ended mutual funds, N-2 for Closed-End funds
        )
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Information Report data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if name:
            params["name"] = name
        if investment_company_type:
            params["investment_company_type"] = investment_company_type

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRFI table
        df = nasdaqdatalink.get_table("NFN/MFRFI", **params)

        if df.empty:
            return "No fund data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund information data: {e!s}"


def get_mfrsm_data(
    fund_id: str | None = None, name: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Share Class Master (NFN/MFRSM) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        name: Optional fund name
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Share Class Master data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if name:
            params["name"] = name

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRSM table
        df = nasdaqdatalink.get_table("NFN/MFRSM", **params)

        if df.empty:
            return "No fund share class data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund share class data: {e!s}"


def get_mfrsi_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Share Class Information (NFN/MFRSI) data with optional
    filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Share Class Information data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRSI table
        df = nasdaqdatalink.get_table("NFN/MFRSI", **params)

        if df.empty:
            return "No fund share class information found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund share class information: {e!s}"


def get_mfrph_data(
    fund_id: str | None = None,
    ticker: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch Fund Price History (NFN/MFRPH) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        start_date: Optional start date for price history (YYYY-MM-DD format)
        end_date: Optional end date for price history (YYYY-MM-DD format)
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Price History data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker
        if start_date:
            params["date.gte"] = start_date
        if end_date:
            params["date.lte"] = end_date

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPH table
        df = nasdaqdatalink.get_table("NFN/MFRPH", **params)

        if df.empty:
            return "No fund price history found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund price history: {e!s}"


def get_mfrph10_data(
    fund_id: str | None = None,
    ticker: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch Fund Price History 10-day (NFN/MFRPH10) data with optional
    filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        start_date: Optional start date for price history (YYYY-MM-DD format)
        end_date: Optional end date for price history (YYYY-MM-DD format)
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Price History 10-day data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker
        if start_date:
            params["date.gte"] = start_date
        if end_date:
            params["date.lte"] = end_date

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPH10 table
        df = nasdaqdatalink.get_table("NFN/MFRPH10", **params)

        if df.empty:
            return "No 10-day fund price history found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching 10-day fund price history: {e!s}"


def get_mfrps_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Performance Statistics (NFN/MFRPS) data with optional
    filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Performance Statistics data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPS table
        df = nasdaqdatalink.get_table("NFN/MFRPS", **params)

        if df.empty:
            return "No fund performance statistics found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund performance statistics: {e!s}"


def get_mfrprb_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Performance Benchmark (NFN/MFRPRB) data with optional
    filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Performance Benchmark data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPRB table
        df = nasdaqdatalink.get_table("NFN/MFRPRB", **params)

        if df.empty:
            return (
                "No fund performance benchmark data found for the specified parameters."
            )
        return df
    except Exception as e:
        return f"Error fetching fund performance benchmark data: {e!s}"


def get_mfrpa_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Performance Analytics (NFN/MFRPA) data with optional
    filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Performance Analytics data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPA table
        df = nasdaqdatalink.get_table("NFN/MFRPA", **params)

        if df.empty:
            return "No fund performance analytics found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund performance analytics: {e!s}"


def get_mfrpm_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Fee and Expense Data (NFN/MFRPM) with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Fee and Expense data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRPM table
        df = nasdaqdatalink.get_table("NFN/MFRPM", **params)

        if df.empty:
            return "No fund fee and expense data found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund fee and expense data: {e!s}"


def get_mfrmf_data(
    fund_id: str | None = None, ticker: str | None = None, **kwargs
) -> pd.DataFrame:
    """
    Fetch Fund Monthly Flows (NFN/MFRMF) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        ticker: Optional ticker symbol
        **kwargs: Additional filtering parameters to pass to the API

    Returns:
        DataFrame with Fund Monthly Flows data
    """
    try:
        params = {}
        if fund_id:
            params["fund_id"] = fund_id
        if ticker:
            params["ticker"] = ticker

        # Add additional parameters from kwargs
        params.update(kwargs)

        # Fetch data from NFN/MFRMF table
        df = nasdaqdatalink.get_table("NFN/MFRMF", **params)

        if df.empty:
            return "No fund monthly flows found for the specified parameters."
        return df
    except Exception as e:
        return f"Error fetching fund monthly flows: {e!s}"
