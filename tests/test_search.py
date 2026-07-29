"""Phase 3 tests: single-word phonetic search."""

import sqlite3

from nautical.search.index import segment_ngrams
from nautical.search.words import find_rhymes


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_segment_ngrams_bi_and_tri():
    grams = segment_ngrams(["n", "ɔ", "t", "ə"])
    # bigrams: nɔ, ɔt, tə ; trigrams: nɔt, ɔtə
    assert len(grams) == 5
    assert "\u001f".join(["n", "ɔ"]) in grams
    assert "\u001f".join(["n", "ɔ", "t"]) in grams


def test_segment_ngrams_short_fallback():
    # A single-segment sequence is still emitted so it is searchable.
    assert segment_ngrams(["a"]) == ["a"]
    assert segment_ngrams([]) == []


def test_not_a_cult_finds_nautical(db_path):
    # A boundary-free whole-phrase echo, so it surfaces under full-span anchoring
    # (tail anchoring instead favors words ending in the -ult rhyme).
    results = find_rhymes("not a cult", limit=15, anchor=0.0, conn=_conn(db_path))
    words = [r.word for r in results]
    assert "nautical" in words, words


def test_stainless_finds_rhymes(db_path):
    results = find_rhymes("stainless", limit=200, conn=_conn(db_path))
    words = [r.word for r in results]
    assert "brainless" in words, words
    assert "painless" in words, words
    # The query word itself is excluded by default.
    assert "stainless" not in words


def test_results_sorted_and_alignment_present(db_path):
    results = find_rhymes("stainless", limit=20, conn=_conn(db_path))
    assert results
    sims = [r.similarity for r in results]
    assert sims == sorted(sims, reverse=True)
    assert all(r.alignment is not None and r.alignment.pairs for r in results)


def test_include_self(db_path):
    results = find_rhymes("stainless", limit=50, include_self=True, conn=_conn(db_path))
    assert "stainless" in [r.word for r in results]


def test_rhymes_distinct_ipa(db_path):
    """U1.1: exact homophones collapse onto one IPA row with variants retained."""
    results = find_rhymes("stainless", limit=25, conn=_conn(db_path))
    assert results
    assert len({r.ipa for r in results}) == len(results)
    for r in results:
        assert r.word not in r.variants
        assert r.variants == sorted(r.variants)
        assert len(r.variants) == len(set(r.variants))
