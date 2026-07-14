"""Project paths and constants.

Paths are resolved relative to the repository root, which works with an
editable install (`pip install -e .`) since the source stays in place.
"""

from pathlib import Path

# src/nautical/config.py -> parents[2] is the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "nautical.db"

SCHEMA_VERSION = "2"


def ensure_data_dir() -> Path:
    """Create the data directory if it does not exist and return it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
