"""U1.3 tests: lexicon quality flags, score, and query gating."""

import sqlite3

import pytest

from nautical.db.quality import (
    DEFAULT_MIN_QUALITY,
    compute_quality,
    is_abbrev,
    is_possessive,
    is_propn_tag,
    variant_loser_ids,
    zipf_base,
)
from nautical.search.decoder import find_multiword
from nautical.search.words import find_rhymes


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_possessive_and_abbrev_rules():
    assert is_possessive("stanley's")
    assert is_possessive("s'")
    assert not is_possessive("stanley")
    assert is_abbrev("cm")
    assert is_abbrev("nth")
    assert is_abbrev("a1")
    assert is_abbrev("mr.")
    assert not is_abbrev("by")
    assert not is_abbrev("cult")


def test_zipf_base_and_quality_monotonic():
    assert zipf_base(0.0) == 0.0
    assert zipf_base(7.0) == 1.0
    assert compute_quality(6.0, is_possessive_flag=False, is_abbrev_flag=False,
                           is_propn_flag=False, is_variant_flag=False) > compute_quality(
        3.0, is_possessive_flag=False, is_abbrev_flag=False,
        is_propn_flag=False, is_variant_flag=False
    )
    base = compute_quality(
        4.0, is_possessive_flag=False, is_abbrev_flag=False,
        is_propn_flag=False, is_variant_flag=False,
    )
    assert compute_quality(
        4.0, is_possessive_flag=False, is_abbrev_flag=False,
        is_propn_flag=False, is_variant_flag=True,
    ) < base


def test_propn_rule_skips_high_zipf_false_positives():
    assert is_propn_tag("NNP", 1.5)
    assert not is_propn_tag("NNP", 2.75)  # e.g. title-cased "brainless"
    assert not is_propn_tag("NNP", 4.0)  # e.g. title-cased "cult"
    assert not is_propn_tag("NNP", 6.1)  # e.g. title-cased "know"
    assert not is_propn_tag("NN", 1.5)


def test_variant_loser_ids_marks_non_winners():
    groups = [
        (
            "noʊ",
            [
                (1, 6.3, "no"),
                (2, 6.1, "know"),
                (3, 2.8, "noe"),
            ],
        )
    ]
    assert variant_loser_ids(groups) == {2, 3}


def test_build_assigns_quality_columns(db_path):
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT zipf, pos_tag, is_variant, quality FROM lexeme "
            "WHERE written_form = ?",
            ("noe",),
        ).fetchone()
        assert row is not None
        zipf, pos_tag, is_variant, quality = row
        assert pos_tag
        assert is_variant == 1
        assert quality < DEFAULT_MIN_QUALITY

        good = conn.execute(
            "SELECT quality FROM lexeme WHERE written_form = ?", ("no",)
        ).fetchone()
        assert good is not None
        assert good[0] >= DEFAULT_MIN_QUALITY

        cult = conn.execute(
            "SELECT quality FROM lexeme WHERE written_form = ?", ("cult",)
        ).fetchone()
        assert cult is not None
        assert cult[0] >= DEFAULT_MIN_QUALITY

        stelljes = conn.execute(
            "SELECT quality, zipf FROM lexeme WHERE written_form = ?",
            ("stelljes",),
        ).fetchone()
        if stelljes is not None:
            assert stelljes[0] < DEFAULT_MIN_QUALITY
    finally:
        conn.close()


def test_multiword_default_quality_drops_junk_spellings(db_path):
    junk = {"noe", "noh", "nau", "stelljes"}
    results, _ = find_multiword("nautical", limit=20, conn=_conn(db_path))
    assert results
    tokens = {w for r in results for w in r.words}
    assert tokens.isdisjoint(junk)
    assert all(r.quality >= DEFAULT_MIN_QUALITY for r in results)


def test_multiword_quality_zero_admits_junk_inventory(db_path):
    """At --quality 0, junk spellings are in the decode inventory (SQL gate open)."""
    junk = ("noe", "noh", "nau", "stelljes")
    conn = _conn(db_path)
    try:
        for form in junk:
            row = conn.execute(
                "SELECT quality FROM lexeme WHERE written_form = ?", (form,)
            ).fetchone()
            if row is None:
                continue
            assert row[0] < DEFAULT_MIN_QUALITY
            admitted = conn.execute(
                "SELECT 1 FROM pronunciation p "
                "JOIN lexeme l ON l.id = p.lexeme_id "
                "WHERE l.written_form = ? AND l.quality >= 0 LIMIT 1",
                (form,),
            ).fetchone()
            assert admitted is not None
            blocked = conn.execute(
                "SELECT 1 FROM pronunciation p "
                "JOIN lexeme l ON l.id = p.lexeme_id "
                "WHERE l.written_form = ? AND l.quality >= ? LIMIT 1",
                (form, DEFAULT_MIN_QUALITY),
            ).fetchone()
            assert blocked is None
    finally:
        conn.close()


def test_single_word_respects_min_quality(db_path):
    default, _ = find_rhymes("no", limit=50, conn=_conn(db_path))
    words_default = {r.word for r in default}
    assert "noe" not in words_default
    open_pool, _ = find_rhymes("no", limit=100, min_quality=0.0, conn=_conn(db_path))
    words_open = {r.word for r in open_pool}
    # At quality 0, a junk homophone of "no" should be admissible somewhere.
    assert words_open & {"noe", "noh", "nau"} or any(
        r.quality < DEFAULT_MIN_QUALITY for r in open_pool
    )
