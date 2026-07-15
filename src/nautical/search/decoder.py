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

import math
import sqlite3
from dataclasses import dataclass

from .. import cache as cache_service
from ..config import DB_PATH
from ..phonetics.align import (
    Alignment,
    Seg,
    align,
    alignment_from_dict,
    alignment_to_dict,
)
from ..phonetics.anchor import rhyme_tail, segs_from_stored
from ..phonetics.distance import _stress_similarity, _stress_string, score_segments
from ..pronounce import enriched_segments, tokenize
from .normalize import onset_keys

_segs_from_row = segs_from_stored

# Ranking blend (uncalibrated first pass; see docs/NOTES.md).
_W_NATURALNESS = 0.35
_W_WORDS = 0.05


@dataclass
class MultiwordResult:
    phrase: str
    words: list[str]
    similarity: float
    stress_similarity: float
    naturalness: float
    num_words: int
    ipa: str
    score: float
    chunks: list[tuple[str, Alignment]]
    theme_fit: float | None = None


def _result_to_dict(r: MultiwordResult) -> dict:
    return {
        "phrase": r.phrase,
        "words": r.words,
        "similarity": r.similarity,
        "stress_similarity": r.stress_similarity,
        "naturalness": r.naturalness,
        "num_words": r.num_words,
        "ipa": r.ipa,
        "score": r.score,
        "chunks": [[w, alignment_to_dict(a)] for w, a in r.chunks],
    }


def _result_from_dict(d: dict) -> MultiwordResult:
    return MultiwordResult(
        phrase=d["phrase"],
        words=d["words"],
        similarity=d["similarity"],
        stress_similarity=d["stress_similarity"],
        naturalness=d["naturalness"],
        num_words=d["num_words"],
        ipa=d["ipa"],
        score=d["score"],
        chunks=[(w, alignment_from_dict(a)) for w, a in d["chunks"]],
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
) -> str:
    """Cache key for a multi-word decode (phonetic params only)."""
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
        },
    )


@dataclass
class _Transition:
    word: str
    frequency: float
    length: int  # target segments consumed
    cost: float
    segs: list[Seg]
    alignment: Alignment


def _freq_score(frequency: float) -> float:
    """Map a wordfreq value to a [0, 1] naturalness contribution."""
    if frequency <= 0:
        return 0.0
    return max(0.0, min(1.0, (math.log10(frequency) + 7.0) / 7.0))


def _position_transitions(
    conn: sqlite3.Connection,
    target: list[Seg],
    i: int,
    cand_per_pos: int,
    strictness: float,
    skip_words: set[str],
) -> list[_Transition]:
    """Candidate word transitions starting at target position ``i``."""
    n = len(target)
    target_ipa = [s.ipa for s in target]
    keys = onset_keys(target_ipa[i : i + 2])
    if not keys:
        return []

    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT l.written_form, l.frequency, p.arpabet, p.ipa_segments "
        f"FROM decode_onset d "
        f"JOIN pronunciation p ON p.id = d.pronunciation_id "
        f"JOIN lexeme l ON l.id = p.lexeme_id "
        f"WHERE d.onset_key IN ({placeholders}) "
        f"GROUP BY p.id",
        keys,
    ).fetchall()

    transitions: list[_Transition] = []
    for written_form, frequency, arpabet, ipa_segments in rows:
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
            alignment = align(cand_segs, target[i : i + length], strictness=strictness)
            transitions.append(
                _Transition(
                    word=written_form,
                    frequency=frequency or 0.0,
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
    use_cache: bool = True,
    conn: sqlite3.Connection | None = None,
) -> list[MultiwordResult]:
    """Return ranked multi-word sequences that sound like ``text``.

    ``anchor`` (0 = full-span, 1 = tail-anchored) blends the whole-tiling
    similarity with a rhyme-tail similarity so ``--anchor tail`` biases toward
    tilings whose ending matches the target's rhyme. Multi-word echoes are
    inherently full-span, so the default is ``0.0``.

    Results are cached (keyed on the phonetic params) unless ``use_cache`` is
    False or an explicit ``conn`` is supplied.
    """
    cache_key = None
    if use_cache and conn is None:
        cache_key = multiword_cache_key(
            text, limit, beam_width, cand_per_pos, max_words, min_words,
            strictness, anchor,
        )
        cached = cache_service.cache_get(cache_key)
        if cached is not None:
            return [_result_from_dict(d) for d in cached]

    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
    try:
        target = enriched_segments(text, conn=conn)
        n = len(target)
        if n == 0:
            return []

        input_tokens = tokenize(text)
        skip_words = {text.strip().lower()}

        # nodes[n] holds completed tilings; there are combinatorially many, so it
        # is capped (by cost) during the DP to bound memory. The final rerank is
        # by score (cost + naturalness), so keep it comfortably larger than limit.
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
                    conn, target, i, cand_per_pos, strictness, skip_words
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

        best_by_phrase: dict[str, MultiwordResult] = {}
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
                    target_tail, rhyme_tail(segs), strictness=strictness
                )
                similarity = (1.0 - anchor) * similarity + anchor * tail_similarity
            naturalness = sum(_freq_score(tr.frequency) for tr in steps) / len(steps)
            num_words = len(words)
            score = similarity + _W_NATURALNESS * naturalness - _W_WORDS * num_words
            stress_similarity = _stress_similarity(_stress_string(segs), target_stress)

            existing = best_by_phrase.get(phrase)
            if existing is None or score > existing.score:
                best_by_phrase[phrase] = MultiwordResult(
                    phrase=phrase,
                    words=words,
                    similarity=similarity,
                    stress_similarity=stress_similarity,
                    naturalness=naturalness,
                    num_words=num_words,
                    ipa="".join(s.ipa for s in segs),
                    score=score,
                    chunks=[(tr.word, tr.alignment) for tr in steps],
                )
    finally:
        if own_conn:
            conn.close()

    results = sorted(best_by_phrase.values(), key=lambda r: r.score, reverse=True)[
        :limit
    ]

    if cache_key is not None:
        cache_service.cache_put(cache_key, [_result_to_dict(r) for r in results])
    return results
