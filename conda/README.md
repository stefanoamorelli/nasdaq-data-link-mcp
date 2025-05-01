# Conda Package Build for Nasdaq Data Link MCP

This directory contains the necessary files to build a conda package for the Nasdaq Data Link MCP server.

## Building Locally

To build the conda package locally:

1. Install conda-build:
```
conda install conda-build
```

2. Build the package:
```
conda build conda/
```

## Package Information

This conda package installs:
- The Nasdaq Data Link MCP server
- All required dependencies (mcp-cli, nasdaq-data-link, pycountry)

## Using the Package

After installation, you can register the server with:

```
mcp install nasdaq_data_link_mcp_os/server.py --name "Nasdaq Data Link MCP Server" --with nasdaq-data-link --with pycountry
```

## Anaconda Cloud

The package is available on Anaconda Cloud at:
https://anaconda.org/stefano.amorelli/nasdaq-data-link-mcp-os

## Maintainer

This package is maintained by [Stefano Amorelli](https://github.com/stefanoamorelli).