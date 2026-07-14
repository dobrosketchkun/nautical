"""High-level phonetic distance between two pieces of text.

Turns each side into enriched segments (via the pronunciation service), aligns
them with the lyric-weighted aligner, and reports a decomposed result: an
overall similarity, a stress similarity, and the alignment that explains it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import editdistance

from ..config import DB_PATH
from ..pronounce import enriched_segments
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


def phonetic_distance(
    text_a: str,
    text_b: str,
    strictness: float = 0.5,
    conn: sqlite3.Connection | None = None,
) -> DistanceResult:
    """Compute the decomposed phonetic distance between two texts."""
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
    try:
        segs_a = enriched_segments(text_a, conn=conn)
        segs_b = enriched_segments(text_b, conn=conn)
    finally:
        if own_conn:
            conn.close()

    alignment = align(segs_a, segs_b, strictness=strictness)
    columns = len(alignment.pairs) or 1
    similarity = max(0.0, 1.0 - alignment.total_cost / columns)

    return DistanceResult(
        text_a=text_a,
        text_b=text_b,
        ipa_a="".join(s.ipa for s in segs_a),
        ipa_b="".join(s.ipa for s in segs_b),
        similarity=similarity,
        stress_similarity=_stress_similarity(
            _stress_string(segs_a), _stress_string(segs_b)
        ),
        total_cost=alignment.total_cost,
        alignment=alignment,
    )
