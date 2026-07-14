"""Theme reranking: bias phonetic results toward a verse/theme via GloVe.

Given a set of theme terms (e.g. ``"ocean, sea, ship"``) we build a single
theme vector and score each candidate's semantic fit against it. The fit is kept
as a separate, decomposed signal (``theme_fit`` in ``[-1, 1]``) and blended with
the phonetic ``similarity`` only for ranking; the two numbers are never merged
into one opaque score in the output.
"""

from __future__ import annotations

from typing import Sequence, TypeVar

import numpy as np

from .vectors import Vectors

T = TypeVar("T")


def parse_terms(text: str) -> list[str]:
    """Split a comma/whitespace-separated term string into clean tokens."""
    raw = text.replace(",", " ").split()
    return [t.strip().lower() for t in raw if t.strip()]


def _phrase_vector(words: Sequence[str], vectors: Vectors) -> np.ndarray | None:
    """Mean of the resolvable member-word vectors (renormalized)."""
    vecs = [v for v in (vectors.get(w) for w in words) if v is not None]
    if not vecs:
        return None
    mean = np.mean(np.vstack(vecs), axis=0)
    norm = np.linalg.norm(mean)
    return mean / norm if norm else mean


def _result_words(result: object) -> list[str]:
    """Extract the word(s) of a RhymeResult or MultiwordResult."""
    words = getattr(result, "words", None)
    if words:
        return list(words)
    word = getattr(result, "word", None)
    return [word] if word else []


def apply_theme(
    results: list[T],
    theme_terms: list[str],
    vectors: Vectors,
    weight: float = 0.5,
    min_theme: float | None = None,
) -> list[T]:
    """Set ``theme_fit`` on each result and re-rank by a phonetic/theme blend.

    ``rank = (1 - weight) * similarity + weight * (theme_fit + 1) / 2``. Results
    whose ``theme_fit`` is below ``min_theme`` (when given) are dropped. Results
    with no resolvable words get ``theme_fit = 0.0`` and are ranked on phonetics.
    """
    theme_vec = vectors.term_vector(theme_terms)
    if theme_vec is None:
        return results

    kept: list[T] = []
    for result in results:
        phrase_vec = _phrase_vector(_result_words(result), vectors)
        fit = float(np.dot(phrase_vec, theme_vec)) if phrase_vec is not None else 0.0
        result.theme_fit = fit  # type: ignore[attr-defined]
        if min_theme is not None and fit < min_theme:
            continue
        kept.append(result)

    kept.sort(
        key=lambda r: (1.0 - weight) * r.similarity  # type: ignore[attr-defined]
        + weight * (r.theme_fit + 1.0) / 2.0,  # type: ignore[attr-defined]
        reverse=True,
    )
    return kept
