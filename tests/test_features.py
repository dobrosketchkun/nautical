"""Phase 2 tests: PanPhon-backed feature vectors and distance."""

from nautical.phonetics.features import feature_distance, feature_vector
from nautical.phonology.arpabet import IPA_INVENTORY


def test_inventory_coverage():
    for segment in IPA_INVENTORY:
        assert feature_vector(segment) is not None, segment


def test_identity_is_zero():
    assert feature_distance("t", "t") == 0.0
    assert feature_distance("ə", "ə") == 0.0


def test_relative_distances():
    # voicing-only difference is smaller than a place+manner difference
    assert feature_distance("t", "d") < feature_distance("t", "m")
    # schwa is closer to the wedge vowel than to a stop
    assert feature_distance("ə", "ʌ") < feature_distance("ə", "k")


def test_bounded():
    for a in ("t", "ə", "eɪ", "tʃ", "ɝ"):
        for b in ("d", "k", "oʊ", "dʒ", "ɚ"):
            d = feature_distance(a, b)
            assert 0.0 <= d <= 1.0
