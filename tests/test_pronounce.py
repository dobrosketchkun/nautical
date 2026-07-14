"""Phase 1 tests: the pronunciation service (DB lookup + g2p fallback)."""

import sqlite3

import pytest

from nautical import pronounce
from nautical.db import loader


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "nautical.db"
    loader.build_db(force=True, db_path=path)
    return path


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
