"""Pronunciation service: text -> normalized IPA representation.

CMUdict (from the SQLite DB) is the primary source; ``g2p_en`` is the fallback
for out-of-vocabulary words. A word maps to a lattice of pronunciation variants;
a phrase keeps per-token boundaries plus a boundary-free IPA string used by the
later phonetic-search phases.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import g2p as g2p_module
from .config import DB_PATH
from .phonetics.align import Seg
from .phonology.arpabet import arpabet_to_ipa, is_vowel, stress_pattern, syllable_count
from .phonology.syllable import Syllable, syllabify

# Strip leading/trailing punctuation but preserve word-internal apostrophes
# (so contractions like "you're" survive).
_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


@dataclass
class Pronunciation:
    source: str  # "cmudict" | "g2p"
    arpabet: list[str]
    ipa_segments: list[str]
    stress: str
    syllable_count: int
    syllables: list[Syllable] = field(default_factory=list)

    @property
    def ipa(self) -> str:
        return "".join(self.ipa_segments)


@dataclass
class WordPronunciation:
    word: str
    variants: list[Pronunciation] = field(default_factory=list)

    @property
    def primary(self) -> Pronunciation | None:
        return self.variants[0] if self.variants else None


@dataclass
class PhrasePronunciation:
    text: str
    tokens: list[WordPronunciation]
    boundaries: list[tuple[int, int]]  # (start, end) segment span per token
    boundary_free: str


def tokenize(text: str) -> list[str]:
    """Split text into lowercased word tokens (edge punctuation removed).

    A minimal tokenizer for now; a full lyric tokenizer (Japanese switching,
    elongated spellings, performance notation) is deferred.
    """
    tokens = []
    for raw in text.split():
        token = _EDGE_PUNCT.sub("", raw.lower())
        if token:
            tokens.append(token)
    return tokens


def _pronunciation_from_arpabet(phones: list[str], source: str) -> Pronunciation:
    return Pronunciation(
        source=source,
        arpabet=list(phones),
        ipa_segments=arpabet_to_ipa(phones),
        stress=stress_pattern(phones),
        syllable_count=syllable_count(phones),
        syllables=syllabify(phones),
    )


def pronounce_word(
    word: str,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> WordPronunciation:
    """Return the pronunciation lattice for a single word.

    Looks the word up in the CMUdict-backed DB first; falls back to g2p for
    out-of-vocabulary words.
    """
    normalized = _EDGE_PUNCT.sub("", word.lower())
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        rows = conn.execute(
            "SELECT p.arpabet, p.source FROM pronunciation p "
            "JOIN lexeme l ON l.id = p.lexeme_id "
            "WHERE l.written_form = ? ORDER BY p.id",
            (normalized,),
        ).fetchall()
    finally:
        if own_conn:
            conn.close()

    variants: list[Pronunciation] = []
    if rows:
        for arpabet_str, source in rows:
            variants.append(
                _pronunciation_from_arpabet(arpabet_str.split(), source or "cmudict")
            )
    else:
        phones = g2p_module.grapheme_to_arpabet(normalized)
        if phones:
            variants.append(_pronunciation_from_arpabet(phones, "g2p"))

    return WordPronunciation(word=normalized, variants=variants)


def pronounce_phrase(
    text: str,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> PhrasePronunciation:
    """Pronounce a phrase, keeping word boundaries as metadata.

    ``boundary_free`` concatenates the primary variant's IPA segments across
    tokens; ``boundaries`` records each token's (start, end) segment span.
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(Path(db_path) if db_path is not None else DB_PATH)
    try:
        tokens = [pronounce_word(w, conn=conn) for w in tokenize(text)]
    finally:
        if own_conn:
            conn.close()

    boundaries: list[tuple[int, int]] = []
    segments: list[str] = []
    position = 0
    for word_pron in tokens:
        primary = word_pron.primary
        token_segments = primary.ipa_segments if primary else []
        start = position
        segments.extend(token_segments)
        position += len(token_segments)
        boundaries.append((start, position))

    return PhrasePronunciation(
        text=text,
        tokens=tokens,
        boundaries=boundaries,
        boundary_free="".join(segments),
    )


def _segs_from_pronunciation(pron: Pronunciation) -> list[Seg]:
    """Build ``Seg``s for one pronunciation, marking the final segment word-final."""
    segs: list[Seg] = []
    for phone, ipa_segment in zip(pron.arpabet, pron.ipa_segments):
        stress = phone[-1] if phone and phone[-1].isdigit() else ""
        segs.append(Seg(ipa=ipa_segment, stress=stress, is_vowel=is_vowel(phone)))
    if segs:
        segs[-1].word_final = True
    return segs


def enriched_segments(
    text: str,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> list[Seg]:
    """Return per-segment ``Seg(ipa, stress, is_vowel, word_final)`` for a phrase.

    Uses each token's primary variant, deriving per-segment stress and vowel-ness
    from the ARPAbet<->IPA 1:1 correspondence. The last segment of every token is
    flagged ``word_final`` so the aligner can apply word-boundary leniency.
    Consumed by the phonetic aligner.
    """
    phrase = pronounce_phrase(text, conn=conn, db_path=db_path)
    segments: list[Seg] = []
    for word_pron in phrase.tokens:
        primary = word_pron.primary
        if primary is None:
            continue
        segments.extend(_segs_from_pronunciation(primary))
    return segments


# Cap on the per-token variant product for a phrase, to avoid combinatorial
# blow-up; above this the phrase falls back to primary-variant segments only.
_MAX_PHRASE_VARIANTS = 8


def enriched_segment_variants(
    text: str,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> list[list[Seg]]:
    """Return one enriched-segment list per pronunciation variant of ``text``.

    A single-word input yields every CMUdict variant. A multi-word phrase yields
    the Cartesian product of its tokens' variants, but only when that product is
    small (<= ``_MAX_PHRASE_VARIANTS``); otherwise it falls back to a single
    primary-variant list to avoid combinatorial blow-up.
    """
    phrase = pronounce_phrase(text, conn=conn, db_path=db_path)
    token_variant_segs: list[list[list[Seg]]] = []
    for word_pron in phrase.tokens:
        if not word_pron.variants:
            continue
        token_variant_segs.append(
            [_segs_from_pronunciation(v) for v in word_pron.variants]
        )

    if not token_variant_segs:
        return []

    total = 1
    for options in token_variant_segs:
        total *= len(options)
    if total > _MAX_PHRASE_VARIANTS:
        # Too many combinations; use the primary variant of each token.
        return [[seg for options in token_variant_segs for seg in options[0]]]

    import itertools

    combos: list[list[Seg]] = []
    for combo in itertools.product(*token_variant_segs):
        combos.append([seg for token_segs in combo for seg in token_segs])
    return combos
