from typing import List, Dict
import csv
import nasdaqdatalink

# Define the function to load indicators directly in this file to avoid circular imports
def load_indicator_metadata(filepath="src/resources/world_data_bank/metadata/metadata.csv") -> Dict[str, str]:
    """Load indicator metadata from CSV file."""
    mapping = {}
    with open(filepath, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                series_id, description = row[0].strip(), row[1].strip()
                if series_id and description:
                    mapping[series_id] = description
    return mapping

# Load indicators on module import
INDICATORS = load_indicator_metadata()


def get_indicator_value(country: str, indicator: str) -> str:
    """
    Fetch the most recent value of a World Bank development indicator for a given country.

    The `indicator` should describe what you're interested in. Examples:
    - "share of youth not in education"
    - "employment to population ratio"
    - "female NEET rate"
    - "GDP per person employed"
    """
    try:
        df = nasdaqdatalink.get_table(
            "WB/DATA",
            series_id=indicator,
            country_code=country,
        )
        if df.empty:
            return f"No data found for {indicator} in country."
        return df
    except Exception as e:
        return f"Error fetching {indicator}: {str(e)}"


def search_indicators(keyword: str) -> List[str]:
    """
    Search for indicator descriptions matching a given keyword.
    """
    keyword_lower = keyword.lower()
    matches = [
        f"{code}: {desc}"
        for code, desc in INDICATORS.items()
        if keyword_lower in desc.lower()
    ]
    return matches[:10]  # return up to 10 matches


def list_all_indicators() -> List[str]:
    """
    List all available indicator codes and descriptions.
    """
    return [f"{series_id}: {desc}" for series_id, desc in INDICATORS.items()]
