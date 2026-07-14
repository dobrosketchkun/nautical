"""Segment normalization for the multi-word decoder's onset index.

Oronyms keep their onset consonants but drift across slant vowels (`nautical`
`nɔt-` vs `not` `nɑt`). Retrieval therefore anchors on a *normalized* onset:
consonants are kept exactly, vowels are collapsed to a few broad classes, and
stress is ignored. This is deliberately generous - it only widens the candidate
pool (which is then capped by frequency and rescored by the precise aligner), so
over-merging never hurts correctness, only recall.
"""

from __future__ import annotations

# Broad vowel classes. The CENTRAL bucket intentionally merges the low/central
# vowels (ɑ ɔ ʌ ə and r-colored ɝ ɚ) so `not`/`nautical`-style slant vowels land
# on the same key.
_VOWEL_CLASS = {
    "ɑ": "CENTRAL", "ɔ": "CENTRAL", "ʌ": "CENTRAL", "ə": "CENTRAL",
    "ɝ": "CENTRAL", "ɚ": "CENTRAL",
    "i": "FRONT", "ɪ": "FRONT", "eɪ": "FRONT", "ɛ": "FRONT", "æ": "FRONT",
    "u": "BACK", "ʊ": "BACK", "oʊ": "BACK",
    "aɪ": "DIPH", "aʊ": "DIPH", "ɔɪ": "DIPH",
}

_SEP = "\u001f"


def broad_vowel(segment: str) -> str:
    """Map a vowel segment to its broad class; return consonants unchanged."""
    return _VOWEL_CLASS.get(segment, segment)


def normalize_segments(segments: list[str]) -> list[str]:
    """Normalize a segment sequence (vowels -> broad class, consonants kept)."""
    return [broad_vowel(s) for s in segments]


def onset_keys(segments: list[str]) -> list[str]:
    """Return normalized onset keys (1-segment and, if present, 2-segment).

    Indexing every word under both keys and querying with both lets single- and
    multi-segment words be retrieved at the same target position: a 1-segment
    word like `a` (`ə`) matches on the 1-segment key, while a longer word is
    anchored by its onset consonant plus its first vowel's broad class.
    """
    if not segments:
        return []
    keys = [broad_vowel(segments[0])]
    if len(segments) >= 2:
        keys.append(broad_vowel(segments[0]) + _SEP + broad_vowel(segments[1]))
    return keys
