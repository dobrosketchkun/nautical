"""Phase 0 smoke test: build the DB and verify it holds real data."""

import sqlite3

from nautical.db import loader


def test_build_and_counts(tmp_path):
    db_path = tmp_path / "test_nautical.db"
    stats = loader.build_db(force=True, db_path=db_path)

    assert stats["lexeme_count"] > 100_000
    assert stats["pronunciation_count"] > 100_000
    assert stats["lexeme_with_frequency"] > 0

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT p.arpabet, p.syllable_count "
            "FROM pronunciation p JOIN lexeme l ON l.id = p.lexeme_id "
            "WHERE l.written_form = ?",
            ("nautical",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "expected 'nautical' to be present in CMUdict"
    arpabet, syllables = row
    assert "AO" in arpabet or "AA" in arpabet
    assert syllables == 3


def test_stats_roundtrip(tmp_path):
    db_path = tmp_path / "test_nautical.db"
    loader.build_db(force=True, db_path=db_path)
    info = loader.get_stats(db_path=db_path)
    assert info["schema_version"] == "2"
    assert int(info["lexeme_count"]) > 100_000
