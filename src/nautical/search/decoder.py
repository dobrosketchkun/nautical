"""Multi-word phonetic decoder.

"Spells out" a target sound with sequences of real words (e.g. `nautical` ->
`not a cult`, `gnaw tickle`). A beam search tiles the target's IPA segments with
word pronunciations, allowing phonetic slack (scored by the Phase 2 aligner),
and ranks the tilings by phonetic similarity blended with word-frequency
naturalness so natural phrases beat gibberish while playful oronyms still
surface lower.

Efficiency: candidate transitions are computed once per target position (they
depend only on the position, not the beam state), so the work is ~N x
cand_per_pos small alignments plus cheap beam bookkeeping.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .. import cache as cache_service
from ..config import DB_PATH
from ..db.quality import DEFAULT_MIN_QUALITY
from ..phonetics.align import (
    Alignment,
    Seg,
    align,
    alignment_from_dict,
    alignment_to_dict,
)
from ..phonetics.anchor import boundary_surprise, rhyme_tail, segs_from_stored
from ..phonetics.distance import _stress_similarity, _stress_string, score_segments
from ..pronounce import enriched_segments, tokenize
from .normalize import onset_keys
from .diversity import select_diverse
from .plausibility import load_pos_lm, phrase_naturalness
from .ranking import ScoreComponents, display_sort_key, merge_variant_forms, rank_base

_segs_from_row = segs_from_stored

@dataclass
class MultiwordResult:
    phrase: str
    words: list[str]
    num_words: int
    ipa: str
    chunks: list[tuple[str, Alignment]]
    alignment: Alignment
    scores: ScoreComponents
    variants: list[str] = field(default_factory=list)
    quality: float = 0.0

    @property
    def similarity(self) -> float:
        return self.scores.phonetic_similarity

    @property
    def stress_similarity(self) -> float:
        return self.scores.stress_similarity

    @property
    def naturalness(self) -> float:
        return self.scores.naturalness or 0.0

    @property
    def boundary_surprise(self) -> float:
        return self.scores.boundary_surprise

    @property
    def theme_fit(self) -> float | None:
        return self.scores.theme_fit

    @property
    def rank_score(self) -> float:
        return self.scores.rank_score

    @property
    def score(self) -> float:
        """Backwards-compatible alias for the explicit rank score."""
        return self.rank_score


def _result_to_dict(r: MultiwordResult) -> dict:
    return {
        "phrase": r.phrase,
        "words": r.words,
        "num_words": r.num_words,
        "ipa": r.ipa,
        "chunks": [[w, alignment_to_dict(a)] for w, a in r.chunks],
        "alignment": alignment_to_dict(r.alignment),
        "scores": r.scores.to_dict(),
        "variants": list(r.variants),
        "quality": r.quality,
    }


def _result_from_dict(d: dict) -> MultiwordResult:
    return MultiwordResult(
        phrase=d["phrase"],
        words=d["words"],
        num_words=d["num_words"],
        ipa=d["ipa"],
        chunks=[(w, alignment_from_dict(a)) for w, a in d["chunks"]],
        alignment=alignment_from_dict(d["alignment"]),
        scores=ScoreComponents.from_dict(d["scores"]),
        variants=list(d.get("variants", [])),
        quality=float(d.get("quality", 0.0)),
    )


def multiword_cache_key(
    text: str,
    limit: int,
    beam_width: int,
    cand_per_pos: int,
    max_words: int,
    min_words: int,
    strictness: float,
    anchor: float,
    word_boundary_leniency: bool = True,
    exclude: frozenset[str] | None = None,
    diversity: float = 0.35,
    prefix_cap: int = 3,
    min_quality: float = DEFAULT_MIN_QUALITY,
) -> str:
    """Cache key for a multi-word decode (phonetic + diversity + quality params)."""
    return cache_service.make_key(
        "multiword",
        text,
        {
            "limit": limit,
            "beam_width": beam_width,
            "cand_per_pos": cand_per_pos,
            "max_words": max_words,
            "min_words": min_words,
            "strictness": strictness,
            "anchor": anchor,
            "word_boundary_leniency": word_boundary_leniency,
            "exclude": sorted(exclude) if exclude else [],
            "diversity": diversity,
            "prefix_cap": prefix_cap,
            "min_quality": min_quality,
        },
    )


@dataclass
class _Transition:
    word: str
    frequency: float
    quality: float
    pos_tag: str
    length: int  # target segments consumed
    cost: float
    segs: list[Seg]
    alignment: Alignment


def _position_transitions(
    conn: sqlite3.Connection,
    target: list[Seg],
    i: int,
    cand_per_pos: int,
    strictness: float,
    skip_words: set[str],
    word_boundary_leniency: bool = True,
    min_quality: float = DEFAULT_MIN_QUALITY,
) -> list[_Transition]:
    """Candidate word transitions starting at target position ``i``."""
    n = len(target)
    target_ipa = [s.ipa for s in target]
    keys = onset_keys(target_ipa[i : i + 2])
    if not keys:
        return []

    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT l.written_form, l.frequency, l.quality, l.pos_tag, "
        f"p.arpabet, p.ipa_segments "
        f"FROM decode_onset d "
        f"JOIN pronunciation p ON p.id = d.pronunciation_id "
        f"JOIN lexeme l ON l.id = p.lexeme_id "
        f"WHERE d.onset_key IN ({placeholders}) AND l.quality >= ? "
        f"GROUP BY p.id",
        (*keys, min_quality),
    ).fetchall()

    transitions: list[_Transition] = []
    for written_form, frequency, quality, pos_tag, arpabet, ipa_segments in rows:
        if written_form in skip_words:
            continue
        cand_segs = _segs_from_row(arpabet, ipa_segments)
        if not cand_segs:
            continue
        p_len = len(cand_segs)
        # Emit a transition for each plausible consumed length, not just the
        # single best: alternate segmentations matter (e.g. `knot` consuming 2
        # target segments enables `knot tickle`, consuming 3 enables `knot ...`).
        for length in (p_len - 1, p_len, p_len + 1):
            if length < 1 or i + length > n:
                continue
            alignment = align(
                cand_segs, target[i : i + length], strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
            )
            transitions.append(
                _Transition(
                    word=written_form,
                    frequency=frequency or 0.0,
                    quality=float(quality or 0.0),
                    pos_tag=pos_tag or "",
                    length=length,
                    cost=alignment.total_cost,
                    segs=cand_segs,
                    alignment=alignment,
                )
            )

    # Keep the phonetically-best candidates (NOT the most frequent): rare but
    # well-fitting words like `gnaw`, `tickle`, `cult` must survive to the beam;
    # frequency influences only the final naturalness ranking.
    transitions.sort(key=lambda t: t.cost)
    return transitions[:cand_per_pos]


# A DP entry is a compact tuple so the beam can be wide without copying path
# state: (cost, num_words, prev_pos, prev_idx, tr_idx). The word sequence is
# reconstructed via back-pointers only for the final top results.
#   cost      accumulated alignment cost
#   num_words words used so far
#   prev_pos  target position of the predecessor entry (-1 for the root)
#   prev_idx  index of the predecessor entry within nodes[prev_pos]
#   tr_idx    index into transitions[prev_pos] taken to reach here (-1 for root)
_Entry = tuple[float, int, int, int, int]


def _reconstruct(
    entry: _Entry,
    nodes: list[list[_Entry]],
    transitions: list[list[_Transition]],
) -> list[_Transition]:
    """Walk back-pointers to recover the transitions of a completed path."""
    steps: list[_Transition] = []
    cost, num_words, prev_pos, prev_idx, tr_idx = entry
    while prev_pos >= 0:
        steps.append(transitions[prev_pos][tr_idx])
        cost, num_words, prev_pos, prev_idx, tr_idx = nodes[prev_pos][prev_idx]
    steps.reverse()
    return steps


def find_multiword(
    text: str,
    limit: int = 25,
    beam_width: int = 300,
    cand_per_pos: int = 350,
    max_words: int = 5,
    min_words: int = 2,
    strictness: float = 0.5,
    anchor: float = 0.0,
    word_boundary_leniency: bool = True,
    exclude: frozenset[str] | None = None,
    diversity: float = 0.35,
    prefix_cap: int = 3,
    min_quality: float = DEFAULT_MIN_QUALITY,
    use_cache: bool = True,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[MultiwordResult]:
    """Return ranked multi-word sequences that sound like ``text``.

    ``anchor`` (0 = full-span, 1 = tail-anchored) blends the whole-tiling
    similarity with a rhyme-tail similarity so ``--anchor tail`` biases toward
    tilings whose ending matches the target's rhyme. Multi-word echoes are
    inherently full-span, so the default is ``0.0``.

    ``word_boundary_leniency`` makes word-final consonants cheap to drop;
    ``exclude`` bars those words from every tiling.

    ``diversity`` (0 = pure rank order) and ``prefix_cap`` apply presentation-
    layer selection after IPA collapse so similar prefixes do not monopolize
    the top rows. ``min_quality`` gates the decode inventory (0 = full lexicon).

    Results are cached (keyed on the phonetic + diversity + quality params)
    unless ``use_cache`` is False or an explicit ``conn`` is supplied.
    """
    exclude = exclude or frozenset()
    cache_key = None
    if use_cache and conn is None:
        cache_key = multiword_cache_key(
            text, limit, beam_width, cand_per_pos, max_words, min_words,
            strictness, anchor, word_boundary_leniency, exclude,
            diversity, prefix_cap, min_quality,
        )
        cached = cache_service.cache_get(cache_key, db_path=cache_db_path)
        if cached is not None:
            return [_result_from_dict(d) for d in cached]

    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        target = enriched_segments(text, conn=conn)
        n = len(target)
        if n == 0:
            return []

        input_tokens = tokenize(text)
        skip_words = {text.strip().lower()} | set(exclude)
        pos_lm = load_pos_lm(conn)

        # nodes[n] holds completed tilings; there are combinatorially many, so it
        # is capped (by cost) during the DP to bound memory. Final ranking also
        # uses stress, boundary surprise, naturalness, and word count, so keep
        # this cost-ranked window comfortably larger than the requested limit.
        final_cap = max(beam_width, min(limit * 50, 100_000))

        transitions: list[list[_Transition]] = [[] for _ in range(n)]
        nodes: list[list[_Entry]] = [[] for _ in range(n + 1)]
        nodes[0] = [(0.0, 0, -1, -1, -1)]

        for i in range(n):
            if not nodes[i]:
                continue
            nodes[i].sort(key=lambda e: e[0])
            del nodes[i][beam_width:]

            if not transitions[i]:
                transitions[i] = _position_transitions(
                    conn, target, i, cand_per_pos, strictness, skip_words,
                    word_boundary_leniency, min_quality,
                )

            pos_transitions = transitions[i]
            for idx, entry in enumerate(nodes[i]):
                cost, num_words = entry[0], entry[1]
                if num_words >= max_words:
                    continue
                for tr_idx, tr in enumerate(pos_transitions):
                    nodes[i + tr.length].append(
                        (cost + tr.cost, num_words + 1, i, idx, tr_idx)
                    )

            # Bound memory: keep each downstream node to its cap (best by cost).
            # Truncating early is safe because cost only accumulates, so a dropped
            # higher-cost entry can never re-enter the best set.
            for j in range(i + 1, n + 1):
                cap = final_cap if j == n else beam_width
                if len(nodes[j]) > cap:
                    nodes[j].sort(key=lambda e: e[0])
                    del nodes[j][cap:]

        nodes[n].sort(key=lambda e: e[0])

        target_stress = _stress_string(target)
        target_tail = rhyme_tail(target) if anchor > 0.0 else []

        # Collapse tilings that share the same sound onto one row; keep alternate
        # spellings as variants under the preferred display form.
        best_by_ipa: dict[str, MultiwordResult] = {}
        display_freq: dict[str, float] = {}
        for entry in nodes[n]:
            if entry[1] < min_words:
                continue
            steps = _reconstruct(entry, nodes, transitions)
            words = [tr.word for tr in steps]
            if words == input_tokens:
                continue
            phrase = " ".join(words)

            segs = [s for tr in steps for s in tr.segs]
            similarity = max(0.0, 1.0 - entry[0] / n)
            if anchor > 0.0:
                tail_similarity, _, _ = score_segments(
                    target_tail, rhyme_tail(segs), strictness=strictness,
                    word_boundary_leniency=word_boundary_leniency,
                )
                similarity = (1.0 - anchor) * similarity + anchor * tail_similarity
            naturalness, freq_geom, pos_plaus, func_ok = phrase_naturalness(
                [tr.frequency for tr in steps],
                [tr.pos_tag for tr in steps],
                pos_lm,
                words=[tr.word for tr in steps],
            )
            num_words = len(words)
            stress_similarity = _stress_similarity(_stress_string(segs), target_stress)
            _, _, global_alignment = score_segments(
                target,
                segs,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
            )
            surprise = boundary_surprise(global_alignment)
            base_score = rank_base(
                similarity,
                stress_similarity,
                surprise,
                naturalness=naturalness,
                num_words=num_words,
            )

            sound_key = "".join(s.ipa for s in segs)
            phrase_freq = sum(tr.frequency for tr in steps)
            phrase_quality = min(tr.quality for tr in steps)
            candidate = MultiwordResult(
                phrase=phrase,
                words=words,
                num_words=num_words,
                ipa=sound_key,
                chunks=[(tr.word, tr.alignment) for tr in steps],
                alignment=global_alignment,
                scores=ScoreComponents(
                    phonetic_similarity=similarity,
                    full_similarity=similarity,
                    tail_similarity=tail_similarity if anchor > 0.0 else similarity,
                    stress_similarity=stress_similarity,
                    naturalness=naturalness,
                    freq_naturalness=freq_geom,
                    pos_plausibility=pos_plaus,
                    function_ok=func_ok,
                    boundary_surprise=surprise,
                    base_score=base_score,
                    rank_score=base_score,
                ),
                quality=phrase_quality,
            )
            existing = best_by_ipa.get(sound_key)
            if existing is None:
                best_by_ipa[sound_key] = candidate
                display_freq[sound_key] = phrase_freq
                continue
            if phrase == existing.phrase:
                if base_score > existing.rank_score:
                    candidate.variants = list(existing.variants)
                    best_by_ipa[sound_key] = candidate
                    display_freq[sound_key] = phrase_freq
                continue
            if display_sort_key(phrase_freq, phrase) < display_sort_key(
                display_freq[sound_key], existing.phrase
            ):
                candidate.variants = merge_variant_forms(
                    phrase, existing.variants, existing.phrase
                )
                best_by_ipa[sound_key] = candidate
                display_freq[sound_key] = phrase_freq
            else:
                existing.variants = merge_variant_forms(
                    existing.phrase, existing.variants, phrase
                )
    finally:
        if own_conn:
            conn.close()

    ranked = sorted(best_by_ipa.values(), key=lambda r: r.rank_score, reverse=True)
    results = select_diverse(
        ranked, limit=limit, diversity=diversity, prefix_cap=prefix_cap
    )

    if cache_key is not None:
        cache_service.cache_put(
            cache_key, [_result_to_dict(r) for r in results], db_path=cache_db_path
        )
    return results
