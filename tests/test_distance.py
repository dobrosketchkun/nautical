"""Phase 2 / U2 tests: high-level phonetic distance."""

import sqlite3

import pytest

from nautical.phonetics.distance import (
    phonetic_distance,
    score_segments,
    similarity_from_alignment,
)
from nautical.pronounce import enriched_segments


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_high_vs_low(db_path):
    high = phonetic_distance("not a cult", "nautical", conn=_conn(db_path))
    low = phonetic_distance("not a cult", "electric", conn=_conn(db_path))
    assert high.similarity > low.similarity
    assert low.similarity < 0.4


def test_unrelated_pairs_below_threshold(db_path):
    conn = _conn(db_path)
    for a, b in (
        ("not a cult", "electric"),
        ("stainless", "banana"),
        ("nautical", "keyboard"),
    ):
        assert phonetic_distance(a, b, conn=conn).similarity < 0.4, (a, b)


def test_near_identical_above_threshold(db_path):
    conn = _conn(db_path)
    assert phonetic_distance("nautical", "nautical", conn=conn).similarity > 0.9
    assert phonetic_distance("read", "red", conn=conn).similarity > 0.9


def test_identical_is_one(db_path):
    result = phonetic_distance("nautical", "nautical", conn=_conn(db_path))
    assert result.similarity == 1.0
    assert result.total_cost == 0.0


def test_final_t_deletion(db_path):
    result = phonetic_distance("not a cult", "nautical", conn=_conn(db_path))
    last = result.alignment.pairs[-1]
    assert last.op == "del"
    assert last.src is not None and last.src.ipa == "t"


def test_strictness_monotonic(db_path):
    lenient = phonetic_distance(
        "not a cult", "nautical", strictness=0.1, conn=_conn(db_path)
    )
    strict = phonetic_distance(
        "not a cult", "nautical", strictness=0.9, conn=_conn(db_path)
    )
    assert lenient.similarity >= strict.similarity


def test_multi_variant_never_worse_than_primary(db_path):
    # "read" has an R EH D variant that matches "red" exactly; multi-variant must
    # be at least as good as primary-only.
    multi = phonetic_distance(
        "read", "red", multi_variant=True, conn=_conn(db_path)
    )
    primary = phonetic_distance(
        "read", "red", multi_variant=False, conn=_conn(db_path)
    )
    assert multi.similarity >= primary.similarity


def test_strict_boundaries_not_higher_than_lenient(db_path):
    lenient = phonetic_distance(
        "not a cult", "nautical", word_boundary_leniency=True, conn=_conn(db_path)
    )
    strict = phonetic_distance(
        "not a cult", "nautical", word_boundary_leniency=False, conn=_conn(db_path)
    )
    assert lenient.similarity >= strict.similarity


def test_similarity_from_alignment_matches_score_segments(db_path):
    conn = _conn(db_path)
    a = enriched_segments("nautical", conn=conn)
    b = enriched_segments("not a cult", conn=conn)
    sim, _, alignment = score_segments(a, b)
    assert sim == pytest.approx(similarity_from_alignment(alignment))
