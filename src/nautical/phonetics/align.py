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

from .features import feature_distance


@dataclass
class Seg:
    ipa: str
    stress: str = ""  # "0" / "1" / "2" or "" for consonants
    is_vowel: bool = False

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
                else [p.src.ipa, p.src.stress, p.src.is_vowel],
                "tgt": None
                if p.tgt is None
                else [p.tgt.ipa, p.tgt.stress, p.tgt.is_vowel],
                "op": p.op,
                "cost": p.cost,
            }
            for p in alignment.pairs
        ],
    }


def alignment_from_dict(data: dict) -> Alignment:
    """Rebuild an Alignment from :func:`alignment_to_dict` output."""

    def _seg(v: list | None) -> Seg | None:
        return None if v is None else Seg(ipa=v[0], stress=v[1], is_vowel=v[2])

    pairs = [
        AlignedPair(src=_seg(p["src"]), tgt=_seg(p["tgt"]), op=p["op"], cost=p["cost"])
        for p in data["pairs"]
    ]
    return Alignment(pairs=pairs, total_cost=data["total_cost"])


def _strictness_scale(strictness: float) -> float:
    # 0.0 -> 0.6 (forgiving), 0.5 -> 1.0, 1.0 -> 1.4 (strict)
    return 0.6 + 0.8 * strictness


def _sub_cost(a: Seg, b: Seg, strictness: float) -> float:
    distance = feature_distance(a.ipa, b.ipa)
    if distance == 0.0:
        return 0.0
    if a.is_vowel and b.is_vowel:
        multiplier = 1.6 if (a.stressed or b.stressed) else 0.35
    else:
        multiplier = 1.0
    return distance * multiplier * _strictness_scale(strictness)


def _gap_cost(seg: Seg, strictness: float, is_final: bool) -> float:
    if seg.is_vowel and not seg.stressed:
        base = 0.3
    elif not seg.is_vowel and is_final:
        base = 0.4
    elif seg.is_vowel and seg.stressed:
        base = 1.1
    else:
        base = 0.9
    return base * _strictness_scale(strictness)


def align(a: list[Seg], b: list[Seg], strictness: float = 0.5) -> Alignment:
    n, m = len(a), len(b)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[""] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + _gap_cost(a[i - 1], strictness, is_final=(i == n))
        back[i][0] = "del"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + _gap_cost(b[j - 1], strictness, is_final=(j == m))
        back[0][j] = "ins"

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + _sub_cost(a[i - 1], b[j - 1], strictness)
            delete = dp[i - 1][j] + _gap_cost(a[i - 1], strictness, is_final=(i == n))
            insert = dp[i][j - 1] + _gap_cost(b[j - 1], strictness, is_final=(j == m))
            best = min(diag, delete, insert)
            dp[i][j] = best
            back[i][j] = "diag" if best == diag else ("del" if best == delete else "ins")

    pairs: list[AlignedPair] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move == "diag":
            src, tgt = a[i - 1], b[j - 1]
            cost = _sub_cost(src, tgt, strictness)
            op = "match" if feature_distance(src.ipa, tgt.ipa) == 0.0 else "sub"
            pairs.append(AlignedPair(src, tgt, op, cost))
            i, j = i - 1, j - 1
        elif move == "del":
            src = a[i - 1]
            pairs.append(
                AlignedPair(src, None, "del", _gap_cost(src, strictness, is_final=(i == n)))
            )
            i -= 1
        else:  # ins
            tgt = b[j - 1]
            pairs.append(
                AlignedPair(None, tgt, "ins", _gap_cost(tgt, strictness, is_final=(j == m)))
            )
            j -= 1

    pairs.reverse()
    return Alignment(pairs=pairs, total_cost=dp[n][m])
