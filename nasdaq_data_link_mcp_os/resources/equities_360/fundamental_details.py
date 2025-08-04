from typing import Any

import nasdaqdatalink
import pandas as pd


def get_fundamental_details(
    symbol: str | None = None,
    figi: str | None = None,
    calendardate: str | None = None,
    dimension: str | None = None,
) -> pd.DataFrame | str:
    """
    Fetch detailed fundamental data from Nasdaq Data Link E360 NDAQ/FD table.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        figi: Bloomberg FIGI identifier (e.g., 'BBG000BPH459')
        calendardate: Calendar date in YYYY-MM-DD format
        dimension: MRQ (Quarterly), MRY (Annual), or MRT (Trailing-twelve-months)

    Returns:
        DataFrame containing detailed fundamental data or error message
    """
    if not symbol and not figi:
        return "Error: Either symbol or figi must be provided."

    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        if figi:
            params["figi"] = figi
        if calendardate:
            params["calendardate"] = calendardate
        if dimension:
            params["dimension"] = dimension

        # Fetch data from NDAQ/FD table
        data = nasdaqdatalink.get_table("NDAQ/FD", **params)

        if data.empty:
            return "No data found for the specified criteria."

        return data
    except Exception as e:
        return f"Error fetching fundamental details: {e!s}"


def list_available_detail_fields() -> list[dict[str, Any]]:
    """
    List available fields in the NDAQ/FD table with descriptions.

    Returns:
        List of dictionaries containing field name, description, and type
    """
    fields = [
        {
            "name": "calendardate",
            "description": "The Calendar Date represents the normalized reportperiod",
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
            "name": "reportperiod",
            "description": (
                "The Report Period represents the end date of the fiscal period"
            ),
            "type": "Date",
            "primary_key": True,
        },
        {
            "name": "dimension",
            "description": (
                "Dimensional view of data (MRQ: Quarterly, "
                "MRY: annual, MRT: trailing-twelve-months)"
            ),
            "type": "String",
            "filterable": True,
            "primary_key": True,
        },
        {
            "name": "payables",
            "description": (
                "A component of liabilities representing trade and non-trade payables"
            ),
            "type": "BigInt",
        },
        {
            "name": "receivables",
            "description": (
                "A component of assets representing trade and non-trade receivables"
            ),
            "type": "BigInt",
        },
        {
            "name": "cashneq",
            "description": (
                "A component of assets representing currency on hand and "
                "demand deposits"
            ),
            "type": "BigInt",
        },
        {
            "name": "investmentsnc",
            "description": "The non-current portion of investments",
            "type": "BigInt",
        },
        {
            "name": "investmentsc",
            "description": "The current portion of investments",
            "type": "BigInt",
        },
        {
            "name": "taxassets",
            "description": (
                "A component of assets representing tax assets and receivables"
            ),
            "type": "BigInt",
        },
        {
            "name": "ncfo",
            "description": "Cash inflow (outflow) from operating activities",
            "type": "BigInt",
        },
        {
            "name": "capex",
            "description": (
                "Cash inflow (outflow) associated with acquisition & disposal of "
                "long-lived assets"
            ),
            "type": "BigInt",
        },
        {
            "name": "cashnequsd",
            "description": "Cash and equivalents in USD",
            "type": "BigInt",
        },
        {
            "name": "netincdis",
            "description": "Income from a disposal group, net of income tax",
            "type": "BigInt",
        },
        {
            "name": "debtc",
            "description": "The current portion of debt",
            "type": "BigInt",
        },
        {
            "name": "dps",
            "description": (
                "Dividends declared per split-adjusted share of common stock"
            ),
            "type": "Double",
        },
        {
            "name": "retearn",
            "description": "Cumulative amount of undistributed earnings or deficit",
            "type": "BigInt",
        },
        {
            "name": "ebitda",
            "description": (
                "Earnings Before Interest, Taxes, Depreciation and Amortization"
            ),
            "type": "BigInt",
        },
        {
            "name": "ebit",
            "description": "Earnings Before Interest and Tax",
            "type": "BigInt",
        },
        {
            "name": "equity",
            "description": "Total stockholders' equity",
            "type": "BigInt",
        },
        {
            "name": "ncfbus",
            "description": (
                "Cash inflow (outflow) from acquisition & disposal of businesses"
            ),
            "type": "BigInt",
        },
        {
            "name": "depamor",
            "description": "Depreciation, amortization, and accretion",
            "type": "BigInt",
        },
        {
            "name": "taxexp",
            "description": (
                "Current and deferred income tax expense for continuing operations"
            ),
            "type": "BigInt",
        },
        {
            "name": "sgna",
            "description": "Selling, general and administrative expenses",
            "type": "BigInt",
        },
        {
            "name": "rnd",
            "description": "Research and development expenses",
            "type": "BigInt",
        },
        {
            "name": "opex",
            "description": (
                "Operating expenses (sgna, rnd and other operating expenses)"
            ),
            "type": "BigInt",
        },
        {
            "name": "sbcomp",
            "description": "Non-cash, equity-based employee remuneration",
            "type": "BigInt",
        },
        {
            "name": "tangibles",
            "description": "Value of tangible assets (assets minus intangibles)",
            "type": "BigInt",
        },
        {
            "name": "intangibles",
            "description": "Carrying amounts of intangible assets and goodwill",
            "type": "BigInt",
        },
        {
            "name": "eps",
            "description": "Earnings per share as reported by the company",
            "type": "Double",
        },
        {"name": "ebt", "description": "Earnings Before Tax", "type": "BigInt"},
        {
            "name": "netinc",
            "description": "Net income attributable to the parent",
            "type": "BigInt",
        },
        {
            "name": "opinc",
            "description": (
                "Operating income (before interest, taxes and non-operating items)"
            ),
            "type": "BigInt",
        },
        {
            "name": "consolinc",
            "description": "Consolidated net income",
            "type": "BigInt",
        },
        {
            "name": "inventory",
            "description": "Value of inventory expected to be sold within one year",
            "type": "BigInt",
        },
        {
            "name": "debtnc",
            "description": "The non-current portion of debt",
            "type": "BigInt",
        },
        {
            "name": "taxliabilities",
            "description": "Outstanding tax liabilities",
            "type": "BigInt",
        },
        {
            "name": "liabilitiesnc",
            "description": "The non-current portion of liabilities",
            "type": "BigInt",
        },
        {"name": "liabilities", "description": "Total liabilities", "type": "BigInt"},
        {
            "name": "deferredrev",
            "description": "Consideration received but not recognized as revenue",
            "type": "BigInt",
        },
        {
            "name": "accoci",
            "description": "Accumulated other comprehensive income",
            "type": "BigInt",
        },
        {
            "name": "ppnenet",
            "description": "Property, plant, and equipment (net of depreciation)",
            "type": "BigInt",
        },
        {
            "name": "pe1",
            "description": "Price to earnings ratio (price/eps)",
            "type": "Double",
        },
        {
            "name": "gp",
            "description": "Gross profit (revenue minus cost of revenue)",
            "type": "BigInt",
        },
        {
            "name": "grossmargin",
            "description": "Ratio between gross profit and revenue",
            "type": "Double",
        },
        {
            "name": "revenue",
            "description": "Total revenue from goods sold and services rendered",
            "type": "BigInt",
        },
        {
            "name": "intexp",
            "description": "Interest expense on borrowed funds",
            "type": "BigInt",
        },
        {
            "name": "cor",
            "description": (
                "Cost of revenue (goods produced and sold, services rendered)"
            ),
            "type": "BigInt",
        },
        {
            "name": "ncfcommon",
            "description": "Cash flow from common equity changes",
            "type": "BigInt",
        },
        {
            "name": "netinccmn",
            "description": "Net income attributable to common shareholders",
            "type": "BigInt",
        },
        {
            "name": "ncfinv",
            "description": "Cash flow from investments",
            "type": "BigInt",
        },
        {
            "name": "ncff",
            "description": "Cash flow from financing activities",
            "type": "BigInt",
        },
        {
            "name": "shareswa",
            "description": "Weighted average shares outstanding used to calculate EPS",
            "type": "BigInt",
        },
        {
            "name": "epsusd",
            "description": "Earnings per share in USD",
            "type": "Double",
        },
        {
            "name": "workingcapital",
            "description": "Difference between current assets and current liabilities",
            "type": "BigInt",
        },
        {"name": "invcap", "description": "Invested capital", "type": "BigInt"},
        {
            "name": "invcapavg",
            "description": "Average invested capital for the period",
            "type": "BigInt",
        },
        {
            "name": "roic",
            "description": "Return on Invested Capital (EBIT/invcapavg)",
            "type": "Double",
        },
        {
            "name": "freecashflow",
            "description": "Free Cash Flow (ncfo minus capex)",
            "type": "BigInt",
        },
        {
            "name": "ebitdamargin",
            "description": "Ratio between EBITDA and revenue",
            "type": "Double",
        },
        {
            "name": "ev",
            "description": "Enterprise value (marketcap plus debt minus cashneq)",
            "type": "BigInt",
        },
        {
            "name": "evebit",
            "description": "Enterprise Value to EBIT ratio",
            "type": "BigInt",
        },
        {
            "name": "evebitda",
            "description": "Enterprise Value to EBITDA ratio",
            "type": "Double",
        },
        {
            "name": "divyield",
            "description": "Dividend Yield (dps/price)",
            "type": "Double",
        },
        {
            "name": "assetturnover",
            "description": "Revenue divided by average assets",
            "type": "Double",
        },
        {"name": "revenueusd", "description": "Revenue in USD", "type": "BigInt"},
        {
            "name": "debttoassets",
            "description": "Cash flow from debt issuance/repayment",
            "type": "BigInt",
        },
        {
            "name": "shareswadil",
            "description": "Weighted average diluted shares outstanding",
            "type": "BigInt",
        },
        {
            "name": "sharesbas",
            "description": "Basic shares outstanding after stock splits",
            "type": "BigInt",
        },
    ]
    return fields
