"""ARPAbet -> IPA normalization.

CMUdict and g2p_en both emit ARPAbet phones (vowels carry a trailing stress
digit 0/1/2; consonants never do). This module converts those to a canonical
list of IPA segments and exposes small helpers for stress and syllable counts.

The conversion is stress-aware where it matters phonetically:

* ``AH0`` -> ``ə`` (schwa) but ``AH1``/``AH2`` -> ``ʌ``
* ``ER0`` -> ``ɚ`` but ``ER1``/``ER2`` -> ``ɝ``

That is what lets the ``a`` in "not a cult" reduce to ``ə`` and produce the
boundary-free string ``nɑtəkʌlt``.
"""

from __future__ import annotations

# ARPAbet vowel nuclei (base symbols, without the stress digit).
ARPABET_VOWELS = frozenset(
    {
        "AA", "AE", "AH", "AO", "AW", "AY",
        "EH", "ER", "EY",
        "IH", "IY",
        "OW", "OY",
        "UH", "UW",
    }
)

# Base ARPAbet -> IPA. Diphthongs map to a single multi-character segment.
_ARPABET_TO_IPA = {
    # consonants
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ",
    "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t",
    "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
    # vowels (base / stressed forms)
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɝ", "EY": "eɪ", "IH": "ɪ", "IY": "i",
    "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
}


def strip_stress(phone: str) -> str:
    """Return the ARPAbet phone without its trailing stress digit."""
    return phone[:-1] if phone and phone[-1].isdigit() else phone


def _stress_of(phone: str) -> str:
    """Return the stress digit of a phone ("0"/"1"/"2") or "" if none."""
    return phone[-1] if phone and phone[-1].isdigit() else ""


def is_vowel(phone: str) -> bool:
    """True if the ARPAbet phone is a vowel nucleus."""
    return strip_stress(phone) in ARPABET_VOWELS


def phone_to_ipa(phone: str) -> str:
    """Convert a single ARPAbet phone to an IPA segment (stress-aware)."""
    base = strip_stress(phone)
    stress = _stress_of(phone)
    if base == "AH" and stress == "0":
        return "ə"
    if base == "ER" and stress == "0":
        return "ɚ"
    return _ARPABET_TO_IPA[base]


def arpabet_to_ipa(phones: list[str]) -> list[str]:
    """Convert a sequence of ARPAbet phones to a list of IPA segments."""
    return [phone_to_ipa(p) for p in phones]


def stress_pattern(phones: list[str]) -> str:
    """Concatenated stress digits over the vowels, e.g. "100"."""
    return "".join(_stress_of(p) for p in phones if is_vowel(p))


def syllable_count(phones: list[str]) -> int:
    """Number of syllables = number of vowel nuclei."""
    return sum(1 for p in phones if is_vowel(p))
