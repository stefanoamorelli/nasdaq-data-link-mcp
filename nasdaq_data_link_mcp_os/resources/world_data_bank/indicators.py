import nasdaqdatalink


# Define a function to load indicators from Nasdaq Data Link directly
def load_indicator_metadata() -> dict[str, dict[str, str]]:
    """Load indicator metadata from WB/METADATA dataset."""
    try:
        metadata_df = nasdaqdatalink.get_table("WB/METADATA")

        # Convert DataFrame to dictionary
        metadata_dict = {}
        for _, row in metadata_df.iterrows():
            series_id = row.get("series_id", "")
            name = row.get("name", "")
            description = row.get("description", "")

            if series_id:
                metadata_dict[series_id] = {"name": name, "description": description}

        return metadata_dict
    except Exception:
        return {}


def get_indicator_value(country: str, indicator: str) -> str:
    """
    Fetch the most recent value of a World Bank development indicator for a
    given country.

    The `indicator` parameter can be either:
    1. An exact indicator code (e.g., 'NY.GDP.MKTP.CD')
    2. A descriptive keyword (e.g., 'GDP', 'population', 'CO2 emissions')

    Examples:
    - "share of youth not in education"
    - "employment to population ratio"
    - "female NEET rate"
    - "GDP per person employed"
    """
    # Check if the indicator is a direct code or needs to be searched
    metadata = load_indicator_metadata()

    # If indicator is not a direct code, try to find a match
    if indicator not in metadata:
        # Search for matching indicators
        matches = search_indicators(indicator)

        if not matches:
            return (
                f"No indicators found matching '{indicator}'. "
                "Try a different search term."
            )

        # Use the first match's series_id
        indicator = matches[0].split(":")[0].strip()

    try:
        df = nasdaqdatalink.get_table(
            "WB/DATA",
            series_id=indicator,
            country_code=country,
        )

        if df.empty:
            return f"No data found for indicator '{indicator}' in country '{country}'."

        # Return the most recent data
        df = df.sort_values("year", ascending=False)

        # Format the response
        indicator_name = metadata.get(indicator, {}).get("name", indicator)
        most_recent = df.iloc[0]
        return {
            "indicator": indicator,
            "indicator_name": indicator_name,
            "country": country,
            "year": int(most_recent.get("year")),
            "value": float(most_recent.get("value")),
            "all_data": df[["year", "value"]].to_dict("records"),
        }
    except Exception as e:
        return f"Error fetching data for indicator '{indicator}': {e!s}"


def search_indicators(keyword: str) -> list[str]:
    """
    Search for indicator descriptions matching a given keyword.
    Returns a list of indicators matching the keyword.
    """
    metadata = load_indicator_metadata()
    keyword_lower = keyword.lower()
    matches = []

    for series_id, info in metadata.items():
        name = info.get("name", "")
        description = info.get("description", "")

        # Search in both name and description
        if (
            keyword_lower in name.lower()
            or keyword_lower in description.lower()
            or keyword_lower in series_id.lower()
        ):
            matches.append(f"{series_id}: {name} - {description}")

    # Return up to 10 matches
    return matches[:10]


def list_all_indicators() -> list[str]:
    """
    List all available indicator codes and descriptions.
    Returns a list of all World Bank indicators.
    """
    metadata = load_indicator_metadata()
    results = []

    for series_id, info in metadata.items():
        name = info.get("name", "")
        description = info.get("description", "")
        results.append(f"{series_id}: {name} - {description}")

    return results
