"""High-level phonetic distance between two pieces of text.

Turns each side into enriched segments (via the pronunciation service), aligns
them with the lyric-weighted aligner, and reports a decomposed result: an
overall similarity, a stress similarity, and the alignment that explains it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import editdistance

from ..config import DB_PATH
from ..pronounce import enriched_segment_variants, enriched_segments
from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights
from .align import Alignment, Seg, align


@dataclass
class DistanceResult:
    text_a: str
    text_b: str
    ipa_a: str
    ipa_b: str
    similarity: float
    stress_similarity: float
    total_cost: float
    alignment: Alignment


def _stress_string(segments: list[Seg]) -> str:
    return "".join(s.stress or "0" for s in segments if s.is_vowel)


def _stress_similarity(a: str, b: str) -> float:
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - editdistance.eval(a, b) / longest


def score_segments(
    segs_a: list[Seg],
    segs_b: list[Seg],
    strictness: float = 0.5,
    word_boundary_leniency: bool = True,
    weights: ScoringWeights | None = None,
) -> tuple[float, float, Alignment]:
    """Align two segment sequences and return (similarity, stress_similarity, alignment).

    Shared by ``phonetic_distance`` and the search reranker so the similarity
    formula lives in one place.
    """
    alignment = align(
        segs_a,
        segs_b,
        strictness=strictness,
        word_boundary_leniency=word_boundary_leniency,
        weights=weights if weights is not None else DEFAULT_WEIGHTS,
    )
    columns = len(alignment.pairs) or 1
    similarity = max(0.0, 1.0 - alignment.total_cost / columns)
    stress_similarity = _stress_similarity(
        _stress_string(segs_a), _stress_string(segs_b)
    )
    return similarity, stress_similarity, alignment


def phonetic_distance(
    text_a: str,
    text_b: str,
    strictness: float = 0.5,
    word_boundary_leniency: bool = True,
    multi_variant: bool = True,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    weights: ScoringWeights | None = None,
) -> DistanceResult:
    """Compute the decomposed phonetic distance between two texts.

    When ``multi_variant`` is set, every pronunciation variant of each side is
    scored and the best-matching pair is reported (so an alternate pronunciation
    that rhymes better is not missed).
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        if multi_variant:
            variants_a = enriched_segment_variants(text_a, conn=conn)
            variants_b = enriched_segment_variants(text_b, conn=conn)
        else:
            variants_a = [enriched_segments(text_a, conn=conn)]
            variants_b = [enriched_segments(text_b, conn=conn)]
    finally:
        if own_conn:
            conn.close()

    best: tuple[float, float, Alignment, list[Seg], list[Seg]] | None = None
    for segs_a in variants_a:
        for segs_b in variants_b:
            similarity, stress_similarity, alignment = score_segments(
                segs_a,
                segs_b,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=weights,
            )
            if best is None or similarity > best[0]:
                best = (similarity, stress_similarity, alignment, segs_a, segs_b)

    if best is None:
        best = (0.0, 0.0, align([], []), [], [])
    similarity, stress_similarity, alignment, segs_a, segs_b = best

    return DistanceResult(
        text_a=text_a,
        text_b=text_b,
        ipa_a="".join(s.ipa for s in segs_a),
        ipa_b="".join(s.ipa for s in segs_b),
        similarity=similarity,
        stress_similarity=stress_similarity,
        total_cost=alignment.total_cost,
        alignment=alignment,
    )
