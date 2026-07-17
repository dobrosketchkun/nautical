"""Phase 6 tests: semantic vectors, theme reranking, and chains.

All tests use a tiny hand-built vector space - no network and no GloVe download.
"""

import numpy as np
import pytest

from nautical.search.words import RhymeResult
from nautical.search.ranking import ScoreComponents
from nautical.semantics import theme as theme_service
from nautical.semantics import vectors as vectors_service
from nautical.semantics.theme import apply_theme, parse_terms
from nautical.semantics.vectors import Vectors, VectorsUnavailable

# Three orthogonal "meaning" axes: marine, finance, other.
_SPACE = {
    "nautical": [1.0, 0.1, 0.0],
    "ocean": [1.0, 0.0, 0.1],
    "sea": [0.9, 0.1, 0.0],
    "ship": [1.0, 0.05, 0.05],
    "bank": [0.0, 1.0, 0.0],
    "money": [0.1, 1.0, 0.0],
    "currency": [0.0, 0.9, 0.1],
    "interest": [0.0, 1.0, 0.1],
    "cat": [0.0, 0.0, 1.0],
}


@pytest.fixture(scope="module")
def vecs() -> Vectors:
    return Vectors.from_mapping(_SPACE)


def _rhyme(word: str, similarity: float) -> RhymeResult:
    return RhymeResult(
        word=word,
        frequency=1e-5,
        syllable_count=2,
        ipa="",
        alignment=None,
        scores=ScoreComponents(
            phonetic_similarity=similarity,
            full_similarity=similarity,
            tail_similarity=similarity,
            stress_similarity=1.0,
            base_score=similarity,
            rank_score=similarity,
        ),
    )


def test_parse_terms():
    assert parse_terms("ocean, sea, ship") == ["ocean", "sea", "ship"]
    assert parse_terms("  Ocean   SEA ") == ["ocean", "sea"]


def test_vectors_get_normalized(vecs):
    v = vecs.get("ocean")
    assert v is not None
    assert np.isclose(np.linalg.norm(v), 1.0)
    assert vecs.get("NAUTICAL") is not None  # case-insensitive
    assert vecs.get("nonexistent") is None


def test_similarity_ordering(vecs):
    marine = vecs.similarity("ocean", "sea")
    cross = vecs.similarity("ocean", "bank")
    assert marine > cross
    assert vecs.similarity("ocean", "zzz") is None


def test_term_vector_unknown_skipped(vecs):
    v = vecs.term_vector(["bank", "zzz"])
    assert v is not None
    assert np.isclose(np.linalg.norm(v), 1.0)
    assert vecs.term_vector(["zzz", "qqq"]) is None


def test_most_similar_neighbors(vecs):
    seed = vecs.term_vector(["bank"])
    neighbors = [w for w, _ in vecs.most_similar(seed, topn=3, exclude={"bank"})]
    assert "bank" not in neighbors
    # The finance cluster should dominate the marine/other words.
    assert set(neighbors) <= {"money", "currency", "interest"}


def test_most_similar_allowed_mask(vecs):
    seed = vecs.term_vector(["bank"])
    allowed = {"money", "cat"}
    neighbors = [
        w
        for w, _ in vecs.most_similar(
            seed, topn=5, exclude={"bank"}, allowed=allowed
        )
    ]
    # Only allowed words come back, even though other finance words score higher.
    assert set(neighbors) <= allowed
    assert "money" in neighbors
    assert "currency" not in neighbors


def test_apply_theme_floats_relevant_word_up(vecs):
    # cat is phonetically "closer" but off-theme; nautical is on-theme.
    results = [_rhyme("cat", 0.9), _rhyme("nautical", 0.5)]
    reranked = apply_theme(
        results, ["ocean", "sea", "ship"], vecs, weight=0.8
    )
    assert reranked[0].word == "nautical"
    assert reranked[0].theme_fit > reranked[1].theme_fit


def test_apply_theme_min_theme_filters(vecs):
    results = [_rhyme("cat", 0.9), _rhyme("nautical", 0.5)]
    reranked = apply_theme(
        results, ["ocean", "sea", "ship"], vecs, weight=0.5, min_theme=0.3
    )
    words = [r.word for r in reranked]
    assert "nautical" in words
    assert "cat" not in words


def test_apply_theme_preserves_complete_base_score(vecs):
    cat = _rhyme("cat", 0.5)
    nautical = _rhyme("nautical", 0.5)
    cat.scores.base_score = cat.scores.rank_score = 1.5
    reranked = apply_theme([cat, nautical], ["ocean"], vecs, weight=0.1)
    assert reranked[0].word == "cat"
    assert reranked[0].rank_score > reranked[1].rank_score


def test_expand_seed_terms_keeps_seed_and_uses_allowed_neighbors(vecs):
    expanded = theme_service.expand_seed_terms(
        ["bank"], vecs, limit=2, allowed={"money", "currency", "cat"}
    )
    assert expanded[0] == "bank"
    assert set(expanded[1:]) <= {"money", "currency"}


def test_lexicon_guard_when_db_absent(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(VectorsUnavailable):
        vectors_service._lexicon_words(missing)
