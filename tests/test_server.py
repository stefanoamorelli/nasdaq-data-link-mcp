"""
Integration tests for Nasdaq Data Link MCP Server
Note: These tests focus on server integration rather than individual functions
"""

import os
import sys

import pytest

# Add the parent directory to the path to import the server module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nasdaq_data_link_mcp_os.server import mcp


class TestMCPServerIntegration:
    """Test cases for the MCP server integration"""

    def test_server_initialization(self):
        """Test that the server initializes correctly"""
        assert mcp is not None
        assert hasattr(mcp, "name")
        assert mcp.name == "NASDAQ Data Link MCP"

    def test_server_has_dependencies(self):
        """Test that server has expected dependencies"""
        assert hasattr(mcp, "dependencies")
        expected_deps = ["nasdaq-data-link", "pycountry"]
        for dep in expected_deps:
            assert dep in mcp.dependencies


class TestModuleImports:
    """Test that all required modules can be imported"""

    def test_import_core_modules(self):
        """Test that core modules can be imported without errors"""
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


class TestConfigurationHandling:
    """Test configuration and environment variable handling"""

    def test_api_configuration(self):
        """Test that API configuration is handled properly"""
        # Test that config module can be imported and used
        from nasdaq_data_link_mcp_os.config import initialize_api

        try:
            initialize_api()
            # Should not raise exception
            assert True
        except Exception as e:
            # Some exceptions are expected in test environment
            assert "api" in str(e).lower() or "key" in str(e).lower()


if __name__ == "__main__":
    pytest.main([__file__])
