"""Evaluation harness.

Replays a curated corpus of known lyric pairs through the search engine and
reports whether each expected match is rediscovered and at what rank. This makes
the calibration debts in ``docs/NOTES.md`` measurable rather than anecdotal.

The packaged ``nautical.resources/eval_pairs.json`` corpus is hand-verified
ground truth. Callers may supply a custom JSON path.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from .search import decoder as multiword_search
from .search import words as word_search

DEFAULT_PAIRS_PATH = files("nautical.resources").joinpath("eval_pairs.json")


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for match comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_anchor(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    token = str(value).strip().lower()
    if token == "tail":
        return 1.0
    if token == "full":
        return 0.0
    try:
        return max(0.0, min(1.0, float(token)))
    except ValueError:
        return default


@dataclass
class EvalRow:
    query: str
    expected: str
    mode: str
    anchor: str
    theme: str | None
    found: bool
    rank: int | None
    similarity: float | None
    rank_score: float | None
    boundary_surprise: float | None
    theme_fit: float | None
    note: str | None = None


@dataclass
class EvalReport:
    rows: list[EvalRow] = field(default_factory=list)
    limit: int = 50

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def hits(self) -> int:
        return sum(1 for r in self.rows if r.rank is not None)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def mrr(self) -> float:
        if not self.rows:
            return 0.0
        return sum((1.0 / r.rank) if r.rank else 0.0 for r in self.rows) / len(self.rows)

    @property
    def median_rank(self) -> float | None:
        ranks = [r.rank for r in self.rows if r.rank is not None]
        return statistics.median(ranks) if ranks else None


def load_pairs(path: Path | None = None) -> list[dict]:
    """Load the pair list from a corpus JSON file (keys starting with '_' skipped)."""
    source = Path(path) if path is not None else DEFAULT_PAIRS_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("pairs", []))
    return list(data)


def _rank_of(results: list, expected: str, attr: str) -> tuple[int | None, object | None]:
    target = _normalize(expected)
    for i, r in enumerate(results, start=1):
        if _normalize(getattr(r, attr)) == target:
            return i, r
    return None, None


def evaluate_pair(
    pair: dict,
    limit: int = 50,
    use_cache: bool = True,
    conn: sqlite3.Connection | None = None,
    vectors=None,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
) -> EvalRow:
    """Run one pair through the engine and locate the expected match's rank."""
    query = pair["query"]
    expected = pair["expected"]
    mode = pair.get("mode", "single")
    anchor_raw = pair.get("anchor")
    theme = pair.get("theme")
    theme_terms = _theme_terms(theme)
    apply_theme = bool(theme_terms) and vectors is not None
    fetch_limit = max(limit, 200) if apply_theme else limit

    if mode == "multiword":
        anchor = _parse_anchor(anchor_raw, default=0.0)
        results = multiword_search.find_multiword(
            query,
            limit=fetch_limit,
            anchor=anchor,
            diversity=0.0,
            prefix_cap=0,
            use_cache=use_cache,
            db_path=db_path,
            cache_db_path=cache_db_path,
            conn=conn,
        )
        match_attr = "phrase"
    else:
        anchor = _parse_anchor(anchor_raw, default=0.5)
        results = word_search.find_rhymes(
            query,
            limit=fetch_limit,
            anchor=anchor,
            use_cache=use_cache,
            db_path=db_path,
            cache_db_path=cache_db_path,
            conn=conn,
        )
        match_attr = "word"

    if apply_theme:
        from .semantics.theme import apply_theme as _rerank

        results = _rerank(results, theme_terms, vectors)
    results = results[:limit]

    rank, hit = _rank_of(results, expected, match_attr)
    similarity = getattr(hit, "similarity", None) if hit is not None else None
    rank_score = getattr(hit, "rank_score", None) if hit is not None else None
    boundary = getattr(hit, "boundary_surprise", None) if hit is not None else None
    theme_fit = getattr(hit, "theme_fit", None) if hit is not None else None
    return EvalRow(
        query=query,
        expected=expected,
        mode=mode,
        anchor=str(anchor_raw) if anchor_raw is not None else "-",
        theme=theme,
        found=rank is not None,
        rank=rank,
        similarity=similarity,
        rank_score=rank_score,
        boundary_surprise=boundary,
        theme_fit=theme_fit,
        note=pair.get("note"),
    )


def _theme_terms(theme: str | None) -> list[str]:
    if not theme:
        return []
    from .semantics.theme import parse_terms

    return parse_terms(theme)


def run_eval(
    pairs: list[dict],
    limit: int = 50,
    use_cache: bool = True,
    conn: sqlite3.Connection | None = None,
    vectors=None,
    db_path: Path | None = None,
    cache_db_path: Path | None = None,
) -> EvalReport:
    """Evaluate every pair and return per-pair rows plus aggregates."""
    report = EvalReport(limit=limit)
    for pair in pairs:
        report.rows.append(
            evaluate_pair(
                pair,
                limit=limit,
                use_cache=use_cache,
                conn=conn,
                vectors=vectors,
                db_path=db_path,
                cache_db_path=cache_db_path,
            )
        )
    return report
