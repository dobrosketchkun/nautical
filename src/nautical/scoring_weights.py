"""Externalized scoring / alignment weights (U3 + U2).

Defaults match the calibrated module constants. A JSON file in the
data directory (or ``--weights``) can override them without editing source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

WEIGHTS_FILENAME = "scoring_weights.json"


@dataclass(frozen=True)
class ScoringWeights:
    """Every provisional constant that affects ranking or alignment cost."""

    # Convex rank_base weights (renormalized at use; multi defaults sum to 1)
    phonetic_weight: float = 0.45
    stress_weight: float = 0.10
    boundary_weight: float = 0.10
    naturalness_weight: float = 0.25
    compactness_weight: float = 0.10
    theme_weight_default: float = 0.5

    # Hybrid similarity: cost / (columns * unrelated_cost_per_col)
    # Measured mean unrelated cost/col ≈ 0.24; 0.30 keeps unrelated sim < 0.4.
    unrelated_cost_per_col: float = 0.30

    # Alignment substitution / gap / strictness
    vowel_stressed_mult: float = 1.6
    vowel_unstressed_mult: float = 0.35
    gap_unstressed_vowel: float = 0.3
    gap_cheap_consonant: float = 0.4
    gap_stressed_vowel: float = 1.1
    gap_other: float = 0.9
    strictness_base: float = 0.6
    strictness_span: float = 0.8

    # Phrase plausibility blend (U1.4)
    freq_geom_weight: float = 0.40
    pos_plaus_weight: float = 0.45
    function_ok_weight: float = 0.15
    closed_frac_threshold: float = 2.0 / 3.0

    # Query inventory gate
    min_quality: float = 0.35

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoringWeights":
        known = {f.name for f in fields(cls)}
        cleaned = {k: float(v) for k, v in data.items() if k in known}
        # Pre-U2 JSON used word_count_penalty; map to compactness_weight.
        if "compactness_weight" not in cleaned and "word_count_penalty" in data:
            cleaned["compactness_weight"] = float(data["word_count_penalty"])
        return cls(**cleaned)

    def weights_hash(self) -> str:
        """Stable short digest for cache keys."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    def with_updates(self, **kwargs: float) -> "ScoringWeights":
        return replace(self, **kwargs)


DEFAULT_WEIGHTS = ScoringWeights()


def load_weights(path: str | Path | None = None) -> ScoringWeights:
    """Load weights from JSON, or return defaults if path is missing/absent."""
    if path is None:
        return DEFAULT_WEIGHTS
    file_path = Path(path)
    if not file_path.is_file():
        return DEFAULT_WEIGHTS
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Weights file must be a JSON object: {file_path}")
    return ScoringWeights.from_dict(data)


def resolve_weights(
    data_dir: str | Path | None = None,
    weights_path: str | Path | None = None,
    weights: ScoringWeights | None = None,
) -> ScoringWeights:
    """Explicit object → path → ``{data_dir}/scoring_weights.json`` → defaults."""
    if weights is not None:
        return weights
    if weights_path is not None:
        return load_weights(weights_path)
    if data_dir is not None:
        return load_weights(Path(data_dir) / WEIGHTS_FILENAME)
    return DEFAULT_WEIGHTS


def save_weights(weights: ScoringWeights, path: str | Path) -> Path:
    """Write weights JSON (pretty-printed) and return the path."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(weights.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return file_path
