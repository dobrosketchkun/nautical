"""Phase 5 tests: tail anchoring and the anchor dial."""

import sqlite3

from nautical.phonetics.align import Seg
from nautical.phonetics.anchor import anchored_score, rhyme_tail
from nautical.pronounce import enriched_segments
from nautical.search.words import find_rhymes


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_rhyme_tail_stressed(db_path):
    segs = enriched_segments("stainless", conn=_conn(db_path))
    tail = "".join(s.ipa for s in rhyme_tail(segs))
    # steɪnləs -> tail from the stressed vowel eɪ to the end.
    assert tail == "eɪnləs", tail


def test_rhyme_tail_no_stress_fallback():
    # No segment carries stress -> fall back to the last vowel onward.
    segs = [
        Seg(ipa="k", stress="", is_vowel=False),
        Seg(ipa="ə", stress="", is_vowel=True),
        Seg(ipa="t", stress="", is_vowel=False),
    ]
    tail = "".join(s.ipa for s in rhyme_tail(segs))
    assert tail == "ət", tail


def test_rhyme_tail_no_vowel_fallback():
    segs = [Seg(ipa="s", stress="", is_vowel=False), Seg(ipa="t", stress="", is_vowel=False)]
    assert [s.ipa for s in rhyme_tail(segs)] == ["s", "t"]


def test_anchored_score_end_rhyme_high_tail(db_path):
    conn = _conn(db_path)
    target = enriched_segments("stainless", conn=conn)
    for word in ("painless", "brainless"):
        cand = enriched_segments(word, conn=conn)
        score = anchored_score(target, cand, anchor=1.0)
        assert score.tail_similarity > 0.95, (word, score.tail_similarity)


def test_anchored_score_onset_share_low_tail(db_path):
    conn = _conn(db_path)
    target = enriched_segments("stainless", conn=conn)
    # Shares the onset region but not the rhyme tail: much lower tail similarity
    # than the ~1.0 of a true -ainless rhyme.
    cand = enriched_segments("stampede", conn=conn)
    score = anchored_score(target, cand, anchor=1.0)
    assert score.tail_similarity < 0.7, score.tail_similarity


def test_find_rhymes_tail_anchor_ranks_end_rhymes(db_path):
    results, _ = find_rhymes("stainless", limit=8, anchor=1.0, conn=_conn(db_path))
    words = [r.word for r in results]
    assert "painless" in words, words
    assert "brainless" in words, words


def test_find_rhymes_phrase_tail_anchor(db_path):
    results, _ = find_rhymes("clean and stainless", limit=15, anchor=1.0, conn=_conn(db_path))
    words = [r.word for r in results]
    assert any(w.endswith("ainless") or w in {"painless", "brainless"} for w in words), (
        words
    )
