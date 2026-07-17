"""Phase 9 tests for coherent score composition and boundary surprise."""

import pytest

from nautical.phonetics.align import Seg, align
from nautical.phonetics.anchor import boundary_surprise
from nautical.search.ranking import apply_context_score, rank_base


def _seg(ipa: str, *, final: bool = False) -> Seg:
    return Seg(ipa=ipa, is_vowel=ipa in {"ɑ", "ə", "ʌ", "ɔ"}, word_final=final)


def test_boundary_surprise_same_segmentation_is_zero():
    left = [_seg("n"), _seg("ɑ", final=True), _seg("t")]
    right = [_seg("n"), _seg("ɔ", final=True), _seg("t")]
    assert boundary_surprise(align(left, right)) == 0.0


def test_boundary_surprise_detects_phrase_to_word_resegmentation():
    phrase = [
        _seg("n"),
        _seg("ɑ"),
        _seg("t", final=True),
        _seg("ə", final=True),
        _seg("k"),
        _seg("ʌ"),
        _seg("l"),
        _seg("t", final=True),
    ]
    word = [
        _seg("n"),
        _seg("ɔ"),
        _seg("t"),
        _seg("ə"),
        _seg("k"),
        _seg("ə"),
        _seg("l", final=True),
    ]
    assert boundary_surprise(align(phrase, word)) >= 0.5


def test_stress_and_boundary_are_real_base_ranking_signals():
    baseline = rank_base(0.8, 0.0, 0.0)
    assert rank_base(0.8, 1.0, 0.0) > baseline
    assert rank_base(0.8, 0.0, 1.0) > baseline


def test_context_blends_with_complete_base_score():
    assert apply_context_score(1.4, -1.0, 0.2) == pytest.approx(1.12)
