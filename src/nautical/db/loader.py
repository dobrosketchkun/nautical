"""Build the SQLite lexicon from the offline data sources.

Reads CMUdict pronunciations and wordfreq frequencies and writes them into
`lexeme` and `pronunciation` tables, normalizing each ARPAbet pronunciation to
IPA (plus a stress pattern and syllable count) at build time so later phases can
index the phonetic representation directly.
"""

from __future__ import annotations

import sqlite3
import time
from importlib.resources import files
from pathlib import Path

from ..config import DB_PATH, SCHEMA_VERSION, ensure_data_dir
from ..data.sources import get_frequency, iter_lexemes
from ..phonology.arpabet import arpabet_to_ipa, stress_pattern, syllable_count
from ..search.index import segment_ngrams


def _load_schema(conn: sqlite3.Connection) -> None:
    schema_sql = (files("nautical.db") / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def _write_meta(conn: sqlite3.Connection) -> dict[str, int]:
    lexeme_count = conn.execute("SELECT COUNT(*) FROM lexeme").fetchone()[0]
    pron_count = conn.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    with_freq = conn.execute(
        "SELECT COUNT(*) FROM lexeme WHERE frequency > 0"
    ).fetchone()[0]
    ngram_count = conn.execute("SELECT COUNT(*) FROM phoneme_ngram").fetchone()[0]

    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lexeme_count": str(lexeme_count),
        "pronunciation_count": str(pron_count),
        "lexeme_with_frequency": str(with_freq),
        "phoneme_ngram_count": str(ngram_count),
    }
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", meta.items()
    )
    return {
        "lexeme_count": lexeme_count,
        "pronunciation_count": pron_count,
        "lexeme_with_frequency": with_freq,
        "phoneme_ngram_count": ngram_count,
    }


def _build_ngram_index(conn: sqlite3.Connection) -> None:
    """Populate phoneme_ngram from each pronunciation's IPA segments."""
    rows = conn.execute(
        "SELECT id, ipa_segments FROM pronunciation"
    ).fetchall()
    ngram_rows = []
    for pron_id, ipa_segments in rows:
        segments = ipa_segments.split(" ") if ipa_segments else []
        for gram in segment_ngrams(segments):
            ngram_rows.append((gram, pron_id))
    conn.executemany(
        "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        ngram_rows,
    )


def build_db(force: bool = False, db_path: Path | None = None) -> dict[str, int]:
    """Create the schema and ingest CMUdict + wordfreq into SQLite.

    Returns a dict of row counts. With ``force=True`` an existing database file
    is deleted and rebuilt from scratch.
    """
    db_path = Path(db_path) if db_path is not None else DB_PATH
    if db_path == DB_PATH:
        ensure_data_dir()
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    if force and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        _load_schema(conn)

        lexemes = list(iter_lexemes())

        conn.executemany(
            "INSERT OR IGNORE INTO lexeme(written_form, frequency) VALUES (?, ?)",
            ((word, get_frequency(word)) for word, _ in lexemes),
        )
        conn.commit()

        id_map = {
            form: lid
            for lid, form in conn.execute("SELECT id, written_form FROM lexeme")
        }

        pron_rows = []
        for word, pronunciations in lexemes:
            lexeme_id = id_map[word]
            for phones in pronunciations:
                ipa_segments = arpabet_to_ipa(phones)
                pron_rows.append(
                    (
                        lexeme_id,
                        " ".join(phones),
                        stress_pattern(phones),
                        syllable_count(phones),
                        "".join(ipa_segments),
                        " ".join(ipa_segments),
                        "cmudict",
                    )
                )

        conn.executemany(
            "INSERT INTO pronunciation"
            "(lexeme_id, arpabet, stress, syllable_count, ipa, ipa_segments, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            pron_rows,
        )
        conn.commit()

        _build_ngram_index(conn)

        stats = _write_meta(conn)
        conn.commit()
        return stats
    finally:
        conn.close()


def get_stats(db_path: Path | None = None) -> dict[str, str]:
    """Read counts and metadata from an existing database."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(db_path)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()

    meta["db_size_bytes"] = str(db_path.stat().st_size)
    meta["db_path"] = str(db_path)
    return meta
