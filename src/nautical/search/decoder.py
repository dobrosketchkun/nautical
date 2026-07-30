"""Multi-word phonetic decoder.

"Spells out" a target sound with sequences of real words (e.g. `nautical` ->
`not a cult`, `gnaw tickle`). A beam search tiles the target's IPA segments with
word pronunciations, allowing phonetic slack (scored by the Phase 2 aligner),
and ranks the tilings by phonetic similarity blended with word-frequency
naturalness so natural phrases beat gibberish while playful oronyms still
surface lower.

Efficiency: candidate transitions are computed once per target position (they
depend only on the position, not the beam state). The beam is pruned by
A*-style ``f = g + h`` so early expensive prefixes that enable a cheap ending
can survive. Completed tilings are pruned with a frequency-aware key because
final ranking is not cost-only.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import cache as cache_service
from ..config import DB_PATH
from ..db.quality import DEFAULT_MIN_QUALITY
from ..phonetics.align import (
    Alignment,
    Seg,
    align,
    align_cost,
    alignment_from_dict,
    alignment_to_dict,
)
from ..phonetics.anchor import boundary_surprise, rhyme_tail, segs_from_stored
from ..phonetics.distance import clamp, score_segments
from ..pronounce import enriched_segments, tokenize
from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights
from .normalize import onset_keys
from .diversity import select_diverse
from .plausibility import load_pos_lm, phrase_naturalness
from .ranking import ScoreComponents, display_sort_key, merge_variant_forms, rank_base

_segs_from_row = segs_from_stored

# When True, `_position_transitions` uses full `align` (test equivalence only).
_FORCE_FULL_ALIGN_TRANSITIONS = False

_DEFAULT_STRETCH = 2
_THOROUGH_STRETCH = 3
_THOROUGH_BEAM = 800
_THOROUGH_CAND_PER_POS = 2000
# Completed-pool prune: f - λ * mean(log freq). Favors grammatical common-word
# tilings among near-cost rivals so loose oronyms are not drowned by junk.
_COMPLETED_FREQ_LAMBDA = 0.35
_FREQ_FLOOR = 1e-12
# Final multiword rescoring: word-final consonant gaps at most this (oronym /t/).
_MW_GAP_CHEAP_CAP = 0.1
# Small boost for grammatical 3+ word tilings (content-bearing, not pure glue).
_MW_PHRASE_BONUS = 0.035
# Drop tilings whose weakest word is below this before diversity (filters "i'm").
_MW_RESULT_QUALITY_FLOOR = 0.55
# Full global align is expensive; cheap-proxy filter then fully rescore this many.
_MW_FULL_RESCORE_CAP = 800
# Beam expansion uses the phonetically-best transitions; full cand_per_pos still
# feeds the heuristic DAG, but expanding every row is O(beam×cand) Python.
_MW_EXPAND_TRANSITIONS = 400


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


# DP entry: (f, g, num_words, prev_pos, prev_idx, tr_idx, freq_log_sum)
_Entry = tuple[float, float, int, int, int, int, float]


def rescore_cap(beam_width: int, thorough: bool = False) -> int:
    """Completed-tiling pool size; independent of display ``limit``."""
    if thorough:
        return max(50_000, beam_width * 40)
    return max(10_000, beam_width * 40)


def completed_prune_key(entry: _Entry) -> float:
    """Lower is better: A* f adjusted by mean log-frequency (rank-aware)."""
    f, _g, num_words, _pp, _pi, _ti, freq_log_sum = entry
    mean_log = freq_log_sum / max(num_words, 1)
    return f - _COMPLETED_FREQ_LAMBDA * mean_log


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
    diversity: float = 0.30,
    prefix_cap: int = 3,
    min_quality: float = DEFAULT_MIN_QUALITY,
    weights: ScoringWeights | None = None,
    db_path: Path | None = None,
    stretch: int = _DEFAULT_STRETCH,
    thorough: bool = False,
) -> str:
    """Cache key for a multi-word decode (phonetic + diversity + quality + weights)."""
    w = weights if weights is not None else DEFAULT_WEIGHTS
    lex = cache_service.lexicon_identity(db_path)
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
            "stretch": stretch,
            "thorough": thorough,
            "weights_hash": w.weights_hash(),
            "schema_version": lex["schema_version"],
            "built_at": lex["built_at"],
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
    alignment: Alignment | None = None


def _position_transitions(
    conn: sqlite3.Connection,
    target: list[Seg],
    i: int,
    cand_per_pos: int,
    strictness: float,
    skip_words: set[str],
    word_boundary_leniency: bool = True,
    min_quality: float = DEFAULT_MIN_QUALITY,
    weights: ScoringWeights | None = None,
    stretch: int = _DEFAULT_STRETCH,
) -> list[_Transition]:
    """Candidate word transitions starting at target position ``i``."""
    w = weights if weights is not None else DEFAULT_WEIGHTS
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
    # Huge onset fanouts (4k+) make stretch expansion too slow; raise the
    # retrieve quality floor only for this cut so rare fits like ``cult``
    # (q≈0.58) remain while low-q junk is dropped.
    if len(rows) > 2000:
        q_cut = max(min_quality, 0.50)
        rows = [r for r in rows if float(r[2] or 0.0) >= q_cut]

    def _span_cost(cand_segs: list[Seg], length: int) -> tuple[float, Alignment | None]:
        span = target[i : i + length]
        if _FORCE_FULL_ALIGN_TRANSITIONS:
            alignment = align(
                cand_segs,
                span,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=w,
            )
            return alignment.total_cost, alignment
        return (
            align_cost(
                cand_segs,
                span,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=w,
            ),
            None,
        )

    # Phase A: score each onset hit at its native length (one align_cost each),
    # keep the phonetically-best survivors. Rare fits like `cult` must not lose
    # to a quality-only fanout cut.
    prelim: list[tuple[float, str, float, float, str, list[Seg], int]] = []
    for written_form, frequency, quality, pos_tag, arpabet, ipa_segments in rows:
        if written_form in skip_words:
            continue
        cand_segs = _segs_from_row(arpabet, ipa_segments)
        if not cand_segs:
            continue
        p_len = len(cand_segs)
        if p_len < 1 or i + p_len > n:
            # Fall back to nearest in-bounds length near p_len.
            length = min(max(p_len, 1), n - i)
        else:
            length = p_len
        cost, _ = _span_cost(cand_segs, length)
        prelim.append(
            (
                cost,
                written_form,
                frequency or 0.0,
                float(quality or 0.0),
                pos_tag or "",
                cand_segs,
                p_len,
            )
        )
    prelim.sort(key=lambda t: t[0])
    prelim = prelim[: max(cand_per_pos, 800)]

    # Phase B: stretch-expand survivors (real ±K slack for loose oronyms).
    transitions: list[_Transition] = []
    for cost0, written_form, frequency, quality, pos_tag, cand_segs, p_len in prelim:
        length_order = sorted(
            range(p_len - stretch, p_len + stretch + 1),
            key=lambda length: (abs(length - p_len), length),
        )
        best_cost = math.inf
        for length in length_order:
            if length < 1 or i + length > n:
                continue
            cost, alignment = _span_cost(cand_segs, length)
            if best_cost < math.inf and cost > best_cost + 1.0:
                continue
            best_cost = min(best_cost, cost)
            transitions.append(
                _Transition(
                    word=written_form,
                    frequency=frequency,
                    quality=quality,
                    pos_tag=pos_tag,
                    length=length,
                    cost=cost,
                    segs=cand_segs,
                    alignment=alignment,
                )
            )

    # Keep the phonetically-best candidates (NOT the most frequent): rare but
    # well-fitting words like `gnaw`, `tickle`, `cult` must survive to the beam;
    # frequency influences only the final naturalness ranking.
    transitions.sort(key=lambda t: t.cost)
    return transitions[:cand_per_pos]


def suffix_heuristic(
    transitions: list[list[_Transition]], n: int
) -> list[float]:
    """Backward min remaining cost on the transition DAG; ``h[n] == 0``.

    Admissible for search restricted to these transitions: ``h[i]`` is the
    cheapest path cost from position ``i`` to the end (or ``+inf`` if none).
    """
    h = [math.inf] * (n + 1)
    h[n] = 0.0
    for i in range(n - 1, -1, -1):
        best = math.inf
        for tr in transitions[i]:
            j = i + tr.length
            if j <= n and h[j] < math.inf:
                best = min(best, tr.cost + h[j])
        h[i] = best
    return h


def _materialize_alignments(
    steps: list[_Transition],
    target: list[Seg],
    *,
    strictness: float,
    word_boundary_leniency: bool,
    weights: ScoringWeights,
) -> list[_Transition]:
    """Fill full alignments on beam survivors that only carried a cost."""
    out: list[_Transition] = []
    pos = 0
    for tr in steps:
        if tr.alignment is None:
            alignment = align(
                tr.segs,
                target[pos : pos + tr.length],
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=weights,
            )
            tr = _Transition(
                word=tr.word,
                frequency=tr.frequency,
                quality=tr.quality,
                pos_tag=tr.pos_tag,
                length=tr.length,
                cost=tr.cost,
                segs=tr.segs,
                alignment=alignment,
            )
        out.append(tr)
        pos += tr.length
    return out


def _reconstruct(
    entry: _Entry,
    nodes: list[list[_Entry]],
    transitions: list[list[_Transition]],
) -> list[_Transition]:
    """Walk back-pointers to recover the transitions of a completed path."""
    steps: list[_Transition] = []
    _f, _g, _num_words, prev_pos, prev_idx, tr_idx, _fl = entry
    while prev_pos >= 0:
        steps.append(transitions[prev_pos][tr_idx])
        _f, _g, _num_words, prev_pos, prev_idx, tr_idx, _fl = nodes[prev_pos][
            prev_idx
        ]
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
    diversity: float = 0.30,
    prefix_cap: int = 3,
    min_quality: float | None = None,
    use_cache: bool = True,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    weights: ScoringWeights | None = None,
    stretch: int | None = None,
    thorough: bool = False,
) -> tuple[list[MultiwordResult], bool]:
    """Return ``(ranked multi-word sequences, was_cached)``.

    ``anchor`` (0 = full-span, 1 = tail-anchored) blends the whole-tiling
    similarity with a rhyme-tail similarity so ``--anchor tail`` biases toward
    tilings whose ending matches the target's rhyme. Multi-word echoes are
    inherently full-span, so the default is ``0.0``.

    ``word_boundary_leniency`` makes word-final consonants cheap to drop;
    ``exclude`` bars those words from every tiling.

    ``diversity`` (0 = pure rank order) and ``prefix_cap`` apply presentation-
    layer selection after IPA collapse so similar prefixes do not monopolize
    the top rows. ``min_quality`` gates the decode inventory (0 = full lexicon).

    ``thorough`` widens beam, candidate cut, stretch, and rescore pool for
    hard loose oronyms (higher latency).

    Results are cached (keyed on the phonetic + diversity + quality + weights)
    unless ``use_cache`` is False or an explicit ``conn`` is supplied.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    if min_quality is None:
        min_quality = w.min_quality
    exclude = exclude or frozenset()

    if thorough:
        beam_width = max(beam_width, _THOROUGH_BEAM)
        cand_per_pos = max(cand_per_pos, _THOROUGH_CAND_PER_POS)
        if stretch is None:
            stretch = _THOROUGH_STRETCH
    elif stretch is None:
        stretch = _DEFAULT_STRETCH

    final_cap = rescore_cap(beam_width, thorough=thorough)

    cache_key = None
    if use_cache and conn is None:
        cache_key = multiword_cache_key(
            text,
            limit,
            beam_width,
            cand_per_pos,
            max_words,
            min_words,
            strictness,
            anchor,
            word_boundary_leniency,
            exclude,
            diversity,
            prefix_cap,
            min_quality,
            weights=w,
            db_path=db_path,
            stretch=stretch,
            thorough=thorough,
        )
        cached = cache_service.cache_get(cache_key, db_path=cache_db_path)
        if cached is not None:
            return [_result_from_dict(d) for d in cached], True

    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        target = enriched_segments(text, conn=conn)
        n = len(target)
        if n == 0:
            return [], False

        input_tokens = tokenize(text)
        skip_words = {text.strip().lower()} | set(exclude)
        pos_lm = load_pos_lm(conn)

        # Materialize every position's transitions once, then compute the
        # admissible suffix heuristic for A* beam ordering.
        transitions: list[list[_Transition]] = [
            _position_transitions(
                conn,
                target,
                i,
                cand_per_pos,
                strictness,
                skip_words,
                word_boundary_leniency,
                min_quality,
                weights=w,
                stretch=stretch,
            )
            for i in range(n)
        ]
        h = suffix_heuristic(transitions, n)

        # nodes[n] holds completed tilings. Intermediate beams prune by f=g+h;
        # the completed pool also uses a frequency-aware key because final
        # ranking is not cost-only (and is independent of display limit).
        nodes: list[list[_Entry]] = [[] for _ in range(n + 1)]
        h0 = 0.0 if h[0] == math.inf else h[0]
        nodes[0] = [(h0, 0.0, 0, -1, -1, -1, 0.0)]

        for i in range(n):
            if not nodes[i]:
                continue
            nodes[i].sort(key=lambda e: e[0])
            del nodes[i][beam_width:]

            pos_transitions = transitions[i]
            expand_n = min(len(pos_transitions), max(_MW_EXPAND_TRANSITIONS, cand_per_pos // 2))
            for idx, entry in enumerate(nodes[i]):
                _f, g, num_words = entry[0], entry[1], entry[2]
                freq_log_sum = entry[6]
                if num_words >= max_words:
                    continue
                for tr_idx, tr in enumerate(pos_transitions[:expand_n]):
                    j = i + tr.length
                    g2 = g + tr.cost
                    hj = h[j]
                    f2 = g2 if hj == math.inf else g2 + hj
                    fl2 = freq_log_sum + math.log(max(tr.frequency, _FREQ_FLOOR))
                    nodes[j].append(
                        (f2, g2, num_words + 1, i, idx, tr_idx, fl2)
                    )

            for j in range(i + 1, n + 1):
                cap = final_cap if j == n else beam_width
                if len(nodes[j]) <= cap:
                    continue
                if j == n:
                    nodes[j].sort(key=completed_prune_key)
                else:
                    nodes[j].sort(key=lambda e: e[0])
                del nodes[j][cap:]

        nodes[n].sort(key=completed_prune_key)

        target_tail = rhyme_tail(target) if anchor > 0.0 else []
        # Lenient word-final gaps for final oronym scoring only (search still
        # uses ``w``); column-mean similarity restores pre-U2 oronym scale.
        mw_w = replace(w, gap_cheap_consonant=min(w.gap_cheap_consonant, _MW_GAP_CHEAP_CAP))

        # Collapse tilings that share the same sound onto one row; keep alternate
        # spellings as variants under the preferred display form.
        best_by_ipa: dict[str, MultiwordResult] = {}
        display_freq: dict[str, float] = {}

        # Phase 1: reconstruct + naturalness + cheap phonetic proxy (path cost).
        # Full global align (phase 2) only for the top proxy survivors.
        proxied: list[
            tuple[float, _Entry, list[_Transition], float, float, float, float]
        ] = []
        for entry in nodes[n]:
            if entry[2] < min_words:
                continue
            steps = _reconstruct(entry, nodes, transitions)
            phrase_quality = min(tr.quality for tr in steps)
            if phrase_quality < _MW_RESULT_QUALITY_FLOOR:
                continue
            words = [tr.word for tr in steps]
            if words == input_tokens:
                continue
            naturalness, _fg, pos_plaus, func_ok = phrase_naturalness(
                [tr.frequency for tr in steps],
                [tr.pos_tag for tr in steps],
                pos_lm,
                words=words,
                weights=w,
            )
            g = entry[1]
            proxy_sim = clamp(1.0 - g / max(n, 1))
            num_words = len(words)
            proxy_score = rank_base(
                proxy_sim,
                0.7,
                1.0,
                naturalness=naturalness,
                num_words=num_words,
                weights=w,
            )
            if (
                num_words >= 3
                and (pos_plaus or 0.0) >= 0.65
                and (func_ok or 0.0) > 0.0
            ):
                proxy_score = min(1.0, proxy_score + _MW_PHRASE_BONUS)
            proxied.append(
                (proxy_score, entry, steps, naturalness, pos_plaus, func_ok, phrase_quality)
            )
        proxied.sort(key=lambda t: t[0], reverse=True)
        del proxied[_MW_FULL_RESCORE_CAP:]

        for (
            _proxy,
            entry,
            steps,
            naturalness,
            pos_plaus,
            func_ok,
            phrase_quality,
        ) in proxied:
            words = [tr.word for tr in steps]
            phrase = " ".join(words)
            steps = _materialize_alignments(
                steps,
                target,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=mw_w,
            )

            segs = [s for tr in steps for s in tr.segs]
            _hybrid, stress_similarity, global_alignment = score_segments(
                target,
                segs,
                strictness=strictness,
                word_boundary_leniency=word_boundary_leniency,
                weights=mw_w,
            )
            n_cols = max(len(global_alignment.pairs), 1)
            full_similarity = clamp(
                1.0 - global_alignment.total_cost / n_cols
            )
            similarity = full_similarity
            if anchor > 0.0:
                _tail_h, _, tail_aln = score_segments(
                    target_tail,
                    rhyme_tail(segs),
                    strictness=strictness,
                    word_boundary_leniency=word_boundary_leniency,
                    weights=mw_w,
                )
                t_cols = max(len(tail_aln.pairs), 1)
                tail_similarity = clamp(1.0 - tail_aln.total_cost / t_cols)
                similarity = (1.0 - anchor) * full_similarity + anchor * tail_similarity
            else:
                tail_similarity = full_similarity
            naturalness, freq_geom, pos_plaus, func_ok = phrase_naturalness(
                [tr.frequency for tr in steps],
                [tr.pos_tag for tr in steps],
                pos_lm,
                words=words,
                weights=w,
            )
            num_words = len(words)
            surprise = boundary_surprise(global_alignment)
            base_score = rank_base(
                similarity,
                stress_similarity,
                surprise,
                naturalness=naturalness,
                num_words=num_words,
                weights=w,
            )
            if (
                num_words >= 3
                and (pos_plaus or 0.0) >= 0.65
                and (func_ok or 0.0) > 0.0
            ):
                base_score = min(1.0, base_score + _MW_PHRASE_BONUS)

            sound_key = "".join(s.ipa for s in segs)
            phrase_freq = sum(tr.frequency for tr in steps)
            candidate = MultiwordResult(
                phrase=phrase,
                words=words,
                num_words=num_words,
                ipa=sound_key,
                chunks=[
                    (tr.word, tr.alignment)
                    for tr in steps
                    if tr.alignment is not None
                ],
                alignment=global_alignment,
                scores=ScoreComponents(
                    phonetic_similarity=similarity,
                    full_similarity=full_similarity,
                    tail_similarity=tail_similarity,
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
    return results, False
