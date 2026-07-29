"""Weighted Needleman-Wunsch alignment over phonetic segments.

The base substitution cost is PanPhon feature distance; on top of that we apply
lyric-aware, stress-aware weights so that the edits people actually tolerate in
performed rhyme are cheap:

* unstressed-vowel / schwa substitution -> cheap
* schwa or unstressed-vowel insertion/deletion -> cheap
* sequence-final consonant deletion -> cheap
* stressed-vowel mismatch -> expensive

A ``strictness`` dial in ``[0, 1]`` scales all mismatch/gap costs (higher = less
forgiving). The alignment itself is returned so it can be shown as the
explanation.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..scoring_weights import DEFAULT_WEIGHTS, ScoringWeights
from .features import feature_distance


@dataclass
class Seg:
    ipa: str
    stress: str = ""  # "0" / "1" / "2" or "" for consonants
    is_vowel: bool = False
    word_final: bool = False  # last segment of its word (for boundary leniency)

    @property
    def stressed(self) -> bool:
        return self.stress in ("1", "2")


@dataclass
class AlignedPair:
    src: Seg | None
    tgt: Seg | None
    op: str  # "match" | "sub" | "ins" | "del"
    cost: float


@dataclass
class Alignment:
    pairs: list[AlignedPair]
    total_cost: float

    def pretty(self) -> str:
        symbols = {"match": "=", "sub": "~", "ins": "+", "del": "x"}
        top, mid, bot = [], [], []
        for pair in self.pairs:
            src = pair.src.ipa if pair.src else "-"
            tgt = pair.tgt.ipa if pair.tgt else "-"
            width = max(len(src), len(tgt), 1)
            top.append(src.ljust(width))
            mid.append(symbols[pair.op].ljust(width))
            bot.append(tgt.ljust(width))
        return (
            "A: " + " ".join(top) + "\n"
            + "   " + " ".join(mid) + "\n"
            + "B: " + " ".join(bot)
        )


def alignment_to_dict(alignment: Alignment) -> dict:
    """Serialize an Alignment to a JSON-friendly dict (for the result cache)."""
    return {
        "total_cost": alignment.total_cost,
        "pairs": [
            {
                "src": None
                if p.src is None
                else [p.src.ipa, p.src.stress, p.src.is_vowel, p.src.word_final],
                "tgt": None
                if p.tgt is None
                else [p.tgt.ipa, p.tgt.stress, p.tgt.is_vowel, p.tgt.word_final],
                "op": p.op,
                "cost": p.cost,
            }
            for p in alignment.pairs
        ],
    }


def alignment_from_dict(data: dict) -> Alignment:
    """Rebuild an Alignment from :func:`alignment_to_dict` output."""

    def _seg(v: list | None) -> Seg | None:
        if v is None:
            return None
        # Back-compat: older cached payloads lack the word_final field.
        word_final = v[3] if len(v) > 3 else False
        return Seg(ipa=v[0], stress=v[1], is_vowel=v[2], word_final=word_final)

    pairs = [
        AlignedPair(src=_seg(p["src"]), tgt=_seg(p["tgt"]), op=p["op"], cost=p["cost"])
        for p in data["pairs"]
    ]
    return Alignment(pairs=pairs, total_cost=data["total_cost"])


def _strictness_scale(
    strictness: float, weights: ScoringWeights = DEFAULT_WEIGHTS
) -> float:
    # Defaults: 0.0 -> 0.6 (forgiving), 0.5 -> 1.0, 1.0 -> 1.4 (strict)
    return weights.strictness_base + weights.strictness_span * strictness


def _sub_cost(
    a: Seg,
    b: Seg,
    strictness: float,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> float:
    distance = feature_distance(a.ipa, b.ipa)
    if distance == 0.0:
        return 0.0
    if a.is_vowel and b.is_vowel:
        multiplier = (
            weights.vowel_stressed_mult
            if (a.stressed or b.stressed)
            else weights.vowel_unstressed_mult
        )
    else:
        multiplier = 1.0
    return distance * multiplier * _strictness_scale(strictness, weights)


def _gap_cost(
    seg: Seg,
    strictness: float,
    is_final: bool,
    word_boundary_leniency: bool = True,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> float:
    # A trailing consonant is cheap to drop at the end of the whole sequence and,
    # when leniency is on, at any word boundary (singers routinely elide them,
    # e.g. the /t/ in "not a cult").
    cheap_consonant = not seg.is_vowel and (
        is_final or (word_boundary_leniency and seg.word_final)
    )
    if seg.is_vowel and not seg.stressed:
        base = weights.gap_unstressed_vowel
    elif cheap_consonant:
        base = weights.gap_cheap_consonant
    elif seg.is_vowel and seg.stressed:
        base = weights.gap_stressed_vowel
    else:
        base = weights.gap_other
    return base * _strictness_scale(strictness, weights)


def align(
    a: list[Seg],
    b: list[Seg],
    strictness: float = 0.5,
    word_boundary_leniency: bool = True,
    weights: ScoringWeights | None = None,
) -> Alignment:
    w = weights if weights is not None else DEFAULT_WEIGHTS
    n, m = len(a), len(b)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[""] * (m + 1) for _ in range(n + 1)]

    def gap(seg: Seg, is_final: bool) -> float:
        return _gap_cost(seg, strictness, is_final, word_boundary_leniency, w)

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap(a[i - 1], is_final=(i == n))
        back[i][0] = "del"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap(b[j - 1], is_final=(j == m))
        back[0][j] = "ins"

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + _sub_cost(a[i - 1], b[j - 1], strictness, w)
            delete = dp[i - 1][j] + gap(a[i - 1], is_final=(i == n))
            insert = dp[i][j - 1] + gap(b[j - 1], is_final=(j == m))
            best = min(diag, delete, insert)
            dp[i][j] = best
            back[i][j] = "diag" if best == diag else ("del" if best == delete else "ins")

    pairs: list[AlignedPair] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move == "diag":
            src, tgt = a[i - 1], b[j - 1]
            cost = _sub_cost(src, tgt, strictness, w)
            op = "match" if feature_distance(src.ipa, tgt.ipa) == 0.0 else "sub"
            pairs.append(AlignedPair(src, tgt, op, cost))
            i, j = i - 1, j - 1
        elif move == "del":
            src = a[i - 1]
            pairs.append(AlignedPair(src, None, "del", gap(src, is_final=(i == n))))
            i -= 1
        else:  # ins
            tgt = b[j - 1]
            pairs.append(AlignedPair(None, tgt, "ins", gap(tgt, is_final=(j == m))))
            j -= 1

    pairs.reverse()
    return Alignment(pairs=pairs, total_cost=dp[n][m])


def align_cost(
    a: list[Seg],
    b: list[Seg],
    strictness: float = 0.5,
    word_boundary_leniency: bool = True,
    weights: ScoringWeights | None = None,
) -> float:
    """Return only the total alignment cost (no traceback).

    Same DP recurrence as :func:`align`, using a flat cost buffer. Used by the
    multi-word beam, which only needs a number until final explanations.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return 0.0
    cols = m + 1
    dp = [0.0] * ((n + 1) * cols)

    def at(i: int, j: int) -> int:
        return i * cols + j

    def gap(seg: Seg, is_final: bool) -> float:
        return _gap_cost(seg, strictness, is_final, word_boundary_leniency, w)

    for i in range(1, n + 1):
        dp[at(i, 0)] = dp[at(i - 1, 0)] + gap(a[i - 1], is_final=(i == n))
    for j in range(1, m + 1):
        dp[at(0, j)] = dp[at(0, j - 1)] + gap(b[j - 1], is_final=(j == m))

    for i in range(1, n + 1):
        row = i * cols
        prev = (i - 1) * cols
        ai = a[i - 1]
        a_final = i == n
        for j in range(1, m + 1):
            diag = dp[prev + j - 1] + _sub_cost(ai, b[j - 1], strictness, w)
            delete = dp[prev + j] + gap(ai, is_final=a_final)
            insert = dp[row + j - 1] + gap(b[j - 1], is_final=(j == m))
            dp[row + j] = diag if diag <= delete and diag <= insert else (
                delete if delete <= insert else insert
            )

    return dp[at(n, m)]
