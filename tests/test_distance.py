"""Phase 2 tests: high-level phonetic distance."""

import sqlite3

from nautical.phonetics.distance import phonetic_distance


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_high_vs_low(db_path):
    high = phonetic_distance("not a cult", "nautical", conn=_conn(db_path))
    low = phonetic_distance("not a cult", "electric", conn=_conn(db_path))
    assert high.similarity > 0.8
    assert high.similarity > low.similarity


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
