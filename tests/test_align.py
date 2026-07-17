"""Phase 8 tests: word-boundary consonant leniency in the aligner."""

from nautical.phonetics.align import Seg, _gap_cost, align


def test_word_final_consonant_cheap_with_leniency():
    seg = Seg(ipa="t", is_vowel=False, word_final=True)
    cheap = _gap_cost(seg, 0.5, is_final=False, word_boundary_leniency=True)
    strict = _gap_cost(seg, 0.5, is_final=False, word_boundary_leniency=False)
    assert cheap < strict


def test_non_word_final_consonant_not_cheapened():
    internal = Seg(ipa="t", is_vowel=False, word_final=False)
    final = Seg(ipa="t", is_vowel=False, word_final=True)
    assert _gap_cost(final, 0.5, is_final=False, word_boundary_leniency=True) < _gap_cost(
        internal, 0.5, is_final=False, word_boundary_leniency=True
    )


def test_leniency_off_matches_old_word_internal_cost():
    # With leniency off, a word-final consonant costs the same as any internal one.
    final = Seg(ipa="t", is_vowel=False, word_final=True)
    internal = Seg(ipa="t", is_vowel=False, word_final=False)
    assert _gap_cost(
        final, 0.5, is_final=False, word_boundary_leniency=False
    ) == _gap_cost(internal, 0.5, is_final=False, word_boundary_leniency=False)


def test_align_threads_leniency_into_total_cost():
    # Deleting a word-final /t/ mid-sequence is cheaper when leniency is on.
    a = [
        Seg(ipa="n", is_vowel=False),
        Seg(ipa="ɔ", stress="1", is_vowel=True),
        Seg(ipa="t", is_vowel=False, word_final=True),
        Seg(ipa="k", is_vowel=False),
    ]
    b = [
        Seg(ipa="n", is_vowel=False),
        Seg(ipa="ɔ", stress="1", is_vowel=True),
        Seg(ipa="k", is_vowel=False),
    ]
    lenient = align(a, b, word_boundary_leniency=True)
    strict = align(a, b, word_boundary_leniency=False)
    assert lenient.total_cost < strict.total_cost
