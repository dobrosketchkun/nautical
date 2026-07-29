"""Build the SQLite lexicon from the offline data sources.

Reads CMUdict pronunciations and wordfreq frequencies and writes them into
`lexeme` and `pronunciation` tables, normalizing each ARPAbet pronunciation to
IPA (plus a stress pattern and syllable count) at build time so later phases can
index the phonetic representation directly. Also computes lexicon quality
signals (zipf, POS, string flags, IPA-variant, derived quality) once at build.
"""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from importlib.resources import files
from pathlib import Path

from ..config import DB_PATH, SCHEMA_VERSION, ensure_data_dir
from ..data.sources import get_frequency, get_zipf, iter_lexemes
from ..phonetics.anchor import rhyme_tail, segs_from_stored
from ..phonology.arpabet import arpabet_to_ipa, stress_pattern, syllable_count
from ..search.index import segment_ngrams
from ..search.normalize import onset_keys
from ..search.plausibility import write_pos_lm
from .quality import (
    DEFAULT_MIN_QUALITY,
    batch_pos_tag,
    compute_quality,
    is_abbrev,
    is_possessive,
    is_propn_tag,
    variant_loser_ids,
)


def _load_schema(conn: sqlite3.Connection) -> None:
    schema_sql = (files("nautical.db") / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def _write_meta(conn: sqlite3.Connection) -> dict[str, int]:
    lexeme_count = conn.execute("SELECT COUNT(*) FROM lexeme").fetchone()[0]
    pron_count = conn.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    with_freq = conn.execute(
        "SELECT COUNT(*) FROM lexeme WHERE frequency > 0"
    ).fetchone()[0]
    quality_ge = conn.execute(
        "SELECT COUNT(*) FROM lexeme WHERE quality >= ?",
        (DEFAULT_MIN_QUALITY,),
    ).fetchone()[0]
    mean_quality = conn.execute("SELECT AVG(quality) FROM lexeme").fetchone()[0] or 0.0
    ngram_count = conn.execute("SELECT COUNT(*) FROM phoneme_ngram").fetchone()[0]
    onset_count = conn.execute("SELECT COUNT(*) FROM decode_onset").fetchone()[0]
    rhyme_count = conn.execute("SELECT COUNT(*) FROM rhyme_ngram").fetchone()[0]
    pos_lm_count = conn.execute("SELECT COUNT(*) FROM pos_lm").fetchone()[0]
    pos_lm_tri = conn.execute(
        "SELECT COUNT(*) FROM pos_lm WHERE order_n = 3"
    ).fetchone()[0]

    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lexeme_count": str(lexeme_count),
        "pronunciation_count": str(pron_count),
        "lexeme_with_frequency": str(with_freq),
        "lexeme_quality_ge_default": str(quality_ge),
        "lexeme_mean_quality": f"{mean_quality:.4f}",
        "phoneme_ngram_count": str(ngram_count),
        "decode_onset_count": str(onset_count),
        "rhyme_ngram_count": str(rhyme_count),
        "pos_lm_count": str(pos_lm_count),
        "pos_lm_trigrams": str(pos_lm_tri),
        "pos_lm_source": "treebank",
    }
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", meta.items()
    )
    return {
        "lexeme_count": lexeme_count,
        "pronunciation_count": pron_count,
        "lexeme_with_frequency": with_freq,
        "lexeme_quality_ge_default": quality_ge,
        "phoneme_ngram_count": ngram_count,
        "decode_onset_count": onset_count,
        "rhyme_ngram_count": rhyme_count,
        "pos_lm_trigrams": pos_lm_tri,
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


def _build_rhyme_index(conn: sqlite3.Connection) -> None:
    """Populate rhyme_ngram from each pronunciation's rhyme tail.

    The tail (last stressed vowel to end) is derived with the same helpers used
    at query time, so retrieval and scoring agree on where the rhyme begins.
    """
    rows = conn.execute(
        "SELECT id, arpabet, ipa_segments FROM pronunciation"
    ).fetchall()
    rhyme_rows = []
    for pron_id, arpabet, ipa_segments in rows:
        segs = segs_from_stored(arpabet, ipa_segments)
        tail = [s.ipa for s in rhyme_tail(segs)]
        for gram in segment_ngrams(tail):
            rhyme_rows.append((gram, pron_id))
    conn.executemany(
        "INSERT INTO rhyme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        rhyme_rows,
    )


def _build_decode_index(conn: sqlite3.Connection) -> None:
    """Populate decode_onset for every pronunciation.

    Admission is gated at query time by ``lexeme.quality >= min_quality``, so
    ``--quality 0`` can reopen the full inventory.
    """
    rows = conn.execute("SELECT id, ipa_segments FROM pronunciation").fetchall()
    onset_rows = []
    for pron_id, ipa_segments in rows:
        segments = ipa_segments.split(" ") if ipa_segments else []
        for key in onset_keys(segments):
            onset_rows.append((key, pron_id))
    conn.executemany(
        "INSERT INTO decode_onset(onset_key, pronunciation_id) VALUES (?, ?)",
        onset_rows,
    )


def _annotate_quality(conn: sqlite3.Connection) -> None:
    """Fill quality columns on every lexeme (flags, POS, variants, score)."""
    rows = conn.execute(
        "SELECT id, written_form, zipf FROM lexeme ORDER BY id"
    ).fetchall()
    if not rows:
        return

    ids = [row[0] for row in rows]
    forms = [row[1] for row in rows]
    zipfs = [float(row[2] or 0.0) for row in rows]

    possessive = [1 if is_possessive(form) else 0 for form in forms]
    abbrev = [1 if is_abbrev(form) else 0 for form in forms]

    lower_tags = batch_pos_tag(forms)
    title_forms = [form[:1].upper() + form[1:] if form else form for form in forms]
    title_tags = batch_pos_tag(title_forms)
    propn = [
        1 if is_propn_tag(title_tag, zipf) else 0
        for title_tag, zipf in zip(title_tags, zipfs)
    ]

    ipa_groups: dict[str, list[tuple[int, float, str]]] = defaultdict(list)
    for lexeme_id, zipf, form, ipa in conn.execute(
        "SELECT l.id, l.zipf, l.written_form, p.ipa "
        "FROM pronunciation p JOIN lexeme l ON l.id = p.lexeme_id "
        "WHERE p.ipa IS NOT NULL AND p.ipa != ''"
    ):
        ipa_groups[ipa].append((lexeme_id, float(zipf or 0.0), form))
    losers = variant_loser_ids(ipa_groups.items())
    variant = [1 if lid in losers else 0 for lid in ids]

    updates = []
    for i, lexeme_id in enumerate(ids):
        quality = compute_quality(
            zipfs[i],
            is_possessive_flag=bool(possessive[i]),
            is_abbrev_flag=bool(abbrev[i]),
            is_propn_flag=bool(propn[i]),
            is_variant_flag=bool(variant[i]),
        )
        updates.append(
            (
                lower_tags[i],
                possessive[i],
                abbrev[i],
                propn[i],
                variant[i],
                quality,
                lexeme_id,
            )
        )

    conn.executemany(
        "UPDATE lexeme SET pos_tag = ?, is_possessive = ?, is_abbrev = ?, "
        "is_propn = ?, is_variant = ?, quality = ? WHERE id = ?",
        updates,
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
            "INSERT OR IGNORE INTO lexeme(written_form, frequency, zipf) "
            "VALUES (?, ?, ?)",
            ((word, get_frequency(word), get_zipf(word)) for word, _ in lexemes),
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

        _annotate_quality(conn)
        conn.commit()

        write_pos_lm(conn)
        conn.commit()

        _build_ngram_index(conn)
        _build_rhyme_index(conn)
        _build_decode_index(conn)

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
