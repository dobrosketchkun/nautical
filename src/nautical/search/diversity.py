"""Presentation-layer diversity for multi-word results.

MMR-style word-overlap selection plus an optional per-first-word cap. This does
not change ``rank_score``; it only chooses which ranked candidates to show.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _HasWords(Protocol):
    words: list[str]


def word_overlap_distance(a: Sequence[str], b: Sequence[str]) -> float:
    """Return ``1 - |set(a) ∩ set(b)| / max(len(a), len(b))`` (0 = identical)."""
    if not a and not b:
        return 0.0
    denom = max(len(a), len(b))
    if denom == 0:
        return 0.0
    overlap = len(set(a) & set(b))
    return 1.0 - overlap / denom


def select_diverse(
    results: Sequence[_HasWords],
    *,
    limit: int,
    diversity: float,
    prefix_cap: int,
) -> list:
    """Admit ranked candidates under MMR distance and an optional prefix cap.

    ``diversity <= 0`` returns ``results[:limit]`` unchanged (pure rank order).
    When ``diversity > 0``, a candidate is admitted only if its minimum
    word-overlap distance to already-selected rows is ``>= diversity`` and
    (when ``prefix_cap > 0``) its first word has not already been used
    ``prefix_cap`` times.
    """
    if limit <= 0:
        return []
    if diversity <= 0:
        return list(results[:limit])

    selected: list = []
    prefix_counts: dict[str, int] = {}
    for candidate in results:
        if len(selected) >= limit:
            break
        words = candidate.words
        if not words:
            continue
        first = words[0]
        if prefix_cap > 0 and prefix_counts.get(first, 0) >= prefix_cap:
            continue
        if selected:
            min_dist = min(
                word_overlap_distance(words, s.words) for s in selected
            )
            if min_dist < diversity:
                continue
        selected.append(candidate)
        prefix_counts[first] = prefix_counts.get(first, 0) + 1
    return selected
