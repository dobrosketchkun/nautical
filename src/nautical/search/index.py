"""Phoneme n-gram index: generous candidate retrieval.

Words are indexed by the bigrams and trigrams of their IPA segment sequence
(stress-insensitive). At query time the target's n-grams are matched against the
index and candidates are ranked by how many n-grams they share; the precise
(and expensive) alignment reranking happens afterwards on this small pool.
"""

from __future__ import annotations

import sqlite3


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


def _overlap_ids(
    conn: sqlite3.Connection, table: str, target_segments: list[str], pool: int
) -> list[int]:
    grams = segment_ngrams(target_segments)
    if not grams:
        return []
    placeholders = ",".join("?" * len(grams))
    rows = conn.execute(
        f"SELECT pronunciation_id, COUNT(*) AS overlap "
        f"FROM {table} WHERE ngram IN ({placeholders}) "
        f"GROUP BY pronunciation_id ORDER BY overlap DESC LIMIT ?",
        (*grams, pool),
    ).fetchall()
    return [row[0] for row in rows]


def candidate_ids(
    conn: sqlite3.Connection, target_segments: list[str], pool: int
) -> list[int]:
    """Return up to ``pool`` pronunciation ids ranked by full n-gram overlap."""
    return _overlap_ids(conn, "phoneme_ngram", target_segments, pool)


def tail_candidate_ids(
    conn: sqlite3.Connection, target_tail_segments: list[str], pool: int
) -> list[int]:
    """Return up to ``pool`` pronunciation ids ranked by rhyme-tail overlap."""
    return _overlap_ids(conn, "rhyme_ngram", target_tail_segments, pool)
