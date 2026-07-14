"""Articulatory feature vectors for our IPA segment inventory.

PanPhon supplies 24-dimensional articulatory feature vectors (values in
{-1, 0, 1}). A few of our segments are not single PanPhon segments, so we build
our own cached ``segment -> vector`` map:

* affricates ``tʃ`` / ``dʒ``  -> queried via the tie-bar forms ``t͡ʃ`` / ``d͡ʒ``
* diphthongs (``eɪ`` etc.)    -> PanPhon returns two vectors; we average them
  into a single slot (we keep one alignment slot per ARPAbet phone)
* r-colored ``ɝ`` / ``ɚ``     -> not in PanPhon; approximated as the average of
  ``ə`` and ``ɹ`` (documented approximation)

PanPhon is a feature source only; the distance/alignment logic lives elsewhere.
"""

from __future__ import annotations

from functools import lru_cache

import panphon

from ..phonology.arpabet import IPA_INVENTORY

NUM_FEATURES = 24

# Segments to query PanPhon under a different (tie-bar) spelling.
_TIE_BAR = {"tʃ": "t͡ʃ", "dʒ": "d͡ʒ"}

# Segments PanPhon lacks, approximated as the mean of these components.
_APPROX = {"ɝ": ("ə", "ɹ"), "ɚ": ("ə", "ɹ")}


@lru_cache(maxsize=1)
def _feature_table() -> panphon.FeatureTable:
    return panphon.FeatureTable()


def _mean(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(column) / n for column in zip(*vectors)]


def _lookup(segment: str) -> list[float] | None:
    """Resolve a segment to a single averaged feature vector, or None."""
    table = _feature_table()
    if segment in _APPROX:
        parts = [table.word_to_vector_list(s, numeric=True)[0] for s in _APPROX[segment]]
        return _mean(parts)
    query = _TIE_BAR.get(segment, segment)
    vectors = table.word_to_vector_list(query, numeric=True)
    if not vectors:
        return None
    return _mean(vectors) if len(vectors) > 1 else [float(x) for x in vectors[0]]


@lru_cache(maxsize=1)
def _vector_map() -> dict[str, list[float]]:
    vector_map: dict[str, list[float]] = {}
    for segment in IPA_INVENTORY:
        vector = _lookup(segment)
        if vector is None:
            raise ValueError(f"PanPhon has no features for inventory segment {segment!r}")
        vector_map[segment] = vector
    return vector_map


def feature_vector(segment: str) -> list[float] | None:
    """Return the feature vector for a segment (cached for the inventory)."""
    cached = _vector_map().get(segment)
    if cached is not None:
        return cached
    return _lookup(segment)  # segment outside our inventory (e.g. odd g2p output)


def feature_distance(a: str, b: str) -> float:
    """Normalized articulatory distance between two segments in ``[0, 1]``.

    0.0 for identical segments; 1.0 if either segment is unknown to PanPhon.
    """
    if a == b:
        return 0.0
    va, vb = feature_vector(a), feature_vector(b)
    if va is None or vb is None:
        return 1.0
    total = sum(abs(x - y) for x, y in zip(va, vb))
    return total / (2 * NUM_FEATURES)
