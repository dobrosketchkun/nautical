"""Nautical - offline phonetic rhyme discovery workbench."""

from .client import Nautical, SearchResponse
from .errors import NauticalError, NotInitializedError
from .phonetics.distance import DistanceResult
from .pronounce import PhrasePronunciation
from .search.decoder import MultiwordResult
from .search.ranking import ScoreComponents
from .search.words import RhymeResult
from .semantics.vectors import VectorsUnavailable

__version__ = "0.0.1"

__all__ = [
    "DistanceResult",
    "MultiwordResult",
    "Nautical",
    "NauticalError",
    "NotInitializedError",
    "PhrasePronunciation",
    "RhymeResult",
    "ScoreComponents",
    "SearchResponse",
    "VectorsUnavailable",
    "__version__",
]
