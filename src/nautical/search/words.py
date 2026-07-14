"""Single-word phonetic search: retrieve, rerank, rank."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..config import DB_PATH
from ..phonetics.align import Alignment
from ..phonetics.anchor import anchored_score, rhyme_tail, segs_from_stored
from ..pronounce import enriched_segments, tokenize
from .index import candidate_ids, tail_candidate_ids

# Backwards-compatible alias (decoder.py imports this name).
_segs_from_row = segs_from_stored


@dataclass
class RhymeResult:
    word: str
    similarity: float  # the anchored blend used for ranking
    full_similarity: float
    tail_similarity: float
    stress_similarity: float
    frequency: float
    syllable_count: int
    ipa: str
    alignment: Alignment


def find_rhymes(
    text: str,
    limit: int = 25,
    pool: int = 1500,
    strictness: float = 0.5,
    anchor: float = 0.5,
    include_self: bool = False,
    conn: sqlite3.Connection | None = None,
) -> list[RhymeResult]:
    """Return ranked single-word sound-alikes for ``text``.

    Two-stage: generous n-gram retrieval, then anchored rerank. The ``anchor``
    dial (0 = full-span, 1 = tail-anchored) blends whole-word and rhyme-tail
    similarity; when it favors the tail, the tail n-gram index is also queried so
    end-rhymes that share little else still enter the pool.
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
    try:
        target_segs = enriched_segments(text, conn=conn)
        if not target_segs:
            return []

        target_ipa = [s.ipa for s in target_segs]
        ids = set(candidate_ids(conn, target_ipa, pool))
        if anchor > 0.0:
            tail_ipa = [s.ipa for s in rhyme_tail(target_segs)]
            ids.update(tail_candidate_ids(conn, tail_ipa, pool))
        if not ids:
            return []

        id_list = list(ids)
        placeholders = ",".join("?" * len(id_list))
        rows = conn.execute(
            f"SELECT l.written_form, l.frequency, p.arpabet, p.ipa_segments, "
            f"p.ipa, p.syllable_count "
            f"FROM pronunciation p JOIN lexeme l ON l.id = p.lexeme_id "
            f"WHERE p.id IN ({placeholders})",
            id_list,
        ).fetchall()
    finally:
        if own_conn:
            conn.close()

    query_forms = {text.strip().lower(), *tokenize(text)}

    best: dict[str, RhymeResult] = {}
    for written_form, frequency, arpabet, ipa_segments, ipa, syllable_count in rows:
        if not include_self and written_form in query_forms:
            continue
        cand_segs = segs_from_stored(arpabet, ipa_segments)
        if not cand_segs:
            continue
        score = anchored_score(
            target_segs, cand_segs, anchor=anchor, strictness=strictness
        )
        existing = best.get(written_form)
        if existing is None or score.anchored_similarity > existing.similarity:
            best[written_form] = RhymeResult(
                word=written_form,
                similarity=score.anchored_similarity,
                full_similarity=score.full_similarity,
                tail_similarity=score.tail_similarity,
                stress_similarity=score.stress_similarity,
                frequency=frequency or 0.0,
                syllable_count=syllable_count or 0,
                ipa=ipa or "",
                alignment=score.full_alignment,
            )

    results = sorted(
        best.values(), key=lambda r: (r.similarity, r.frequency), reverse=True
    )
    return results[:limit]
