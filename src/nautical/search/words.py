"""Single-word phonetic search: retrieve, rerank, rank."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..config import DB_PATH
from ..phonetics.align import Alignment, Seg
from ..phonetics.distance import score_segments
from ..phonology.arpabet import is_vowel
from ..pronounce import enriched_segments, tokenize
from .index import candidate_ids


@dataclass
class RhymeResult:
    word: str
    similarity: float
    stress_similarity: float
    frequency: float
    syllable_count: int
    ipa: str
    alignment: Alignment


def _segs_from_row(arpabet: str, ipa_segments: str) -> list[Seg]:
    """Rebuild enriched segments from a stored pronunciation row."""
    phones = arpabet.split(" ") if arpabet else []
    segments = ipa_segments.split(" ") if ipa_segments else []
    result: list[Seg] = []
    for phone, ipa_segment in zip(phones, segments):
        stress = phone[-1] if phone and phone[-1].isdigit() else ""
        result.append(Seg(ipa=ipa_segment, stress=stress, is_vowel=is_vowel(phone)))
    return result


def find_rhymes(
    text: str,
    limit: int = 25,
    pool: int = 1500,
    strictness: float = 0.5,
    include_self: bool = False,
    conn: sqlite3.Connection | None = None,
) -> list[RhymeResult]:
    """Return ranked single-word sound-alikes for ``text``.

    Two-stage: generous phoneme n-gram retrieval, then precise alignment rerank.
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
    try:
        target_segs = enriched_segments(text, conn=conn)
        if not target_segs:
            return []

        target_ipa = [s.ipa for s in target_segs]
        ids = candidate_ids(conn, target_ipa, pool)
        if not ids:
            return []

        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT l.written_form, l.frequency, p.arpabet, p.ipa_segments, "
            f"p.ipa, p.syllable_count "
            f"FROM pronunciation p JOIN lexeme l ON l.id = p.lexeme_id "
            f"WHERE p.id IN ({placeholders})",
            ids,
        ).fetchall()
    finally:
        if own_conn:
            conn.close()

    query_forms = {text.strip().lower(), *tokenize(text)}

    best: dict[str, RhymeResult] = {}
    for written_form, frequency, arpabet, ipa_segments, ipa, syllable_count in rows:
        if not include_self and written_form in query_forms:
            continue
        cand_segs = _segs_from_row(arpabet, ipa_segments)
        if not cand_segs:
            continue
        similarity, stress_similarity, alignment = score_segments(
            target_segs, cand_segs, strictness=strictness
        )
        existing = best.get(written_form)
        if existing is None or similarity > existing.similarity:
            best[written_form] = RhymeResult(
                word=written_form,
                similarity=similarity,
                stress_similarity=stress_similarity,
                frequency=frequency or 0.0,
                syllable_count=syllable_count or 0,
                ipa=ipa or "",
                alignment=alignment,
            )

    results = sorted(
        best.values(), key=lambda r: (r.similarity, r.frequency), reverse=True
    )
    return results[:limit]
