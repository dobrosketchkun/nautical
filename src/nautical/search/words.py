"""Single-word phonetic search: retrieve, rerank, rank."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .. import cache as cache_service
from ..config import DB_PATH
from ..db.quality import DEFAULT_MIN_QUALITY
from ..phonetics.align import Alignment, alignment_from_dict, alignment_to_dict
from ..phonetics.anchor import (
    anchored_score,
    boundary_surprise,
    rhyme_tail,
    segs_from_stored,
)
from ..pronounce import enriched_segment_variants, enriched_segments, tokenize
from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights
from .index import candidate_ids, tail_candidate_ids
from .ranking import ScoreComponents, display_sort_key, merge_variant_forms, rank_base

# Backwards-compatible alias (decoder.py imports this name).
_segs_from_row = segs_from_stored


@dataclass
class RhymeResult:
    word: str
    frequency: float
    syllable_count: int
    ipa: str
    alignment: Alignment
    scores: ScoreComponents
    variants: list[str] = field(default_factory=list)
    quality: float = 0.0

    @property
    def similarity(self) -> float:
        return self.scores.phonetic_similarity

    @property
    def full_similarity(self) -> float:
        return self.scores.full_similarity

    @property
    def tail_similarity(self) -> float:
        return self.scores.tail_similarity

    @property
    def stress_similarity(self) -> float:
        return self.scores.stress_similarity

    @property
    def boundary_surprise(self) -> float:
        return self.scores.boundary_surprise

    @property
    def theme_fit(self) -> float | None:
        return self.scores.theme_fit

    @property
    def rank_score(self) -> float:
        return self.scores.rank_score


def _result_to_dict(r: RhymeResult) -> dict:
    return {
        "word": r.word,
        "frequency": r.frequency,
        "syllable_count": r.syllable_count,
        "ipa": r.ipa,
        "alignment": alignment_to_dict(r.alignment),
        "scores": r.scores.to_dict(),
        "variants": list(r.variants),
        "quality": r.quality,
    }


def _result_from_dict(d: dict) -> RhymeResult:
    return RhymeResult(
        word=d["word"],
        frequency=d["frequency"],
        syllable_count=d["syllable_count"],
        ipa=d["ipa"],
        alignment=alignment_from_dict(d["alignment"]),
        scores=ScoreComponents.from_dict(d["scores"]),
        variants=list(d.get("variants", [])),
        quality=float(d.get("quality", 0.0)),
    )


def rhymes_cache_key(
    text: str,
    limit: int,
    pool: int,
    strictness: float,
    anchor: float,
    include_self: bool,
    word_boundary_leniency: bool = True,
    multi_variant: bool = True,
    exclude: frozenset[str] | None = None,
    min_quality: float = DEFAULT_MIN_QUALITY,
    weights: ScoringWeights | None = None,
    db_path: Path | None = None,
) -> str:
    """Cache key for a single-word search (phonetic + quality + weights)."""
    w = weights if weights is not None else DEFAULT_WEIGHTS
    lex = cache_service.lexicon_identity(db_path)
    return cache_service.make_key(
        "rhymes",
        text,
        {
            "limit": limit,
            "pool": pool,
            "strictness": strictness,
            "anchor": anchor,
            "include_self": include_self,
            "word_boundary_leniency": word_boundary_leniency,
            "multi_variant": multi_variant,
            "exclude": sorted(exclude) if exclude else [],
            "min_quality": min_quality,
            "weights_hash": w.weights_hash(),
            "schema_version": lex["schema_version"],
            "built_at": lex["built_at"],
        },
    )


def find_rhymes(
    text: str,
    limit: int = 25,
    pool: int = 1500,
    strictness: float = 0.5,
    anchor: float = 0.5,
    include_self: bool = False,
    word_boundary_leniency: bool = True,
    multi_variant: bool = True,
    exclude: frozenset[str] | None = None,
    min_quality: float | None = None,
    use_cache: bool = True,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    weights: ScoringWeights | None = None,
) -> list[RhymeResult]:
    """Return ranked single-word sound-alikes for ``text``.

    Two-stage: generous n-gram retrieval, then anchored rerank. The ``anchor``
    dial (0 = full-span, 1 = tail-anchored) blends whole-word and rhyme-tail
    similarity; when it favors the tail, the tail n-gram index is also queried so
    end-rhymes that share little else still enter the pool.

    ``multi_variant`` scores the query's every pronunciation variant and keeps the
    best per candidate; ``word_boundary_leniency`` makes word-final consonants
    cheap to drop; ``exclude`` drops those words from the results before limiting.
    ``min_quality`` gates the candidate inventory (0 = full lexicon).

    Results are cached (keyed on the phonetic + quality + weights params) unless
    ``use_cache`` is False or an explicit ``conn`` is supplied (tests pass their
    own DB).
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    if min_quality is None:
        min_quality = w.min_quality
    exclude = exclude or frozenset()
    cache_key = None
    if use_cache and conn is None:
        cache_key = rhymes_cache_key(
            text,
            limit,
            pool,
            strictness,
            anchor,
            include_self,
            word_boundary_leniency,
            multi_variant,
            exclude,
            min_quality,
            weights=w,
            db_path=db_path,
        )
        cached = cache_service.cache_get(cache_key, db_path=cache_db_path)
        if cached is not None:
            return [_result_from_dict(d) for d in cached]

    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        if multi_variant:
            target_variants = enriched_segment_variants(text, conn=conn)
        else:
            target_variants = [enriched_segments(text, conn=conn)]
        target_variants = [tv for tv in target_variants if tv]
        if not target_variants:
            return []

        # Union the candidate pool across every query variant.
        ids: set[int] = set()
        for target_segs in target_variants:
            target_ipa = [s.ipa for s in target_segs]
            ids.update(candidate_ids(conn, target_ipa, pool))
            if anchor > 0.0:
                tail_ipa = [s.ipa for s in rhyme_tail(target_segs)]
                ids.update(tail_candidate_ids(conn, tail_ipa, pool))
        if not ids:
            return []

        id_list = list(ids)
        placeholders = ",".join("?" * len(id_list))
        rows = conn.execute(
            f"SELECT l.written_form, l.frequency, l.quality, p.arpabet, "
            f"p.ipa_segments, p.ipa, p.syllable_count "
            f"FROM pronunciation p JOIN lexeme l ON l.id = p.lexeme_id "
            f"WHERE p.id IN ({placeholders}) AND l.quality >= ?",
            (*id_list, min_quality),
        ).fetchall()
    finally:
        if own_conn:
            conn.close()

    query_forms = {text.strip().lower(), *tokenize(text)}

    # Collapse exact homophones / variant spellings onto one IPA sound key.
    best_by_ipa: dict[str, RhymeResult] = {}
    for (
        written_form,
        frequency,
        quality,
        arpabet,
        ipa_segments,
        ipa,
        syllable_count,
    ) in rows:
        if not include_self and written_form in query_forms:
            continue
        if written_form in exclude:
            continue
        cand_segs = segs_from_stored(arpabet, ipa_segments)
        if not cand_segs:
            continue
        # Best score across the query's pronunciation variants.
        score = None
        for target_segs in target_variants:
            s = anchored_score(
                target_segs,
                cand_segs,
                anchor=anchor,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=w,
            )
            if score is None or s.anchored_similarity > score.anchored_similarity:
                score = s
        surprise = boundary_surprise(score.full_alignment)
        base_score = rank_base(
            score.anchored_similarity,
            score.stress_similarity,
            surprise,
            weights=w,
        )
        sound_key = ipa or "".join(s.ipa for s in cand_segs)
        freq = frequency or 0.0
        candidate = RhymeResult(
            word=written_form,
            frequency=freq,
            syllable_count=syllable_count or 0,
            ipa=sound_key,
            alignment=score.full_alignment,
            scores=ScoreComponents(
                phonetic_similarity=score.anchored_similarity,
                full_similarity=score.full_similarity,
                tail_similarity=score.tail_similarity,
                stress_similarity=score.stress_similarity,
                boundary_surprise=surprise,
                base_score=base_score,
                rank_score=base_score,
            ),
            quality=float(quality or 0.0),
        )
        existing = best_by_ipa.get(sound_key)
        if existing is None:
            best_by_ipa[sound_key] = candidate
            continue
        if written_form == existing.word:
            if base_score > existing.rank_score:
                candidate.variants = list(existing.variants)
                best_by_ipa[sound_key] = candidate
            continue
        if display_sort_key(freq, written_form) < display_sort_key(
            existing.frequency, existing.word
        ):
            candidate.variants = merge_variant_forms(
                written_form, existing.variants, existing.word
            )
            best_by_ipa[sound_key] = candidate
        else:
            existing.variants = merge_variant_forms(
                existing.word, existing.variants, written_form
            )

    results = sorted(
        best_by_ipa.values(), key=lambda r: (r.rank_score, r.frequency), reverse=True
    )[:limit]

    if cache_key is not None:
        cache_service.cache_put(
            cache_key, [_result_to_dict(r) for r in results], db_path=cache_db_path
        )
    return results
