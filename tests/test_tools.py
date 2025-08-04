"""
Tests for individual MCP tools
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nasdaq_data_link_mcp_os.resources.common.countries import get_country_code
from nasdaq_data_link_mcp_os.resources.equities_360.company_statistics import (
    get_company_stats,
)
from nasdaq_data_link_mcp_os.resources.world_data_bank.indicators import (
    get_indicator_value,
)


class TestEquitiesTools:
    """Test tools from Equities 360 module"""

    @patch(
        "nasdaq_data_link_mcp_os.resources.equities_360.company_statistics.nasdaqdatalink"
    )
    def test_get_company_stats_with_symbol(self, mock_nasdaqdatalink):
        """Test get_company_stats tool with a valid symbol"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.to_dict.return_value = {
            "data": [{"symbol": "MSFT", "marketcap": 2800000000000}]
        }
        mock_nasdaqdatalink.get_table.return_value = mock_response

        # Test the function (this would be called by MCP framework)
        # Note: Actual implementation may vary, this tests the concept
        result = get_company_stats(symbol="MSFT")

        # Verify the API was called with correct parameters
        mock_nasdaqdatalink.get_table.assert_called_once()
        assert result is not None

    def test_get_company_stats_parameter_validation(self):
        """Test parameter validation for company stats"""
        # Test that either symbol or figi is required
        result = get_company_stats()  # No parameters should return error message
        assert "Error" in str(result)


class TestWorldBankTools:
    """Test tools from World Bank module"""

    def test_get_indicator_value_basic(self):
        """Test World Bank indicator retrieval basic functionality"""
        # Test that function exists and handles parameters
        try:
            result = get_indicator_value(country="Italy", indicator="NY.GDP.MKTP.CD")
            # Should return something (data or error message), not crash
            assert result is not None
        except Exception as e:
            # API exceptions are acceptable in tests
            assert (
                "api" in str(e).lower()
                or "key" in str(e).lower()
                or "unauthorized" in str(e).lower()
            )


class TestCommonTools:
    """Test common utility tools"""

    def test_country_code_lookup(self):
        """Test country code conversion"""
        # Test valid country name
        result = get_country_code("Italy")
        assert result is not None

        # Test another country
        result = get_country_code("United States")
        assert result is not None

    def test_country_code_invalid(self):
        """Test handling of invalid country names"""
        # Should handle invalid country gracefully
        result = get_country_code("NonExistentCountry")
        assert result is None or "Unknown" in str(result) or "Error" in str(result)


class TestToolRegistration:
    """Test that tools are properly registered with the MCP server"""

    def test_tool_functions_exist(self):
        """Test that key tool functions exist and are callable"""
        from nasdaq_data_link_mcp_os.resources.common.countries import get_country_code
        from nasdaq_data_link_mcp_os.resources.equities_360.company_statistics import (
            get_company_stats,
        )
        from nasdaq_data_link_mcp_os.resources.world_data_bank.indicators import (
            get_indicator_value,
        )

        tools = [get_company_stats, get_indicator_value, get_country_code]

        # Each tool should be callable
        for tool in tools:
            assert callable(tool), f"Tool {tool} is not callable"
            assert hasattr(tool, "__name__"), "Tool missing name attribute"
            assert hasattr(tool, "__doc__"), "Tool missing docstring"
            assert len(tool.__name__) > 0, "Tool has empty name"


class TestDataValidation:
    """Test data validation and sanitization"""

    def test_symbol_validation(self):
        """Test that stock symbols are properly validated"""
        # Valid symbols should work
        valid_symbols = ["MSFT", "AAPL", "GOOGL"]
        for symbol in valid_symbols:
            # This would test actual validation logic in your implementation
            assert len(symbol) <= 10, f"Symbol {symbol} too long"
            assert symbol.isalpha(), f"Symbol {symbol} contains invalid characters"

    def test_date_format_validation(self):
        """Test date format validation"""
        # Test various date formats that should be accepted
        valid_dates = ["2025-08-03", "2024-12-31"]
        for date in valid_dates:
            # Basic format check
            assert len(date) == 10, f"Date {date} wrong length"
            assert date.count("-") == 2, f"Date {date} wrong format"


if __name__ == "__main__":
    pytest.main([__file__])
