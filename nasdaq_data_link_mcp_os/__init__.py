"""Community-maintained MCP server for the Nasdaq Data Link Tables API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nasdaq-data-link-mcp-os")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
