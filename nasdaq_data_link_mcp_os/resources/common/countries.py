from typing import TypeVar

import pycountry

CountryCode = TypeVar("CountryCode", bound=str)


def get_country_code(country_name: str) -> str:
    """
    Get the 3-letter ISO country code for a given country name.
    Searches through official country names and common names.
    """
    # Try exact match first
    try:
        country = pycountry.countries.lookup(country_name)
        return country.alpha_3
    except LookupError:
        # Try fuzzy search
        name_lower = country_name.lower()
        for country in pycountry.countries:
            if (
                name_lower in country.name.lower()
                or (
                    hasattr(country, "common_name")
                    and name_lower in country.common_name.lower()
                )
                or (
                    hasattr(country, "official_name")
                    and name_lower in country.official_name.lower()
                )
            ):
                return country.alpha_3

    return f"Unknown country: {country_name}"
