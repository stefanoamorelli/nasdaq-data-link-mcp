import os
from dotenv import load_dotenv
import nasdaqdatalink


def initialize_api():
    """Initialize the Nasdaq Data Link API configuration"""
    load_dotenv()

    api_key = os.getenv("NASDAQ_DATA_LINK_API_KEY")
    if not api_key:
        raise ValueError("NASDAQ_DATA_LINK_API_KEY environment variable is not set.")

    # Set the API key directly on the module
    nasdaqdatalink.read_key(api_key)
