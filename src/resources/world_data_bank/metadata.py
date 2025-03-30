import csv
from typing import Dict

DEFAULT_METADATA_PATH = "src/resources/world_data_bank/metadata/metadata.csv"


def load_indicator_metadata(filepath=DEFAULT_METADATA_PATH) -> Dict[str, str]:
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
