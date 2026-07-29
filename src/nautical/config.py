"""Runtime path resolution for editable checkouts and installed wheels."""

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

SCHEMA_VERSION = "7"
GLOVE_DIM = 300

# The zip bundles all dimensions (50/100/200/300d); we extract only the one we
# use. Primary is Stanford; the HuggingFace mirror is a fallback if it is down.
GLOVE_ZIP_URLS = (
    "https://nlp.stanford.edu/data/glove.6B.zip",
    "https://huggingface.co/stanfordnlp/glove/resolve/main/glove.6B.zip",
)


def _source_checkout_root() -> Path | None:
    """Return the repository root when imported from a ``src`` checkout."""
    candidate = Path(__file__).resolve().parents[2]
    package_dir = candidate / "src" / "nautical"
    if (candidate / "pyproject.toml").is_file() and package_dir.is_dir():
        return candidate
    return None


@dataclass(frozen=True)
class NauticalPaths:
    """All mutable runtime artifacts derived from one data directory."""

    data_dir: Path
    db_path: Path
    cache_db_path: Path
    exclude_path: Path
    vectors_dir: Path
    glove_zip: Path
    glove_raw: Path
    glove_matrix: Path
    glove_vocab: Path

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "NauticalPaths":
        root = Path(data_dir).expanduser().resolve()
        vectors = root / "vectors"
        stem = f"glove.6B.{GLOVE_DIM}d"
        return cls(
            data_dir=root,
            db_path=root / "nautical.db",
            cache_db_path=root / "cache.db",
            exclude_path=root / "exclude.txt",
            vectors_dir=vectors,
            glove_zip=vectors / "glove.6B.zip",
            glove_raw=vectors / f"{stem}.txt",
            glove_matrix=vectors / f"{stem}.npy",
            glove_vocab=vectors / f"{stem}.vocab.txt",
        )

    @classmethod
    def resolve(cls, data_dir: str | Path | None = None) -> "NauticalPaths":
        """Resolve explicit → environment → source checkout → user-data path."""
        if data_dir is not None:
            return cls.from_data_dir(data_dir)
        env_dir = os.environ.get("NAUTICAL_DATA_DIR")
        if env_dir:
            return cls.from_data_dir(env_dir)
        checkout = _source_checkout_root()
        if checkout is not None:
            return cls.from_data_dir(checkout / "data")
        return cls.from_data_dir(user_data_dir("nautical", appauthor=False))

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def ensure_vectors_dir(self) -> Path:
        self.vectors_dir.mkdir(parents=True, exist_ok=True)
        return self.vectors_dir


SOURCE_CHECKOUT_ROOT = _source_checkout_root()
PROJECT_ROOT = SOURCE_CHECKOUT_ROOT or Path(__file__).resolve().parent
DEFAULT_PATHS = NauticalPaths.resolve()

# Backwards-compatible aliases used by low-level functions.
DATA_DIR = DEFAULT_PATHS.data_dir
DB_PATH = DEFAULT_PATHS.db_path
CACHE_DB_PATH = DEFAULT_PATHS.cache_db_path
EXCLUDE_PATH = DEFAULT_PATHS.exclude_path
VECTORS_DIR = DEFAULT_PATHS.vectors_dir
GLOVE_RAW = DEFAULT_PATHS.glove_raw
GLOVE_MATRIX = DEFAULT_PATHS.glove_matrix
GLOVE_VOCAB = DEFAULT_PATHS.glove_vocab


def ensure_data_dir() -> Path:
    """Create the data directory if it does not exist and return it."""
    return DEFAULT_PATHS.ensure_data_dir()


def ensure_vectors_dir() -> Path:
    """Create the vectors directory if it does not exist and return it."""
    return DEFAULT_PATHS.ensure_vectors_dir()
