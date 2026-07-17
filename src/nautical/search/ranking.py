"""Shared, decomposed ranking model for word and phrase candidates.

The weights in this module are deliberately centralized and provisional. Phase 9
wires every search mode to the same score contract; calibrating the values
against a larger judged corpus is deferred.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


STRESS_WEIGHT = 0.10
BOUNDARY_WEIGHT = 0.10
NATURALNESS_WEIGHT = 0.35
WORD_COUNT_PENALTY = 0.05


@dataclass
class ScoreComponents:
    """Named signals plus the explicit score used to order a candidate."""

    phonetic_similarity: float
    full_similarity: float
    tail_similarity: float
    stress_similarity: float
    boundary_surprise: float = 0.0
    naturalness: float | None = None
    theme_fit: float | None = None
    base_score: float = 0.0
    rank_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreComponents":
        return cls(**data)


def rank_base(
    phonetic_similarity: float,
    stress_similarity: float,
    boundary_surprise: float,
    *,
    naturalness: float | None = None,
    num_words: int = 1,
) -> float:
    """Return the provisional non-semantic ordering score.

    Multi-word results retain the Phase 4 naturalness and word-count terms.
    Stress and boundary movement are now real ranking signals in both modes.
    """
    score = (
        phonetic_similarity
        + STRESS_WEIGHT * stress_similarity
        + BOUNDARY_WEIGHT * boundary_surprise
    )
    if naturalness is not None:
        score += NATURALNESS_WEIGHT * naturalness
        score -= WORD_COUNT_PENALTY * num_words
    return score


def apply_context_score(base_score: float, theme_fit: float, weight: float) -> float:
    """Blend semantic context with the complete base score.

    Unlike the pre-Phase-9 formula, this preserves stress, boundary surprise,
    naturalness, and the word-count penalty already present in ``base_score``.
    """
    bounded_weight = max(0.0, min(1.0, weight))
    normalized_theme = (theme_fit + 1.0) / 2.0
    return (1.0 - bounded_weight) * base_score + bounded_weight * normalized_theme
