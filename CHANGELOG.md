# Changelog

All notable changes to the Nasdaq Data Link MCP project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-05-17

### Added
- Added comprehensive Nasdaq Fund Network (NFN) tools:
  - `get_fund_information` - Fund Information Report (MFRFI)
  - `get_share_class_master` - Fund Share Class Master (MFRSM)
  - `get_share_class_information` - Fund Share Class Information (MFRSI)
  - `get_price_history` - Fund Price History (MFRPH)
  - `get_recent_price_history` - Fund Price History 10-day (MFRPH10)
  - `get_performance_statistics` - Fund Performance Statistics (MFRPS)
  - `get_performance_benchmark` - Fund Performance Benchmark (MFRPRB)
  - `get_performance_analytics` - Fund Performance Analytics (MFRPA)
  - `get_fees_and_expenses` - Fund Fee and Expense Data (MFRPM)
  - `get_monthly_flows` - Fund Monthly Flows (MFRMF)
- Enhanced NFN documentation with detailed data structures for each tool
- Added new example conversations demonstrating NFN tool usage
- Updated architecture diagram to include all NFN modules

## [0.1.3] - 2025-04-30

### Added
- Initial release with support for:
  - Equities 360 database
  - Retail Trading Activity Tracker (RTAT)
  - Trade Summary database (NDAQ/TS)
  - World Bank dataset
  - Basic Nasdaq Fund Network support (MFRFM only)