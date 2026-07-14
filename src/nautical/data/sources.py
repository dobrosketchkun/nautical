"""Thin readers over the offline data packages.

CMUdict supplies ARPAbet pronunciations; wordfreq supplies unigram
frequencies. Both ship their data inside the package, so no network access is
required at build or run time.
"""

from __future__ import annotations

from typing import Iterator

import cmudict
from wordfreq import word_frequency

# ARPAbet vowel/phone helpers live in nautical.phonology.arpabet.


def iter_lexemes() -> Iterator[tuple[str, list[list[str]]]]:
    """Yield ``(written_form, [pronunciation, ...])`` for every CMUdict word.

    Each pronunciation is a list of ARPAbet phones (vowels keep their stress
    digit, e.g. ``["N", "AO1", "T", "IH0", "K", "AH0", "L"]``).
    """
    for word, pronunciations in cmudict.dict().items():
        yield word, pronunciations


def get_frequency(word: str) -> float:
    """Return the English unigram frequency of ``word`` (0.0 if unknown)."""
    return word_frequency(word, "en")
