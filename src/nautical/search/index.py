"""Phoneme n-gram index: generous candidate retrieval.

Words are indexed by the bigrams and trigrams of their IPA segment sequence
(stress-insensitive). At query time the target's rarest n-grams are scored with
a length-normalized IDF sum over shared grams (binary TF after build-time
dedupe); the precise (and expensive) alignment reranking happens afterwards on
this pool.
"""

from __future__ import annotations

import math
import sqlite3

from ..phonetics.align import Seg
from ..phonetics.anchor import stress_skeleton_key

# Length-normalization epsilon in score = Σ idf / (ε + log(1 + doc_ngram_count)).
_LENGTH_EPS = 0.5
# Cap query grams to the rarest K so common n-grams do not flood the pool.
_MAX_QUERY_GRAMS = 6


def segment_ngrams(segments: list[str], min_n: int = 2, max_n: int = 3) -> list[str]:
    """Return the n-grams (default bigrams + trigrams) of a segment sequence.

    For sequences shorter than ``min_n`` the whole sequence is emitted as a
    single gram so nothing is left unindexed/unsearchable.
    """
    if not segments:
        return []
    if len(segments) < min_n:
        return ["\u001f".join(segments)]

    grams: list[str] = []
    for n in range(min_n, max_n + 1):
        for i in range(len(segments) - n + 1):
            grams.append("\u001f".join(segments[i : i + n]))
    return grams


def _ensure_ln(conn: sqlite3.Connection) -> None:
    """Register natural log; stock SQLite often lacks math functions on Windows."""
    conn.create_function("_nautical_ln", 1, math.log, deterministic=True)


def _query_grams(
    conn: sqlite3.Connection, kind: str, target_segments: list[str]
) -> list[str]:
    """Distinct query n-grams, preferring the rarest by stored IDF."""
    grams = list(dict.fromkeys(segment_ngrams(target_segments)))
    if not grams:
        return []
    placeholders = ",".join("?" * len(grams))
    rows = conn.execute(
        f"SELECT ngram, idf FROM ngram_df WHERE kind = ? AND ngram IN ({placeholders})",
        (kind, *grams),
    ).fetchall()
    if not rows:
        return grams
    rows.sort(key=lambda r: r[1], reverse=True)
    return [ngram for ngram, _ in rows[:_MAX_QUERY_GRAMS]]


def _scored_ids(
    conn: sqlite3.Connection,
    table: str,
    kind: str,
    count_column: str,
    target_segments: list[str],
    pool: int,
) -> list[int]:
    """Rank pronunciations by length-normalized IDF over shared n-grams."""
    grams = _query_grams(conn, kind, target_segments)
    if not grams or pool <= 0:
        return []
    _ensure_ln(conn)
    placeholders = ",".join("?" * len(grams))
    rows = conn.execute(
        f"""
        SELECT t.pronunciation_id AS pronunciation_id,
               SUM(d.idf) / ({_LENGTH_EPS} + _nautical_ln(1.0 + p.{count_column}))
                   AS score
        FROM {table} AS t
        JOIN ngram_df AS d ON d.kind = ? AND d.ngram = t.ngram
        JOIN pronunciation AS p ON p.id = t.pronunciation_id
        WHERE t.ngram IN ({placeholders})
        GROUP BY t.pronunciation_id
        ORDER BY score DESC
        LIMIT ?
        """,
        (kind, *grams, pool),
    ).fetchall()
    return [row[0] for row in rows]


def candidate_ids(
    conn: sqlite3.Connection, target_segments: list[str], pool: int
) -> list[int]:
    """Return up to ``pool`` pronunciation ids ranked by full-form IDF score."""
    return _scored_ids(
        conn, "phoneme_ngram", "full", "ngram_count", target_segments, pool
    )


def tail_candidate_ids(
    conn: sqlite3.Connection, target_tail_segments: list[str], pool: int
) -> list[int]:
    """Return up to ``pool`` pronunciation ids ranked by rhyme-tail IDF score."""
    return _scored_ids(
        conn, "rhyme_ngram", "rhyme", "rhyme_ngram_count", target_tail_segments, pool
    )


def skeleton_candidate_ids(
    conn: sqlite3.Connection, target_segs: list[Seg], pool: int
) -> list[int]:
    """Return up to ``pool`` ids sharing the query's stressed-vowel skeleton."""
    key = stress_skeleton_key(target_segs)
    if not key or pool <= 0:
        return []
    rows = conn.execute(
        """
        SELECT s.pronunciation_id
        FROM stress_skeleton AS s
        JOIN pronunciation AS p ON p.id = s.pronunciation_id
        JOIN lexeme AS l ON l.id = p.lexeme_id
        WHERE s.skeleton = ?
        ORDER BY l.frequency DESC, s.pronunciation_id
        LIMIT ?
        """,
        (key, pool),
    ).fetchall()
    return [row[0] for row in rows]
