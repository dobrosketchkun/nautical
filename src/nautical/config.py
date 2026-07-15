"""Project paths and constants.

Paths are resolved relative to the repository root, which works with an
editable install (`pip install -e .`) since the source stays in place.
"""

from pathlib import Path

# src/nautical/config.py -> parents[2] is the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "nautical.db"
# Query-result cache; a separate file so it survives `db build` and needs no
# SCHEMA_VERSION bump. Rebuildable, gitignored under data/.
CACHE_DB_PATH = DATA_DIR / "cache.db"

SCHEMA_VERSION = "5"

# --- Semantic vectors (GloVe 6B) ---------------------------------------------
# The raw text file and the filtered/normalized cache live here. Both are under
# the gitignored data/ dir and are rebuildable (auto-downloaded on first use).
VECTORS_DIR = DATA_DIR / "vectors"
GLOVE_DIM = 300
GLOVE_RAW = VECTORS_DIR / f"glove.6B.{GLOVE_DIM}d.txt"
GLOVE_MATRIX = VECTORS_DIR / f"glove.6B.{GLOVE_DIM}d.filtered.npy"
GLOVE_VOCAB = VECTORS_DIR / f"glove.6B.{GLOVE_DIM}d.vocab.txt"

# The zip bundles all dimensions (50/100/200/300d); we extract only the one we
# use. Primary is Stanford; the HuggingFace mirror is a fallback if it is down.
GLOVE_ZIP_URLS = (
    "https://nlp.stanford.edu/data/glove.6B.zip",
    "https://huggingface.co/stanfordnlp/glove/resolve/main/glove.6B.zip",
)


def ensure_data_dir() -> Path:
    """Create the data directory if it does not exist and return it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def ensure_vectors_dir() -> Path:
    """Create the vectors directory if it does not exist and return it."""
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    return VECTORS_DIR
