"""U4 performance: feature table, align_cost parity, equivalence, latency."""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from nautical.phonetics.align import Seg, align, align_cost
from nautical.phonetics.features import (
    _distance_from_vectors,
    _vector_map,
    feature_distance,
)
from nautical.phonology.arpabet import IPA_INVENTORY
from nautical.search.decoder import find_multiword
from nautical.search.words import find_rhymes


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_pairwise_table_matches_vector_formula():
    vectors = _vector_map()
    segments = sorted(IPA_INVENTORY)
    for a in segments:
        for b in segments:
            expected = (
                0.0
                if a == b
                else _distance_from_vectors(vectors[a], vectors[b])
            )
            assert feature_distance(a, b) == pytest.approx(expected)


def _random_seg(rng: random.Random) -> Seg:
    ipa = rng.choice(sorted(IPA_INVENTORY))
    is_vowel = ipa in {"ə", "ɚ", "ɝ", "ɑ", "æ", "ʌ", "ɔ", "ɛ", "ɪ", "ʊ", "i", "u", "eɪ", "aɪ", "ɔɪ", "aʊ", "oʊ"}
    return Seg(
        ipa=ipa,
        stress=rng.choice(["0", "1", "2"]) if is_vowel else "",
        is_vowel=is_vowel,
        word_final=rng.random() < 0.2,
    )


def test_align_cost_matches_align_total():
    rng = random.Random(42)
    for _ in range(40):
        n, m = rng.randint(1, 6), rng.randint(1, 6)
        a = [_random_seg(rng) for _ in range(n)]
        b = [_random_seg(rng) for _ in range(m)]
        strictness = rng.choice([0.0, 0.5, 1.0])
        leniency = rng.choice([True, False])
        full = align(a, b, strictness=strictness, word_boundary_leniency=leniency)
        cost = align_cost(a, b, strictness=strictness, word_boundary_leniency=leniency)
        assert cost == pytest.approx(full.total_cost)


def test_empty_align_cost_is_zero():
    assert align_cost([], []) == 0.0
    assert align([], []).total_cost == 0.0


def test_search_equivalence_cost_only_vs_full_path(db_path):
    """Production (cost-only beam) matches full-align beam on fixed queries."""
    import nautical.search.decoder as decoder

    conn = _conn(db_path)
    try:
        decoder._FORCE_FULL_ALIGN_TRANSITIONS = False
        fast, _ = find_multiword(
            "nautical",
            limit=10,
            beam_width=60,
            cand_per_pos=400,
            diversity=0.0,
            prefix_cap=0,
            conn=conn,
        )
        decoder._FORCE_FULL_ALIGN_TRANSITIONS = True
        full, _ = find_multiword(
            "nautical",
            limit=10,
            beam_width=60,
            cand_per_pos=400,
            diversity=0.0,
            prefix_cap=0,
            conn=conn,
        )
    finally:
        decoder._FORCE_FULL_ALIGN_TRANSITIONS = False
        conn.close()

    assert [r.phrase for r in fast] == [r.phrase for r in full]
    for a, b in zip(fast, full):
        assert a.rank_score == pytest.approx(b.rank_score, abs=1e-9)
        assert a.similarity == pytest.approx(b.similarity, abs=1e-9)


@pytest.mark.slow
def test_cold_latency_budgets(db_path):
    conn = _conn(db_path)
    try:
        # Warm feature table / POS LM once outside the timed window.
        find_rhymes("a", limit=1, conn=conn)
        find_multiword("a", limit=1, beam_width=20, cand_per_pos=50, conn=conn)

        t0 = time.perf_counter()
        find_rhymes("stainless", limit=25, pool=1500, conn=conn)
        single_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        find_multiword(
            "nautical",
            limit=25,
            beam_width=60,
            cand_per_pos=1500,
            diversity=0.0,
            prefix_cap=0,
            conn=conn,
        )
        multi_s = time.perf_counter() - t0
    finally:
        conn.close()

    assert single_s < 1.0, f"single-word cold {single_s:.2f}s"
    assert multi_s < 2.0, f"multiword cold {multi_s:.2f}s"
