"""Lightweight syllabification of ARPAbet phone sequences.

This is a heuristic, not a full phonotactic parser: intervocalic consonants are
assigned by a simplified rule (a single consonant becomes the onset of the
following syllable; in a cluster the last consonant becomes the next onset and
the rest close the preceding syllable). It is good enough for syllable counts
and stress placement now, and is refined in Phase 5 for tail-anchoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .arpabet import is_vowel


@dataclass
class Syllable:
    onset: list[str] = field(default_factory=list)
    nucleus: str = ""
    coda: list[str] = field(default_factory=list)
    stress: str = ""  # "0" / "1" / "2" or ""

    @property
    def phones(self) -> list[str]:
        return [*self.onset, self.nucleus, *self.coda]


def syllabify(phones: list[str]) -> list[Syllable]:
    """Split ARPAbet phones into syllables (see module docstring for the rule)."""
    nuclei = [i for i, p in enumerate(phones) if is_vowel(p)]
    if not nuclei:
        return []

    syllables: list[Syllable] = []
    for k, ni in enumerate(nuclei):
        nucleus = phones[ni]
        stress = nucleus[-1] if nucleus[-1].isdigit() else ""

        if k == 0:
            onset = list(phones[:ni])
        else:
            cluster = phones[nuclei[k - 1] + 1 : ni]
            if len(cluster) <= 1:
                onset = list(cluster)
            else:
                onset = list(cluster[-1:])
                syllables[-1].coda.extend(cluster[:-1])

        syllables.append(Syllable(onset=onset, nucleus=nucleus, stress=stress))

    # Trailing consonants close the final syllable.
    syllables[-1].coda.extend(phones[nuclei[-1] + 1 :])
    return syllables
