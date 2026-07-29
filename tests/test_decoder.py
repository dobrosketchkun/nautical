"""Phase 4 tests: the multi-word phonetic decoder."""

import sqlite3

from nautical.search.decoder import find_multiword
from nautical.search.normalize import broad_vowel, onset_keys


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_broad_vowel_bridges_slant_vowels():
    # The low/central vowels collapse so `not` (nɑt) and `nautical` (nɔt-) share
    # an onset class; consonants are returned unchanged.
    assert broad_vowel("ɑ") == broad_vowel("ɔ") == broad_vowel("ə")
    assert broad_vowel("k") == "k"


def test_onset_keys_slant_and_single_segment():
    # `nɑt` and `nɔt` must land on the same onset keys (slant vowel).
    assert onset_keys(["n", "ɑ"]) == onset_keys(["n", "ɔ"])
    # A single-segment word (`a` = ə) is retrievable at a position whose target
    # window is [ə, k]: its 1-segment key is present among the query keys.
    assert onset_keys(["ə"])[0] in onset_keys(["ə", "k"])


def test_multiword_structure(db_path):
    results, _ = find_multiword("nautical", limit=15, conn=_conn(db_path))
    assert results
    # Every result is a genuine multi-word tiling that is not the query itself.
    assert all(r.num_words >= 2 for r in results)
    assert all(r.phrase != "nautical" for r in results)
    # Ranked by descending blended score, with a populated alignment per word.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert r.ipa
        assert r.alignment.pairs
        assert 0.0 <= r.boundary_surprise <= 1.0
        assert len(r.chunks) == r.num_words
        assert all(alignment.pairs for _, alignment in r.chunks)


def test_multiword_distinct_ipa(db_path):
    """U1.1: each result row is a unique sound; variants hold alternate spellings."""
    results, _ = find_multiword("nautical", limit=20, conn=_conn(db_path))
    assert results
    assert len({r.ipa for r in results}) == len(results)
    for r in results:
        assert r.phrase not in r.variants
        assert r.variants == sorted(r.variants)
        assert len(r.variants) == len(set(r.variants))


def test_multiword_default_diversity_limits_prefix(db_path):
    """U1.2: defaults keep any first word to at most 3 of the top 20."""
    results, _ = find_multiword("nautical", limit=20, conn=_conn(db_path))
    assert results
    counts: dict[str, int] = {}
    for r in results:
        first = r.words[0]
        counts[first] = counts.get(first, 0) + 1
    assert all(n <= 3 for n in counts.values()), counts


def test_multiword_diversity_zero_is_pure_rank_order(db_path):
    """U1.2: --diversity 0 reproduces pure post-collapse rank order."""
    pure, _ = find_multiword(
        "nautical", limit=20, diversity=0.0, prefix_cap=0, conn=_conn(db_path)
    )
    also_pure, _ = find_multiword(
        "nautical", limit=20, diversity=0.0, prefix_cap=3, conn=_conn(db_path)
    )
    assert [r.phrase for r in pure] == [r.phrase for r in also_pure]
    diversified, _ = find_multiword("nautical", limit=20, conn=_conn(db_path))
    # Defaults should differ from the prefix-heavy pure order on this query.
    assert [r.phrase for r in diversified] != [r.phrase for r in pure]


def test_multiword_discovers_oronyms(db_path):
    # The decoder tiles `nautical` (nɔtəkəl) with real words: high-scoring results
    # include `naught`/`gnaw`/`naughty`-based sound-alikes (`naught a can`,
    # `gnaw to can`, `naughty can`). (The genuine close oronym `gnaw tickle` is
    # also generated but ranks low by frequency-naturalness; surfacing meaningful
    # phrases needs Phase 6 semantics - see docs/NOTES.md.)
    results, _ = find_multiword("nautical", limit=25, conn=_conn(db_path))
    phrases = [r.phrase for r in results]
    assert any(
        "gnaw" in p.split() or "naught" in p.split() or "naughty" in p.split()
        for p in phrases
    ), phrases


def test_multiword_stainless(db_path):
    # `stainless` should spell out as real two-word sequences like `stain less`.
    results, _ = find_multiword(
        "stainless", limit=50, beam_width=400, cand_per_pos=500, conn=_conn(db_path)
    )
    phrases = {r.phrase for r in results}
    assert any(" less" in p or " loss" in p for p in phrases)
