"""Phase 1 tests: ARPAbet -> IPA normalization and syllabification."""

from nautical.phonology.arpabet import (
    arpabet_to_ipa,
    is_vowel,
    strip_stress,
    stress_pattern,
    syllable_count,
)
from nautical.phonology.syllable import syllabify

NAUTICAL = ["N", "AO1", "T", "IH0", "K", "AH0", "L"]


def test_arpabet_to_ipa_nautical():
    assert arpabet_to_ipa(NAUTICAL) == list("nɔtɪkəl")


def test_schwa_vs_wedge():
    assert arpabet_to_ipa(["AH0"]) == ["ə"]
    assert arpabet_to_ipa(["AH1"]) == ["ʌ"]
    assert arpabet_to_ipa(["ER0"]) == ["ɚ"]
    assert arpabet_to_ipa(["ER1"]) == ["ɝ"]


def test_helpers():
    assert strip_stress("AO1") == "AO"
    assert strip_stress("T") == "T"
    assert is_vowel("AO1") and not is_vowel("T")
    assert stress_pattern(NAUTICAL) == "100"
    assert syllable_count(NAUTICAL) == 3


def test_syllabify_nautical():
    syllables = syllabify(NAUTICAL)
    assert len(syllables) == 3
    assert [s.stress for s in syllables] == ["1", "0", "0"]
    # trailing L closes the final syllable
    assert syllables[-1].coda == ["L"]
