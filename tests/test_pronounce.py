"""Phase 1 tests: the pronunciation service (DB lookup + g2p fallback)."""

import sqlite3

import pytest

from nautical import pronounce


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_word_nautical(db_path):
    word = pronounce.pronounce_word("nautical", conn=_conn(db_path))
    assert word.primary is not None
    assert word.primary.source == "cmudict"
    # This CMUdict entry is N AO1 T AH0 K AH0 L -> both reduced vowels are schwa.
    assert word.primary.ipa == "nɔtəkəl"
    assert word.primary.syllable_count == 3


def test_phrase_boundary_free(db_path):
    phrase = pronounce.pronounce_phrase("not a cult", conn=_conn(db_path))
    assert phrase.boundary_free == "nɑtəkʌlt"
    assert len(phrase.tokens) == 3
    assert phrase.boundaries[0][0] == 0


def test_tokenize_punctuation():
    assert pronounce.tokenize("We're not a cult!") == ["we're", "not", "a", "cult"]


def test_oov_g2p(db_path):
    try:
        word = pronounce.pronounce_word("spifflicated", conn=_conn(db_path))
    except RuntimeError:
        pytest.skip("g2p_en unavailable (offline nltk data missing)")
    assert word.primary is not None
    assert word.primary.source == "g2p"
    assert word.primary.syllable_count >= 3


def test_enriched_segments_marks_word_final(db_path):
    segs = pronounce.enriched_segments("not a cult", conn=_conn(db_path))
    # The /t/ ending "not" is word-final even though it is mid-phrase.
    word_finals = [s for s in segs if s.word_final]
    assert len(word_finals) == 3  # one per token
    assert segs[-1].word_final


def test_enriched_segment_variants_multiple(db_path):
    # "read" has two CMUdict pronunciations (R IY D and R EH D).
    variants = pronounce.enriched_segment_variants("read", conn=_conn(db_path))
    assert len(variants) >= 2
    ipas = {"".join(s.ipa for s in v) for v in variants}
    assert len(ipas) >= 2


def test_enriched_segment_variants_phrase_capped(db_path):
    # A phrase still returns at least one full-segment list.
    variants = pronounce.enriched_segment_variants("not a cult", conn=_conn(db_path))
    assert variants and all(v for v in variants)
