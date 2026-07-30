"""Phase 4 / U6 tests: the multi-word phonetic decoder."""

import sqlite3

import pytest

from nautical import eval as eval_service
from nautical.phonetics.align import Seg
from nautical.search.decoder import (
    _Transition,
    _position_transitions,
    find_multiword,
    rescore_cap,
    suffix_heuristic,
)
from nautical.search.normalize import broad_vowel, onset_keys


def _conn(db_path):
    return sqlite3.connect(db_path)


def _norm(phrase: str) -> str:
    return eval_service._normalize(phrase)


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
    # The decoder tiles `nautical` with real words. U6 surfaces the flagship
    # oronym `not a cult` (and close rivals); older `naughty`/`gnaw` forms may
    # still appear further down the ranking.
    results, _ = find_multiword("nautical", limit=25, conn=_conn(db_path))
    phrases = [r.phrase for r in results]
    tokens = {t for p in phrases for t in p.split()}
    assert (
        "cult" in tokens
        or "call" in tokens
        or "gnaw" in tokens
        or "naught" in tokens
        or "naughty" in tokens
    ), phrases


def test_multiword_stainless(db_path):
    # `stainless` should spell out as real two-word sequences like `stain less`.
    results, _ = find_multiword(
        "stainless", limit=50, beam_width=400, cand_per_pos=500, conn=_conn(db_path)
    )
    phrases = {r.phrase for r in results}
    assert any(" less" in p or " loss" in p for p in phrases)


def test_suffix_heuristic_backward_exact():
    """h[n]=0; h[i] is min remaining path cost on a tiny transition DAG."""
    dummy = Seg(ipa="x", stress="", is_vowel=False)
    tr = lambda length, cost: _Transition(
        word="w",
        frequency=1.0,
        quality=1.0,
        pos_tag="NN",
        length=length,
        cost=cost,
        segs=[dummy],
    )
    # Positions 0..3; cheapest path 0→1→3 costs 1+2=3; alternate 0→2→3 costs 5+1=6.
    transitions = [
        [tr(1, 1.0), tr(2, 5.0)],  # from 0
        [tr(2, 2.0)],  # from 1 → 3
        [tr(1, 1.0)],  # from 2 → 3
        [],  # from 3 (unused)
    ]
    h = suffix_heuristic(transitions, n=3)
    assert h[3] == 0.0
    assert h[2] == 1.0
    assert h[1] == 2.0
    assert h[0] == 3.0
    assert h[0] <= h[1] + 1.0
    assert h[0] <= h[2] + 5.0


def test_rescore_cap_independent_of_limit():
    assert rescore_cap(300) == max(10_000, 300 * 40)
    assert rescore_cap(300, thorough=True) == max(50_000, 300 * 40)
    # Cap does not take a limit argument — shrinking display limit must not
    # shrink search (regression guard vs old min(limit*50, ...)).
    assert rescore_cap(60) == 10_000


def test_stretch_two_emits_more_lengths_than_one(db_path):
    from nautical.pronounce import enriched_segments

    conn = _conn(db_path)
    try:
        target = enriched_segments("nautical", conn=conn)
        t1 = _position_transitions(
            conn, target, 0, cand_per_pos=500, strictness=0.5, skip_words=set(), stretch=1
        )
        t2 = _position_transitions(
            conn, target, 0, cand_per_pos=500, strictness=0.5, skip_words=set(), stretch=2
        )
    finally:
        conn.close()
    lens1 = {tr.length for tr in t1}
    lens2 = {tr.length for tr in t2}
    assert lens2 >= lens1
    assert max(lens2) - min(lens2) >= max(lens1) - min(lens1)


def _phrases_and_variants(results) -> list[str]:
    out: list[str] = []
    for r in results:
        out.append(_norm(r.phrase))
        out.extend(_norm(v) for v in r.variants)
    return out


def test_nautical_finds_not_a_cult_in_top_50(db_path):
    """U6 acceptance: flagship reverse oronym at product defaults."""
    results, _ = find_multiword(
        "nautical",
        limit=50,
        beam_width=300,
        cand_per_pos=1500,
        diversity=0.30,
        prefix_cap=3,
        conn=_conn(db_path),
    )
    found = _phrases_and_variants(results)
    assert "not a cult" in found, [r.phrase for r in results]


@pytest.mark.xfail(
    reason=(
        "Stretch goal: 'brainless' lexicon quality ~0.39 fails the multiword "
        "result quality floor, and 'acting' is often missing from onset "
        "retrieval for this target — track under thorough decode separately."
    ),
    strict=False,
)
def test_acting_brainless_under_thorough(db_path):
    """Stretch goal: acting brainless reachable under --thorough."""
    results, _ = find_multiword(
        "clean and stainless",
        limit=50,
        beam_width=300,
        cand_per_pos=1500,
        diversity=0.30,
        prefix_cap=3,
        thorough=True,
        conn=_conn(db_path),
    )
    found = _phrases_and_variants(results)
    assert "acting brainless" in found, [r.phrase for r in results]
