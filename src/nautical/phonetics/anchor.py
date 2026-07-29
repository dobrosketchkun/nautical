"""Anchoring: tail-anchored vs full-span phonetic comparison.

Two ways to judge how alike two sounds are:

* **Full-span** - align the whole sequences (Phase 2 behavior).
* **Tail-anchored** - align only the rhyme tails (last stressed vowel to the
  end). This makes onset differences irrelevant, so perfect end-rhymes like
  ``stainless`` / ``painless`` score ~1.0 regardless of their onsets - the
  principled fix for the Phase 3 onset-gap ranking issue.

A single ``anchor`` dial in ``[0, 1]`` slides between them (0 = full-span,
1 = tail-anchored); both are always computed so results can be re-sorted freely.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phonology.arpabet import is_vowel
from .align import Alignment, Seg
from ..scoring_weights import ScoringWeights
from .distance import score_segments


def segs_from_stored(arpabet: str, ipa_segments: str) -> list[Seg]:
    """Rebuild enriched ``Seg``s from a stored pronunciation row.

    Shared by the single-word search, the decoder, the loader, and anchoring so
    every caller derives per-segment stress/vowel-ness identically.
    """
    phones = arpabet.split(" ") if arpabet else []
    segments = ipa_segments.split(" ") if ipa_segments else []
    result: list[Seg] = []
    for phone, ipa_segment in zip(phones, segments):
        stress = phone[-1] if phone and phone[-1].isdigit() else ""
        result.append(Seg(ipa=ipa_segment, stress=stress, is_vowel=is_vowel(phone)))
    # A stored pronunciation is a single word; its last segment is word-final.
    if result:
        result[-1].word_final = True
    return result


def rhyme_tail(segs: list[Seg]) -> list[Seg]:
    """Return the rhyme tail: from the last stressed vowel to the end.

    Falls back to the last vowel if nothing carries stress, and to the whole
    sequence if there are no vowels at all.
    """
    if not segs:
        return []

    last_stressed = -1
    last_vowel = -1
    for i, seg in enumerate(segs):
        if seg.is_vowel:
            last_vowel = i
            if seg.stressed:
                last_stressed = i

    start = last_stressed if last_stressed >= 0 else last_vowel
    if start < 0:
        return list(segs)
    return list(segs[start:])


def _internal_boundary_columns(alignment: Alignment, side: str) -> set[int]:
    """Return aligned columns after which ``side`` has an internal word boundary."""
    attr = "src" if side == "src" else "tgt"
    occupied = [
        i for i, pair in enumerate(alignment.pairs) if getattr(pair, attr) is not None
    ]
    if not occupied:
        return set()
    final_column = occupied[-1]
    return {
        i
        for i, pair in enumerate(alignment.pairs)
        if i != final_column
        and (seg := getattr(pair, attr)) is not None
        and seg.word_final
    }


def boundary_surprise(alignment: Alignment) -> float:
    """Measure how much internal word segmentation moved across an alignment.

    Boundaries are compared in aligned phoneme-column space. The mandatory final
    sequence boundary is ignored. Jaccard distance gives 0 for the same
    segmentation and 1 when all internal boundaries differ.
    """
    source = _internal_boundary_columns(alignment, "src")
    target = _internal_boundary_columns(alignment, "tgt")
    union = source | target
    if not union:
        return 0.0
    return len(source ^ target) / len(union)


@dataclass
class AnchoredScore:
    full_similarity: float
    tail_similarity: float
    anchored_similarity: float
    stress_similarity: float
    full_alignment: Alignment
    tail_alignment: Alignment


def anchored_score(
    target_segs: list[Seg],
    cand_segs: list[Seg],
    anchor: float = 0.5,
    strictness: float = 0.5,
    word_boundary_leniency: bool = True,
    weights: ScoringWeights | None = None,
) -> AnchoredScore:
    """Score two segment sequences under the anchor dial.

    ``anchored_similarity = (1 - anchor) * full + anchor * tail``.
    """
    full_similarity, stress_similarity, full_alignment = score_segments(
        target_segs,
        cand_segs,
        strictness=strictness,
        word_boundary_leniency=word_boundary_leniency,
        weights=weights,
    )
    tail_similarity, _, tail_alignment = score_segments(
        rhyme_tail(target_segs),
        rhyme_tail(cand_segs),
        strictness=strictness,
        word_boundary_leniency=word_boundary_leniency,
        weights=weights,
    )
    anchored = (1.0 - anchor) * full_similarity + anchor * tail_similarity
    return AnchoredScore(
        full_similarity=full_similarity,
        tail_similarity=tail_similarity,
        anchored_similarity=anchored,
        stress_similarity=stress_similarity,
        full_alignment=full_alignment,
        tail_alignment=tail_alignment,
    )
