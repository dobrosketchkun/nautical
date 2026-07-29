"""Shared, decomposed ranking model for word and phrase candidates.

U2: ``rank_base`` is a convex combination (weights renormalized to sum to 1)
so ``rank_score`` stays in ``[0, 1]``. Calibrate magnitudes via U3 ``nautical tune``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights

# Back-compat aliases for the default weight set.
STRESS_WEIGHT = DEFAULT_WEIGHTS.stress_weight
BOUNDARY_WEIGHT = DEFAULT_WEIGHTS.boundary_weight
NATURALNESS_WEIGHT = DEFAULT_WEIGHTS.naturalness_weight
COMPACTNESS_WEIGHT = DEFAULT_WEIGHTS.compactness_weight
PHONETIC_WEIGHT = DEFAULT_WEIGHTS.phonetic_weight
# Legacy name kept for imports that still expect it.
WORD_COUNT_PENALTY = DEFAULT_WEIGHTS.compactness_weight


@dataclass
class ScoreComponents:
    """Named signals plus the explicit score used to order a candidate."""

    phonetic_similarity: float
    full_similarity: float
    tail_similarity: float
    stress_similarity: float
    boundary_surprise: float = 0.0
    naturalness: float | None = None
    freq_naturalness: float | None = None
    pos_plausibility: float | None = None
    function_ok: float | None = None
    theme_fit: float | None = None
    base_score: float = 0.0
    rank_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreComponents":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _renormalize(parts: list[tuple[float, float]]) -> float:
    """Weighted sum of ``(weight, value)`` pairs after renormalizing weights to 1."""
    total_w = sum(max(0.0, w) for w, _ in parts)
    if total_w <= 0.0:
        # Degenerate: equal blend of the values that were supplied.
        if not parts:
            return 0.0
        return sum(v for _, v in parts) / len(parts)
    return sum(max(0.0, w) * v for w, v in parts) / total_w


def rank_base(
    phonetic_similarity: float,
    stress_similarity: float,
    boundary_surprise: float,
    *,
    naturalness: float | None = None,
    num_words: int = 1,
    weights: ScoringWeights | None = None,
) -> float:
    """Return a convex ordering score in ``[0, 1]``.

    Single-word (no naturalness): blend of phonetic / stress / boundary.
    Multi-word: those plus naturalness and compactness ``1/num_words``.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    if naturalness is None:
        return _renormalize(
            [
                (w.phonetic_weight, phonetic_similarity),
                (w.stress_weight, stress_similarity),
                (w.boundary_weight, boundary_surprise),
            ]
        )
    compactness = 1.0 / max(num_words, 1)
    return _renormalize(
        [
            (w.phonetic_weight, phonetic_similarity),
            (w.stress_weight, stress_similarity),
            (w.boundary_weight, boundary_surprise),
            (w.naturalness_weight, naturalness),
            (w.compactness_weight, compactness),
        ]
    )


def apply_context_score(base_score: float, theme_fit: float, weight: float) -> float:
    """Blend semantic context with the complete base score.

    Unlike the pre-Phase-9 formula, this preserves stress, boundary surprise,
    naturalness, and the word-count penalty already present in ``base_score``.
    """
    bounded_weight = max(0.0, min(1.0, weight))
    normalized_theme = (theme_fit + 1.0) / 2.0
    return (1.0 - bounded_weight) * base_score + bounded_weight * normalized_theme


def display_sort_key(frequency: float, form: str) -> tuple:
    """Lower is better: higher frequency, then shorter spelling, then alphabetical."""
    return (-frequency, len(form), form)


def merge_variant_forms(primary: str, *groups: list[str] | tuple[str, ...] | str) -> list[str]:
    """Return sorted alternate spellings/phrases, excluding ``primary``."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        items = (group,) if isinstance(group, str) else group
        for item in items:
            if item != primary and item not in seen:
                seen.add(item)
                out.append(item)
    return sorted(out)
