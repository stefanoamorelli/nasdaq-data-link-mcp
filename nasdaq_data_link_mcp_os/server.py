import argparse
import sys
from typing import Any

import nasdaqdatalink as ndl
from mcp.server.fastmcp import FastMCP

from nasdaq_data_link_mcp_os.config import initialize_api
from nasdaq_data_link_mcp_os.resources_registry import get_databases_resource

mcp = FastMCP("NASDAQ Data Link MCP", dependencies=["nasdaq-data-link", "pycountry"])

api_initialized = False
if "pytest" not in sys.modules:
    api_initialized = initialize_api()


@mcp.resource("nasdaq://databases")
def list_available_databases() -> str:
    """List all available Nasdaq Data Link databases with descriptions."""
    return get_databases_resource()


@mcp.tool()
def search_datasets(query: str) -> list[dict[str, Any]]:
    """
    Search for datasets by keyword.

    Parameters:
      - query: Search term (e.g., 'GDP', 'stock prices', 'bitcoin')

    Example: search_datasets(query='oil prices')
    """
    results = ndl.Dataset.search(query, per_page=10)
    return [
        {
            "code": r.code,
            "name": r.name,
            "description": r.description,
        }
        for r in results
    ]


@mcp.tool()
def get_dataset(
    dataset_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """
    Get data from a specific dataset.

    Parameters:
      - dataset_code: Dataset code in format 'DATABASE/DATASET' (e.g., 'WIKI/AAPL')
      - start_date: Optional start date in YYYY-MM-DD format
      - end_date: Optional end date in YYYY-MM-DD format

    Example: get_dataset(dataset_code='WIKI/AAPL', start_date='2020-01-01')
    """
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    data = ndl.get(dataset_code, **params)
    return data.to_json(orient="split", date_format="iso")


@mcp.tool()
def get_dataset_metadata(dataset_code: str) -> dict[str, Any]:
    """
    Get metadata about a dataset without downloading data.

    Parameters:
      - dataset_code: Dataset code in format 'DATABASE/DATASET' (e.g., 'WIKI/AAPL')

    Example: get_dataset_metadata(dataset_code='WIKI/AAPL')
    """
    dataset = ndl.Dataset(dataset_code)
    return {
        "code": dataset.code,
        "name": dataset.name,
        "description": dataset.description,
        "column_names": dataset.column_names,
    }


@mcp.tool()
def list_databases() -> list[dict[str, Any]]:
    """
    List available databases.

    Example: list_databases()
    """
    databases = ndl.Database.all(per_page=20)

    return [
        {
            "code": db.database_code,
            "name": db.name,
            "description": db.description,
        }
        for db in databases
    ]


@mcp.tool()
def export_dataset(
    dataset_code: str,
    output_format: str = "csv",
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """
    Export dataset in different formats.

    Parameters:
      - dataset_code: Dataset code in format 'DATABASE/DATASET'
      - output_format: Export format: 'csv', 'json', or 'xml' (default: csv)
      - start_date: Optional start date in YYYY-MM-DD format
      - end_date: Optional end date in YYYY-MM-DD format

    Example: export_dataset(dataset_code='WIKI/AAPL', output_format='json')
    """
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    data = ndl.get(dataset_code, **params)

    if output_format == "csv":
        return data.to_csv(index=True)
    elif output_format == "json":
        return data.to_json(orient="records", date_format="iso")
    elif output_format == "xml":
        return data.to_xml(index=True)
    else:
        raise ValueError(
            f"Unsupported format: {output_format}. Use 'csv', 'json', or 'xml'"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nasdaq Data Link MCP Server")
    parser.add_argument(
        "--transport",
        type=str,
        default="stdio",
        choices=["streamable-http", "sse", "stdio"],
        help="Transport protocol to use (default: stdio)",
    )
    args = parser.parse_args()

    mcp.run(transport=args.transport)
