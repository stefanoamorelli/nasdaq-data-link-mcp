from typing import Optional
import nasdaqdatalink
import pandas as pd


def get_mfrfm_data(fund_id: Optional[str] = None, name: Optional[str] = None, 
                 investment_company_type: Optional[str] = None, **kwargs) -> pd.DataFrame:
    """
    Fetch Fund Master Report (NFN/MFRFM) data with optional filtering parameters.

    Args:
        fund_id: Optional unique fund identifier
        name: Optional fund name
        investment_company_type: Optional investment company type (N-1A for Open-Ended mutual funds, N-2 for Closed-End funds)
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
        return f"Error fetching fund data: {str(e)}"