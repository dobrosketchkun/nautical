"""Phrase plausibility for multi-word naturalness (U1.4 Level 1).

Replaces arithmetic unigram-frequency naturalness with an explainable blend of
geometric frequency, a Penn-tag POS trigram LM, and a function-word saturation
penalty.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

FREQ_GEOM_WEIGHT = 0.40
POS_PLAUS_WEIGHT = 0.45
FUNCTION_OK_WEIGHT = 0.15

_FREQ_EPS = 1e-6
_ADD_K = 0.01
_LOG_FLOOR = math.log(1e-6)
_UNK = "UNK"
_BOS = "<s>"
# ≥2/3 closed-class catches 3-word "no to X" tilings (plan's 0.8 never fires on n=3).
CLOSED_FRAC_THRESHOLD = 2.0 / 3.0

CLOSED_CLASS_TAGS = frozenset(
    {
        "DT",
        "IN",
        "TO",
        "CC",
        "PRP",
        "PRP$",
        "MD",
        "RB",
        "WRB",
        "WP",
        "WP$",
        "WDT",
        "EX",
        "PDT",
        "POS",
        "RP",
        "UH",
    }
)

# Isolation POS tags miss some glue spellings ('cause → NN). Lemma backup for
# the highest-frequency closed-class English words that dominate junk tilings.
CLOSED_FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "no",
        "not",
        "so",
        "as",
        "at",
        "by",
        "up",
        "out",
        "if",
        "is",
        "are",
        "be",
        "was",
        "were",
        "do",
        "did",
        "can",
        "could",
        "would",
        "should",
        "will",
        "may",
        "might",
        "must",
        "from",
        "with",
        "this",
        "that",
        "it",
        "its",
        "'cause",
        "cause",
        "because",
        "than",
        "then",
        "too",
        "very",
        "just",
        "about",
        "into",
        "over",
        "after",
        "before",
        "all",
        "any",
        "some",
        "such",
        "nor",
        "yet",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "own",
        "same",
        "than",
        "too",
        "very",
        "s",
        "t",
        "don",
        "re",
        "ve",
        "ll",
        "d",
        "m",
    }
)


def is_closed_token(word: str, tag: str) -> bool:
    """True if the token is closed-class by tag or high-frequency glue lemma."""
    if tag in CLOSED_CLASS_TAGS:
        return True
    lowered = word.lower()
    return lowered in CLOSED_FUNCTION_WORDS or lowered.strip("'") in CLOSED_FUNCTION_WORDS


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def freq_score(frequency: float) -> float:
    """Map a wordfreq value to a [0, 1] frequency contribution."""
    if frequency <= 0:
        return 0.0
    return max(0.0, min(1.0, (math.log10(frequency) + 7.0) / 7.0))


def geometric_freq(frequencies: Sequence[float]) -> float:
    """Geometric mean of per-word ``freq_score`` values."""
    if not frequencies:
        return 0.0
    logs = [math.log(max(freq_score(f), _FREQ_EPS)) for f in frequencies]
    return math.exp(sum(logs) / len(logs))


def function_ok(tags: Sequence[str], words: Sequence[str] | None = None) -> float:
    """1.0 unless ≥2/3 of tokens are closed-class, then ``1 - closed_frac``."""
    if not tags:
        return 1.0
    if words is None or len(words) != len(tags):
        closed = sum(1 for t in tags if t in CLOSED_CLASS_TAGS)
    else:
        closed = sum(1 for w, t in zip(words, tags) if is_closed_token(w, t))
    closed_frac = closed / len(tags)
    if closed_frac >= CLOSED_FRAC_THRESHOLD:
        return 1.0 - closed_frac
    return 1.0


def normalize_tag(tag: str | None) -> str:
    if not tag:
        return _UNK
    return tag


@dataclass
class PosTagLM:
    """In-memory POS n-gram LM with trigram→bigram→unigram backoff."""

    # (order_n, context) -> {tag: log_prob}
    tables: dict[tuple[int, str], dict[str, float]]
    vocab_size: int

    def log_prob(self, tag: str, history: Sequence[str]) -> float:
        tag = normalize_tag(tag)
        hist = [normalize_tag(t) for t in history]
        if len(hist) >= 2:
            ctx = f"{hist[-2]} {hist[-1]}"
            tri = self.tables.get((3, ctx))
            if tri and tag in tri:
                return tri[tag]
        if len(hist) >= 1:
            ctx = hist[-1]
            bi = self.tables.get((2, ctx))
            if bi and tag in bi:
                return bi[tag]
        uni = self.tables.get((1, ""))
        if uni and tag in uni:
            return uni[tag]
        return math.log(1.0 / max(self.vocab_size, 1))

    def mean_log_prob(self, tags: Sequence[str]) -> float:
        if not tags:
            return _LOG_FLOOR
        normed = [normalize_tag(t) for t in tags]
        total = 0.0
        history: list[str] = [_BOS, _BOS]
        for tag in normed:
            total += self.log_prob(tag, history)
            history.append(tag)
        return total / len(normed)

    def pos_plausibility(self, tags: Sequence[str]) -> float:
        mean_log = self.mean_log_prob(tags)
        if _LOG_FLOOR >= 0:
            return 1.0
        return clamp((mean_log - _LOG_FLOOR) / (0.0 - _LOG_FLOOR))


def phrase_naturalness(
    frequencies: Sequence[float],
    tags: Sequence[str],
    lm: PosTagLM | None,
    words: Sequence[str] | None = None,
) -> tuple[float, float, float, float]:
    """Return ``(naturalness, freq_geom, pos_plaus, function_ok)``.

    When a tiling is function-word saturated (≥2/3 closed-class tokens),
    ``naturalness`` is capped by ``function_ok`` so pure glue phrases cannot
    keep a high Nat score from frequency alone.
    """
    freq_geom = geometric_freq(frequencies)
    func = function_ok(tags, words)
    if lm is None:
        pos_plaus = 0.5
    else:
        pos_plaus = lm.pos_plausibility(tags)
    naturalness = (
        FREQ_GEOM_WEIGHT * freq_geom
        + POS_PLAUS_WEIGHT * pos_plaus
        + FUNCTION_OK_WEIGHT * func
    )
    if func < 1.0:
        naturalness = min(naturalness, func)
    return naturalness, freq_geom, pos_plaus, func


def ensure_nltk_treebank() -> None:
    """Ensure the Penn Treebank corpus is available (download once if needed)."""
    import nltk

    try:
        nltk.data.find("corpora/treebank")
        return
    except LookupError:
        pass
    nltk.download("treebank", quiet=True)
    nltk.data.find("corpora/treebank")


def build_pos_lm_rows(*, add_k: float = _ADD_K) -> list[tuple[int, str, str, float]]:
    """Count Treebank tag n-grams and return smoothed ``pos_lm`` rows."""
    from nltk.corpus import treebank

    ensure_nltk_treebank()
    uni: dict[str, float] = defaultdict(float)
    bi: dict[tuple[str, str], float] = defaultdict(float)
    tri: dict[tuple[str, str, str], float] = defaultdict(float)

    for sent in treebank.tagged_sents():
        tags = [_BOS, _BOS] + [normalize_tag(tag) for _, tag in sent]
        for i in range(2, len(tags)):
            t0, t1, t2 = tags[i - 2], tags[i - 1], tags[i]
            uni[t2] += 1.0
            bi[(t1, t2)] += 1.0
            tri[(t0, t1, t2)] += 1.0

    vocab = sorted(uni.keys())
    v = max(len(vocab), 1)
    rows: list[tuple[int, str, str, float]] = []

    uni_total = sum(uni.values()) + add_k * v
    for tag, count in uni.items():
        rows.append((1, "", tag, math.log((count + add_k) / uni_total)))

    bi_context_totals: dict[str, float] = defaultdict(float)
    for (t1, _t2), count in bi.items():
        bi_context_totals[t1] += count
    for (t1, t2), count in bi.items():
        denom = bi_context_totals[t1] + add_k * v
        rows.append((2, t1, t2, math.log((count + add_k) / denom)))

    tri_context_totals: dict[tuple[str, str], float] = defaultdict(float)
    for (t0, t1, _t2), count in tri.items():
        tri_context_totals[(t0, t1)] += count
    for (t0, t1, t2), count in tri.items():
        denom = tri_context_totals[(t0, t1)] + add_k * v
        rows.append((3, f"{t0} {t1}", t2, math.log((count + add_k) / denom)))

    return rows


def write_pos_lm(conn: sqlite3.Connection) -> int:
    """Build the Treebank POS LM and insert into ``pos_lm``. Returns row count."""
    conn.execute("DELETE FROM pos_lm")
    rows = build_pos_lm_rows()
    conn.executemany(
        "INSERT INTO pos_lm(order_n, context, tag, log_prob) VALUES (?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def load_pos_lm(conn: sqlite3.Connection) -> PosTagLM:
    """Load ``pos_lm`` rows into an in-memory ``PosTagLM``."""
    tables: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    vocab: set[str] = set()
    for order_n, context, tag, log_prob in conn.execute(
        "SELECT order_n, context, tag, log_prob FROM pos_lm"
    ):
        tables[(int(order_n), context)][tag] = float(log_prob)
        vocab.add(tag)
    return PosTagLM(tables=dict(tables), vocab_size=max(len(vocab), 1))


def load_pos_lm_from_rows(
    rows: Iterable[tuple[int, str, str, float]],
) -> PosTagLM:
    """Build a ``PosTagLM`` from explicit rows (for unit tests)."""
    tables: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    vocab: set[str] = set()
    for order_n, context, tag, log_prob in rows:
        tables[(int(order_n), context)][tag] = float(log_prob)
        vocab.add(tag)
    return PosTagLM(tables=dict(tables), vocab_size=max(len(vocab), 1))
