"""Seeded random search over ScoringWeights (U3).

Optimizes ``MRR_positives - λ * negative_leak_rate`` on the eval corpus.
Larger trial budgets benefit from U4 performance work; defaults are modest.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import eval as eval_service
from .scoring_weights import DEFAULT_WEIGHTS, ScoringWeights, save_weights

NEGATIVE_LEAK_LAMBDA = 0.5

# Tunable subset: rank + plausibility + align vowel multipliers.
# Gap bases stay frozen initially to keep the search space tractable.
TUNE_BOUNDS: dict[str, tuple[float, float]] = {
    "stress_weight": (0.0, 0.35),
    "boundary_weight": (0.0, 0.35),
    "naturalness_weight": (0.1, 0.6),
    "word_count_penalty": (0.0, 0.15),
    "vowel_stressed_mult": (1.0, 2.5),
    "vowel_unstressed_mult": (0.1, 0.8),
    "freq_geom_weight": (0.15, 0.6),
    "pos_plaus_weight": (0.15, 0.6),
    "function_ok_weight": (0.05, 0.35),
    "closed_frac_threshold": (0.5, 0.9),
}


@dataclass
class TuneTrial:
    weights: ScoringWeights
    objective: float
    mrr: float
    negative_leak_rate: float
    hit_rate: float


@dataclass
class TuneReport:
    baseline: TuneTrial
    best: TuneTrial
    trials: list[TuneTrial]
    seed: int
    improved: bool


def objective_score(report: eval_service.EvalReport, *, leak_lambda: float = NEGATIVE_LEAK_LAMBDA) -> float:
    return report.mrr - leak_lambda * report.negative_leak_rate


def _sample_weights(rng: random.Random, base: ScoringWeights) -> ScoringWeights:
    updates: dict[str, float] = {}
    for name, (lo, hi) in TUNE_BOUNDS.items():
        updates[name] = rng.uniform(lo, hi)
    # Renormalize plausibility blend to sum ≈ 1.
    fg = updates["freq_geom_weight"]
    pp = updates["pos_plaus_weight"]
    fo = updates["function_ok_weight"]
    total = fg + pp + fo
    if total > 0:
        updates["freq_geom_weight"] = fg / total
        updates["pos_plaus_weight"] = pp / total
        updates["function_ok_weight"] = fo / total
    return base.with_updates(**updates)


def _evaluate_weights(
    weights: ScoringWeights,
    pairs: list[dict],
    *,
    limit: int,
    use_cache: bool,
    conn: sqlite3.Connection | None,
    vectors,
    db_path: Path | None,
    cache_db_path: Path | None,
    include_diversity: bool,
) -> TuneTrial:
    report = eval_service.run_eval(
        pairs,
        limit=limit,
        use_cache=use_cache,
        conn=conn,
        vectors=vectors,
        db_path=db_path,
        cache_db_path=cache_db_path,
        weights=weights,
        include_diversity=include_diversity,
    )
    return TuneTrial(
        weights=weights,
        objective=objective_score(report),
        mrr=report.mrr,
        negative_leak_rate=report.negative_leak_rate,
        hit_rate=report.hit_rate,
    )


def run_tune(
    *,
    pairs: list[dict] | None = None,
    trials: int = 40,
    seed: int = 0,
    limit: int = 50,
    use_cache: bool = True,
    base: ScoringWeights | None = None,
    conn: sqlite3.Connection | None = None,
    vectors=None,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
    include_diversity: bool = False,
    subset: int | None = None,
) -> TuneReport:
    """Random-search ``trials`` configurations; return baseline vs best."""
    corpus = list(pairs) if pairs is not None else eval_service.load_pairs()
    if subset is not None and subset > 0:
        corpus = corpus[:subset]
    weights0 = base if base is not None else DEFAULT_WEIGHTS
    rng = random.Random(seed)

    baseline = _evaluate_weights(
        weights0,
        corpus,
        limit=limit,
        use_cache=use_cache,
        conn=conn,
        vectors=vectors,
        db_path=db_path,
        cache_db_path=cache_db_path,
        include_diversity=include_diversity,
    )
    best = baseline
    recorded: list[TuneTrial] = [baseline]

    for _ in range(max(0, trials)):
        candidate = _sample_weights(rng, weights0)
        trial = _evaluate_weights(
            candidate,
            corpus,
            limit=limit,
            use_cache=use_cache,
            conn=conn,
            vectors=vectors,
            db_path=db_path,
            cache_db_path=cache_db_path,
            include_diversity=include_diversity,
        )
        recorded.append(trial)
        if trial.objective > best.objective:
            best = trial

    return TuneReport(
        baseline=baseline,
        best=best,
        trials=recorded,
        seed=seed,
        improved=best.objective > baseline.objective,
    )


def write_best(report: TuneReport, path: str | Path) -> Path:
    """Persist the best weights from a tune run."""
    return save_weights(report.best.weights, path)
