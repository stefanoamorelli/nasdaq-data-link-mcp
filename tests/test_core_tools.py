import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def mock_ndl():
    with (
        patch("nasdaqdatalink.get") as mock_get,
        patch("nasdaqdatalink.Dataset") as mock_dataset_cls,
        patch("nasdaqdatalink.Database") as mock_database_cls,
    ):
        yield {
            "get": mock_get,
            "dataset": mock_dataset_cls,
            "database": mock_database_cls,
        }


class TestSearchDatasets:
    def test_search_datasets_basic(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import search_datasets

        mock_result = MagicMock()
        mock_result.code = "WIKI/AAPL"
        mock_result.name = "Apple Inc."
        mock_result.description = "Stock prices"

        with patch("nasdaqdatalink.Dataset.search", return_value=[mock_result]):
            results = search_datasets("apple")

        assert len(results) == 1
        assert results[0]["code"] == "WIKI/AAPL"
        assert results[0]["name"] == "Apple Inc."


class TestGetDataset:
    def test_get_dataset_basic(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import get_dataset

        mock_df = pd.DataFrame({"Date": ["2020-01-01"], "Close": [100.0]})
        mock_ndl["get"].return_value = mock_df

        result = get_dataset("WIKI/AAPL")
        data = json.loads(result)

        assert "columns" in data
        assert "data" in data
        mock_ndl["get"].assert_called_once_with("WIKI/AAPL")

    def test_get_dataset_with_params(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import get_dataset

        mock_df = pd.DataFrame({"Date": ["2020-01-01"], "Close": [100.0]})
        mock_ndl["get"].return_value = mock_df

        get_dataset("WIKI/AAPL", start_date="2020-01-01", end_date="2020-12-31")

        mock_ndl["get"].assert_called_once_with(
            "WIKI/AAPL", start_date="2020-01-01", end_date="2020-12-31"
        )


class TestGetDatasetMetadata:
    def test_get_dataset_metadata(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import get_dataset_metadata

        mock_dataset = MagicMock()
        mock_dataset.code = "WIKI/AAPL"
        mock_dataset.name = "Apple Inc."
        mock_dataset.description = "Stock data"
        mock_dataset.column_names = ["Date", "Close"]

        mock_ndl["dataset"].return_value = mock_dataset

        result = get_dataset_metadata("WIKI/AAPL")

        assert result["code"] == "WIKI/AAPL"
        assert result["name"] == "Apple Inc."
        assert result["column_names"] == ["Date", "Close"]


class TestListDatabases:
    def test_list_databases_all(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import list_databases

        mock_db = MagicMock()
        mock_db.database_code = "WIKI"
        mock_db.name = "Wikipedia"
        mock_db.description = "Stock data"

        with patch("nasdaqdatalink.Database.all", return_value=[mock_db]):
            results = list_databases()

        assert len(results) == 1
        assert results[0]["code"] == "WIKI"


class TestExportDataset:
    def test_export_csv(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import export_dataset

        mock_df = pd.DataFrame({"Date": ["2020-01-01"], "Close": [100.0]})
        mock_ndl["get"].return_value = mock_df

        result = export_dataset("WIKI/AAPL", output_format="csv")

        assert "Date" in result
        assert "Close" in result

    def test_export_json(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import export_dataset

        mock_df = pd.DataFrame({"Date": ["2020-01-01"], "Close": [100.0]})
        mock_ndl["get"].return_value = mock_df

        result = export_dataset("WIKI/AAPL", output_format="json")
        data = json.loads(result)

        assert isinstance(data, list)

    def test_export_invalid_format(self, mock_ndl):
        from nasdaq_data_link_mcp_os.server import export_dataset

        mock_df = pd.DataFrame({"Date": ["2020-01-01"], "Close": [100.0]})
        mock_ndl["get"].return_value = mock_df

        with pytest.raises(ValueError, match="Unsupported format"):
            export_dataset("WIKI/AAPL", output_format="invalid")
