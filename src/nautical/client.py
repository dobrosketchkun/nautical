"""Supported Python API for the Nautical engine."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar

from . import cache as cache_service
from . import eval as eval_service
from . import exclude as exclude_service
from . import pronounce as pronounce_service
from .config import SCHEMA_VERSION, NauticalPaths
from .db import loader
from .db.quality import DEFAULT_MIN_QUALITY
from .errors import NotInitializedError
from .phonetics import distance as distance_service
from .scoring_weights import (
    WEIGHTS_FILENAME,
    ScoringWeights,
    resolve_weights,
)
from .search import decoder as multiword_search
from .search import words as word_search
from .search.diversity import select_diverse
from .semantics import theme as theme_service
from .semantics import vectors as vectors_service

T = TypeVar("T")


@dataclass
class SearchResponse(Generic[T]):
    """Search results plus reproducibility and runtime metadata."""

    candidates: list[T]
    mode: str
    context_terms: list[str] = field(default_factory=list)
    cached: bool = False
    elapsed_ms: float = 0.0

    @property
    def results(self) -> list[T]:
        """Friendly alias used by callers that prefer ``response.results``."""
        return self.candidates


class Nautical:
    """Configurable facade for embedding Nautical in Python applications."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        weights: ScoringWeights | None = None,
        weights_path: str | Path | None = None,
    ) -> None:
        self.paths = NauticalPaths.resolve(data_dir)
        self.weights = resolve_weights(
            data_dir=self.paths.data_dir,
            weights_path=weights_path,
            weights=weights,
        )
        self._vectors: vectors_service.Vectors | None = None

    @property
    def weights_path(self) -> Path:
        return self.paths.data_dir / WEIGHTS_FILENAME

    @property
    def data_dir(self) -> Path:
        return self.paths.data_dir

    def _require_db(self) -> None:
        if not self.paths.db_path.exists():
            raise NotInitializedError(
                f"No lexicon database at {self.paths.db_path}. "
                "Call `engine.build_db()` or run `nautical db build`."
            )
        try:
            info = loader.get_stats(self.paths.db_path)
        except sqlite3.DatabaseError as exc:
            raise NotInitializedError(
                f"Lexicon database is not usable: {self.paths.db_path}. Rebuild it."
            ) from exc
        if info.get("schema_version") != SCHEMA_VERSION:
            raise NotInitializedError(
                f"Lexicon schema is {info.get('schema_version', 'missing')}; "
                f"version {SCHEMA_VERSION} is required. Rebuild the database."
            )

    def initialize(self, *, vectors: bool = False, force: bool = False) -> dict:
        """Prepare the lexicon and optionally the large semantic vector cache."""
        db_stats = self.build_db(force=force)
        result: dict = {"database": db_stats}
        if vectors:
            result["vectors"] = self.build_vectors(force=force)
        return result

    def build_db(self, *, force: bool = False) -> dict[str, int]:
        if self.paths.db_path.exists() and not force:
            self._require_db()
            info = loader.get_stats(self.paths.db_path)
            return {
                key: int(info.get(key, 0))
                for key in (
                    "lexeme_count",
                    "pronunciation_count",
                    "lexeme_with_frequency",
                    "lexeme_quality_ge_default",
                    "phoneme_ngram_count",
                    "decode_onset_count",
                    "rhyme_ngram_count",
                )
            }
        stats = loader.build_db(force=force, db_path=self.paths.db_path)
        cache_service.clear(self.paths.cache_db_path)
        return stats

    def stats(self) -> dict:
        self._require_db()
        return {
            "database": loader.get_stats(self.paths.db_path),
            "cache": cache_service.stats(self.paths.cache_db_path),
            "data_dir": str(self.paths.data_dir),
            "vectors_ready": vectors_service.vectors_ready(self.paths),
        }

    def clear_cache(self) -> int:
        return cache_service.clear(self.paths.cache_db_path)

    def cache_stats(self) -> dict:
        return cache_service.stats(self.paths.cache_db_path)

    def build_vectors(self, *, force: bool = False) -> dict[str, int]:
        self._require_db()
        stats = vectors_service.build_vectors(
            force=force,
            db_path=self.paths.db_path,
            paths=self.paths,
        )
        self._vectors = vectors_service.Vectors.load(self.paths)
        return stats

    def ensure_vectors(self) -> vectors_service.Vectors:
        self._require_db()
        if self._vectors is None:
            self._vectors = vectors_service.ensure_vectors(
                db_path=self.paths.db_path, paths=self.paths
            )
        return self._vectors

    def pronounce(self, text: str) -> pronounce_service.PhrasePronunciation:
        self._require_db()
        return pronounce_service.pronounce_phrase(text, db_path=self.paths.db_path)

    def distance(self, text_a: str, text_b: str, **kwargs):
        self._require_db()
        return distance_service.phonetic_distance(
            text_a, text_b, db_path=self.paths.db_path, **kwargs
        )

    @staticmethod
    def _terms(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return theme_service.parse_terms(value)
        return [str(term).strip().lower() for term in value if str(term).strip()]

    def _context_terms(
        self,
        theme: str | list[str] | None,
        seed: str | list[str] | None,
        seed_limit: int,
    ) -> tuple[list[str], vectors_service.Vectors | None]:
        terms = self._terms(theme)
        seeds = self._terms(seed)
        if not terms and not seeds:
            return [], None
        vectors = self.ensure_vectors()
        if seeds:
            allowed = vectors_service.lexicon_words(self.paths.db_path)
            expanded = theme_service.expand_seed_terms(
                seeds, vectors, limit=seed_limit, allowed=allowed
            )
            if not expanded:
                raise vectors_service.VectorsUnavailable(
                    f"None of the seed terms are in the vector vocabulary: "
                    f"{', '.join(seeds)}"
                )
            terms = list(dict.fromkeys([*terms, *expanded]))
        return terms, vectors

    def rhymes(
        self,
        text: str,
        *,
        limit: int = 25,
        pool: int = 1500,
        strictness: float = 0.5,
        anchor: float = 0.5,
        min_similarity: float = 0.0,
        theme: str | list[str] | None = None,
        seed: str | list[str] | None = None,
        seed_limit: int = 25,
        theme_weight: float | None = None,
        min_theme: float | None = None,
        include_self: bool = False,
        multiword: bool = False,
        beam_width: int = 300,
        max_words: int = 5,
        min_words: int = 2,
        word_boundary_leniency: bool = True,
        multi_variant: bool = True,
        exclude: str | frozenset[str] | None = None,
        diversity: float = 0.30,
        prefix_cap: int = 3,
        min_quality: float | None = None,
        thorough: bool = False,
        use_cache: bool = True,
    ) -> SearchResponse:
        self._require_db()
        if min_quality is None:
            min_quality = self.weights.min_quality
        if theme_weight is None:
            theme_weight = self.weights.theme_weight_default
        context_terms, vectors = self._context_terms(theme, seed, seed_limit)
        exclusions = (
            exclude
            if isinstance(exclude, frozenset)
            else exclude_service.resolve_exclusions(exclude, path=self.paths.exclude_path)
        )
        # Theme reorders after decode, so diversify after theme on a widened pool.
        # diversity <= 0 disables both MMR and the prefix cap (pure rank order).
        active_diversity = diversity if multiword and diversity > 0 else 0.0
        active_prefix_cap = prefix_cap if active_diversity > 0 else 0
        diversify_after_theme = bool(active_diversity > 0 and context_terms)
        decode_diversity = 0.0 if diversify_after_theme else active_diversity
        decode_prefix_cap = 0 if diversify_after_theme else active_prefix_cap

        fetch_limit = limit
        if context_terms:
            fetch_limit = max(limit, 100 if multiword else 200)
        if diversify_after_theme:
            fetch_limit = max(fetch_limit, limit * 10, 100)

        started = time.perf_counter()

        if multiword:
            candidates, was_cached = multiword_search.find_multiword(
                text,
                limit=fetch_limit,
                beam_width=beam_width,
                cand_per_pos=pool,
                max_words=max_words,
                min_words=min_words,
                strictness=strictness,
                anchor=anchor,
                word_boundary_leniency=word_boundary_leniency,
                exclude=exclusions,
                diversity=decode_diversity,
                prefix_cap=decode_prefix_cap,
                min_quality=min_quality,
                thorough=thorough,
                use_cache=use_cache,
                db_path=self.paths.db_path,
                cache_db_path=self.paths.cache_db_path,
                weights=self.weights,
            )
        else:
            candidates, was_cached = word_search.find_rhymes(
                text,
                limit=fetch_limit,
                pool=pool,
                strictness=strictness,
                anchor=anchor,
                include_self=include_self,
                word_boundary_leniency=word_boundary_leniency,
                multi_variant=multi_variant,
                exclude=exclusions,
                min_quality=min_quality,
                use_cache=use_cache,
                db_path=self.paths.db_path,
                cache_db_path=self.paths.cache_db_path,
                weights=self.weights,
            )
        if min_similarity > 0.0:
            candidates = [r for r in candidates if r.similarity >= min_similarity]
        if context_terms and vectors is not None:
            candidates = theme_service.apply_theme(
                candidates,
                context_terms,
                vectors,
                weight=theme_weight,
                min_theme=min_theme,
            )
        if diversify_after_theme:
            candidates = select_diverse(
                candidates,
                limit=limit,
                diversity=active_diversity,
                prefix_cap=active_prefix_cap,
            )
        else:
            candidates = candidates[:limit]
        return SearchResponse(
            candidates=candidates,
            mode="multiword" if multiword else "single",
            context_terms=context_terms,
            cached=was_cached,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )

    def rhymes_multiword(self, text: str, **kwargs) -> SearchResponse:
        kwargs["multiword"] = True
        kwargs.setdefault("anchor", 0.0)
        return self.rhymes(text, **kwargs)

    def chain(
        self, seed: str | list[str], *, limit: int = 25
    ) -> list[tuple[str, float]]:
        self._require_db()
        seeds = self._terms(seed)
        vectors = self.ensure_vectors()
        seed_vec = vectors.term_vector(seeds)
        if seed_vec is None:
            return []
        return vectors.most_similar(
            seed_vec,
            topn=limit,
            exclude=set(seeds),
            allowed=vectors_service.lexicon_words(self.paths.db_path),
        )

    def evaluate(
        self,
        *,
        pairs_path: str | Path | None = None,
        limit: int = 50,
        use_cache: bool = True,
        weights: ScoringWeights | None = None,
    ) -> eval_service.EvalReport:
        self._require_db()
        active = weights if weights is not None else self.weights
        pairs = eval_service.load_pairs(Path(pairs_path) if pairs_path else None)
        vectors = self.ensure_vectors() if any(p.get("theme") for p in pairs) else None
        return eval_service.run_eval(
            pairs,
            limit=limit,
            use_cache=use_cache,
            vectors=vectors,
            db_path=self.paths.db_path,
            cache_db_path=self.paths.cache_db_path,
            weights=active,
        )
