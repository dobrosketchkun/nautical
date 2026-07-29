"""Phase 7 tests: result-cache key behavior and dataclass round-trips."""

import sqlite3

import pytest

from nautical import cache as cache_service
from nautical.search import decoder as multiword_search
from nautical.search import words as word_search


@pytest.fixture
def cache_db(tmp_path):
    return tmp_path / "cache.db"


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_make_key_stable_and_normalized():
    k1 = cache_service.make_key("rhymes", "stainless", {"limit": 5})
    k2 = cache_service.make_key("rhymes", "  STAINLESS ", {"limit": 5})
    assert k1 == k2  # text is normalized (strip + lowercase)


def test_make_key_sensitive_to_params_and_kind():
    base = cache_service.make_key("rhymes", "stainless", {"limit": 5})
    assert base != cache_service.make_key("rhymes", "stainless", {"limit": 6})
    assert base != cache_service.make_key("multiword", "stainless", {"limit": 5})
    assert base != cache_service.make_key("rhymes", "painless", {"limit": 5})


def test_put_get_clear_roundtrip(cache_db):
    assert cache_service.cache_get("missing", db_path=cache_db) is None
    cache_service.cache_put("k", {"a": 1, "b": [1, 2, 3]}, db_path=cache_db)
    assert cache_service.cache_get("k", db_path=cache_db) == {"a": 1, "b": [1, 2, 3]}

    stats = cache_service.stats(db_path=cache_db)
    assert stats["rows"] == 1 and stats["size_bytes"] > 0

    removed = cache_service.clear(db_path=cache_db)
    assert removed == 1
    assert cache_service.cache_get("k", db_path=cache_db) is None


def test_rhyme_result_roundtrip_preserves_alignment(db_path, cache_db):
    conn = _conn(db_path)
    try:
        results, _ = word_search.find_rhymes("stainless", limit=5, conn=conn)
    finally:
        conn.close()
    assert results

    payload = [word_search._result_to_dict(r) for r in results]
    cache_service.cache_put("rhymes", payload, db_path=cache_db)
    restored = [
        word_search._result_from_dict(d)
        for d in cache_service.cache_get("rhymes", db_path=cache_db)
    ]

    assert [r.word for r in restored] == [r.word for r in results]
    for orig, back in zip(results, restored):
        assert back.similarity == pytest.approx(orig.similarity)
        assert back.rank_score == pytest.approx(orig.rank_score)
        assert back.boundary_surprise == pytest.approx(orig.boundary_surprise)
        assert back.ipa == orig.ipa
        assert back.variants == orig.variants
        assert back.alignment.total_cost == pytest.approx(orig.alignment.total_cost)
        assert back.alignment.pretty() == orig.alignment.pretty()


def test_multiword_result_roundtrip_preserves_chunks(db_path, cache_db):
    conn = _conn(db_path)
    try:
        results, _ = multiword_search.find_multiword(
            "stainless", limit=3, beam_width=40, cand_per_pos=60, conn=conn
        )
    finally:
        conn.close()
    assert results

    payload = [multiword_search._result_to_dict(r) for r in results]
    cache_service.cache_put("mw", payload, db_path=cache_db)
    restored = [
        multiword_search._result_from_dict(d)
        for d in cache_service.cache_get("mw", db_path=cache_db)
    ]

    assert [r.phrase for r in restored] == [r.phrase for r in results]
    for orig, back in zip(results, restored):
        assert back.score == pytest.approx(orig.score)
        assert back.boundary_surprise == pytest.approx(orig.boundary_surprise)
        assert back.variants == orig.variants
        assert back.scores.freq_naturalness == pytest.approx(orig.scores.freq_naturalness)
        assert back.scores.pos_plausibility == pytest.approx(orig.scores.pos_plausibility)
        assert back.scores.function_ok == pytest.approx(orig.scores.function_ok)
        assert back.alignment.pretty() == orig.alignment.pretty()
        assert [w for w, _ in back.chunks] == [w for w, _ in orig.chunks]
        for (_, a_back), (_, a_orig) in zip(back.chunks, orig.chunks):
            assert a_back.pretty() == a_orig.pretty()


def test_find_rhymes_deterministic(db_path):
    """Same query yields the same ranking (the property caching relies on)."""
    conn = _conn(db_path)
    try:
        first, _ = word_search.find_rhymes("stainless", limit=10, conn=conn)
        second, _ = word_search.find_rhymes("stainless", limit=10, conn=conn)
    finally:
        conn.close()
    assert [r.word for r in first] == [r.word for r in second]
    assert [round(r.similarity, 6) for r in first] == [
        round(r.similarity, 6) for r in second
    ]


def test_cache_key_changes_with_weights_hash(db_path):
    from nautical.scoring_weights import DEFAULT_WEIGHTS

    k1 = word_search.rhymes_cache_key(
        "stainless", 5, 100, 0.5, 0.5, False, weights=DEFAULT_WEIGHTS, db_path=db_path
    )
    k2 = word_search.rhymes_cache_key(
        "stainless",
        5,
        100,
        0.5,
        0.5,
        False,
        weights=DEFAULT_WEIGHTS.with_updates(stress_weight=0.99),
        db_path=db_path,
    )
    assert k1 != k2
