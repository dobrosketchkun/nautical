"""Shared, decomposed ranking model for word and phrase candidates.

The weights in this module are deliberately centralized and provisional. Phase 9
wires every search mode to the same score contract; calibrating the values
against a larger judged corpus is deferred.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights

# Back-compat aliases for the default weight set.
STRESS_WEIGHT = DEFAULT_WEIGHTS.stress_weight
BOUNDARY_WEIGHT = DEFAULT_WEIGHTS.boundary_weight
NATURALNESS_WEIGHT = DEFAULT_WEIGHTS.naturalness_weight
WORD_COUNT_PENALTY = DEFAULT_WEIGHTS.word_count_penalty


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


def rank_base(
    phonetic_similarity: float,
    stress_similarity: float,
    boundary_surprise: float,
    *,
    naturalness: float | None = None,
    num_words: int = 1,
    weights: ScoringWeights | None = None,
) -> float:
    """Return the provisional non-semantic ordering score.

    Multi-word results retain the Phase 4 naturalness and word-count terms.
    Stress and boundary movement are now real ranking signals in both modes.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    score = (
        phonetic_similarity
        + w.stress_weight * stress_similarity
        + w.boundary_weight * boundary_surprise
    )
    if naturalness is not None:
        score += w.naturalness_weight * naturalness
        score -= w.word_count_penalty * num_words
    return score


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
