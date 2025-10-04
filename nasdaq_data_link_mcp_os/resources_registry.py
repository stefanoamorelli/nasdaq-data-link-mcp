from typing import Any

DATABASES: dict[str, dict[str, Any]] = {
    "WORLDBANK": {
        "name": "World Bank Indicators",
        "description": "Global development indicators from World Bank",
        "examples": ["WORLDBANK/GDP", "WORLDBANK/POPULATION"],
    },
    "NDAQ": {
        "name": "Nasdaq Data Link",
        "description": "Market data including RTAT, trade summaries",
        "examples": ["NDAQ/RTAT", "NDAQ/TS"],
    },
    "NFN": {
        "name": "Nasdaq Fund Network",
        "description": "Mutual fund and ETF data",
        "examples": ["NFN/MFRFM", "NFN/MFRFI"],
    },
    "QOR": {
        "name": "Equities 360",
        "description": "Company fundamentals, financials, statistics",
        "examples": ["QOR/STATS", "QOR/FUNDAMENTALS"],
    },
}


def get_databases_resource() -> str:
    """Generate formatted database resource content."""
    result = "# Available Nasdaq Data Link Databases\n\n"
    for code, info in DATABASES.items():
        result += f"## {code} - {info['name']}\n"
        result += f"{info['description']}\n\n"
        result += f"**Examples:** {', '.join(info['examples'])}\n\n"
    return result
