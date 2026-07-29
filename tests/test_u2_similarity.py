"""U2 similarity contract: span, rank bounds, mode parity."""

from __future__ import annotations

import sqlite3

import pytest

from nautical.phonetics.distance import score_segments
from nautical.pronounce import enriched_segments
from nautical.search.decoder import find_multiword
from nautical.search.words import find_rhymes


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_rank_score_bounded_single_and_multi(db_path):
    conn = _conn(db_path)
    try:
        singles, _ = find_rhymes("stainless", limit=20, conn=conn)
        multis, _ = find_multiword(
            "nautical",
            limit=20,
            beam_width=60,
            cand_per_pos=400,
            diversity=0.0,
            prefix_cap=0,
            conn=conn,
        )
    finally:
        conn.close()

    assert singles and multis
    for r in singles:
        assert 0.0 <= r.rank_score <= 1.0
        assert 0.0 <= r.similarity <= 1.0
    for r in multis:
        assert 0.0 <= r.rank_score <= 1.0
        assert 0.0 <= r.similarity <= 1.0


def test_similarity_span_not_compressed(db_path):
    conn = _conn(db_path)
    try:
        results, _ = find_rhymes("stainless", limit=20, conn=conn)
    finally:
        conn.close()
    sims = [r.similarity for r in results]
    assert max(sims) - min(sims) >= 0.15, sims


def test_decoder_full_sim_matches_score_segments(db_path):
    """Reported full_similarity uses the shared score_segments formula."""
    conn = _conn(db_path)
    try:
        results, _ = find_multiword(
            "nautical",
            limit=5,
            beam_width=60,
            cand_per_pos=400,
            diversity=0.0,
            prefix_cap=0,
            conn=conn,
        )
        target = enriched_segments("nautical", conn=conn)
        assert results
        top = results[0]
        # Rebuild candidate segs from IPA by re-scoring alignment path cost.
        # Prefer: full_similarity == score_segments(target, stored segs from chunks).
        from nautical.phonetics.align import Seg

        segs: list[Seg] = []
        for _, alignment in top.chunks:
            for pair in alignment.pairs:
                if pair.src is not None:
                    segs.append(pair.src)
        sim, _, _ = score_segments(target, segs)
        assert top.scores.full_similarity == pytest.approx(sim, abs=1e-9)
    finally:
        conn.close()
