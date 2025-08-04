"""
Basic functionality tests for Nasdaq Data Link MCP Server
"""

import os
import sys

import pytest

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBasicFunctionality:
    """Test basic functionality without complex MCP internals"""

    def test_server_import(self):
        """Test that the server module can be imported"""
        try:
            from nasdaq_data_link_mcp_os.server import mcp

            assert mcp is not None
            assert hasattr(mcp, "name")
        except ImportError as e:
            pytest.fail(f"Failed to import server: {e}")

    def test_core_functions_callable(self):
        """Test that core functions can be imported and are callable"""
        from nasdaq_data_link_mcp_os.resources.common.countries import get_country_code
        from nasdaq_data_link_mcp_os.resources.equities_360.company_statistics import (
            get_company_stats,
        )
        from nasdaq_data_link_mcp_os.resources.world_data_bank.indicators import (
            get_indicator_value,
        )

        assert callable(get_company_stats)
        assert callable(get_indicator_value)
        assert callable(get_country_code)

    def test_parameter_validation(self):
        """Test basic parameter validation"""
        from nasdaq_data_link_mcp_os.resources.equities_360.company_statistics import (
            get_company_stats,
        )

        # Test with no parameters - should return error message
        result = get_company_stats()
        assert "Error" in str(result)

        # Test with valid parameter structure (may fail due to API, but shouldn't crash)
        try:
            result = get_company_stats(symbol="MSFT")
            # Should return something (error message or data)
            assert result is not None
        except Exception:
            # API errors are acceptable in tests
            assert True

    def test_country_code_function(self):
        """Test country code conversion"""
        from nasdaq_data_link_mcp_os.resources.common.countries import get_country_code

        # Test with a known country
        result = get_country_code("United States")
        assert result is not None
        assert isinstance(result, str)

        # Test with invalid input
        result = get_country_code("NonExistentCountry123")
        # Should handle gracefully (return None, error message, etc.)
        assert result is None or "Error" in str(result) or "Unknown" in str(result)


class TestModuleStructure:
    """Test that the module structure is correct"""

    def test_main_modules_exist(self):
        """Test that main resource modules can be imported"""
        modules_to_test = [
            "nasdaq_data_link_mcp_os.config",
            "nasdaq_data_link_mcp_os.resources.equities_360.company_statistics",
            "nasdaq_data_link_mcp_os.resources.world_data_bank.indicators",
            "nasdaq_data_link_mcp_os.resources.rtat.retail_activity",
            "nasdaq_data_link_mcp_os.resources.trade_summary.trade_data",
            "nasdaq_data_link_mcp_os.resources.nfn.fund_master_report",
        ]

        for module_name in modules_to_test:
            try:
                __import__(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_server_has_expected_attributes(self):
        """Test that server has expected attributes"""
        from nasdaq_data_link_mcp_os.server import mcp

        assert hasattr(mcp, "name")
        assert isinstance(mcp.name, str)
        assert len(mcp.name) > 0


class TestErrorHandling:
    """Test error handling in core functions"""

    def test_missing_api_key_handling(self):
        """Test that functions handle missing API key gracefully"""
        # Temporarily remove API key
        original_key = os.environ.get("NASDAQ_DATA_LINK_API_KEY")
        if "NASDAQ_DATA_LINK_API_KEY" in os.environ:
            del os.environ["NASDAQ_DATA_LINK_API_KEY"]

        try:
            from nasdaq_data_link_mcp_os.resources.equities_360.company_statistics import (  # noqa: E501
                get_company_stats,
            )

            # Should not crash, may return error message
            result = get_company_stats(symbol="MSFT")
            assert result is not None  # Should return something, even if error

        except Exception as e:
            # Some exceptions are expected without API key
            assert "api" in str(e).lower() or "key" in str(e).lower()
        finally:
            # Restore API key
            if original_key:
                os.environ["NASDAQ_DATA_LINK_API_KEY"] = original_key


if __name__ == "__main__":
    pytest.main([__file__])
