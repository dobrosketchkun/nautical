"""Build-time lexicon quality signals and derived score.

Computed once during ``nautical db build`` and filtered at query time via
``--quality`` / ``min_quality``. Constants are centralized so U3 can tune them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# Default query gate (U3 may retune later).
DEFAULT_MIN_QUALITY = 0.35

ZIPF_FLOOR = 0.0
ZIPF_CEIL = 7.0
PENALTY_POSSESSIVE = 0.35
PENALTY_ABBREV = 0.40
PENALTY_PROPN = 0.30
PENALTY_VARIANT = 0.25

# Proper-noun title-case tags below this zipf count as is_propn.
# Must stay low: title-casing common nouns (cult, brainless) often yields NNP.
PROPN_ZIPF_MAX = 2.0

_VOWEL_LETTERS = frozenset("aeiouy")
_PROPN_TAGS = frozenset({"NNP", "NNPS"})

_TAGGER_PACKAGES = (
    "averaged_perceptron_tagger_eng",
    "averaged_perceptron_tagger",
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def zipf_base(zipf: float) -> float:
    """Map zipf frequency into a [0, 1] quality base."""
    return clamp((zipf - ZIPF_FLOOR) / (ZIPF_CEIL - ZIPF_FLOOR))


def is_possessive(form: str) -> bool:
    """True if the spelling looks like a possessive or contains an apostrophe."""
    if "'" not in form and "’" not in form:
        return False
    return True


def is_abbrev(form: str) -> bool:
    """True for digit/dot forms, tiny vowelless tokens, or all-consonant spellings."""
    if any(ch.isdigit() for ch in form) or "." in form:
        return True
    letters = [ch for ch in form.lower() if ch.isalpha()]
    if not letters:
        return True
    has_vowel = any(ch in _VOWEL_LETTERS for ch in letters)
    if len(letters) <= 2 and not has_vowel:
        return True
    if not has_vowel:
        return True
    return False


def is_propn_tag(title_tag: str, zipf: float) -> bool:
    """Proper-noun flag: title-case NNP/NNPS and not a high-frequency common word."""
    return title_tag in _PROPN_TAGS and zipf < PROPN_ZIPF_MAX


def compute_quality(
    zipf: float,
    *,
    is_possessive_flag: bool,
    is_abbrev_flag: bool,
    is_propn_flag: bool,
    is_variant_flag: bool,
) -> float:
    """Derived 0..1 admission score from zipf base minus fixed flag penalties."""
    q = zipf_base(zipf)
    if is_possessive_flag:
        q -= PENALTY_POSSESSIVE
    if is_abbrev_flag:
        q -= PENALTY_ABBREV
    if is_propn_flag:
        q -= PENALTY_PROPN
    if is_variant_flag:
        q -= PENALTY_VARIANT
    return clamp(q)


def ensure_nltk_tagger() -> None:
    """Make sure an averaged perceptron tagger is available (download once if needed)."""
    import nltk

    last_error: Exception | None = None
    for package in _TAGGER_PACKAGES:
        try:
            nltk.data.find(f"taggers/{package}")
            return
        except LookupError as exc:
            last_error = exc
            try:
                nltk.download(package, quiet=True)
                nltk.data.find(f"taggers/{package}")
                return
            except Exception as download_exc:  # pragma: no cover - env/network
                last_error = download_exc
    raise RuntimeError(
        "NLTK averaged perceptron tagger is required for lexicon quality tagging "
        f"but could not be loaded ({last_error})."
    )


def batch_pos_tag(forms: Sequence[str], *, chunk_size: int = 2000) -> list[str]:
    """Return isolation POS tags for ``forms`` (same order), tagging in chunks."""
    from nltk import pos_tag

    ensure_nltk_tagger()
    tags: list[str] = []
    for start in range(0, len(forms), chunk_size):
        chunk = list(forms[start : start + chunk_size])
        if not chunk:
            continue
        tagged = pos_tag(chunk)
        tags.extend(tag for _, tag in tagged)
    return tags


def variant_loser_ids(
    groups: Iterable[tuple[str, Iterable[tuple[int, float, str]]]],
) -> set[int]:
    """Return lexeme ids that lose at least one IPA group.

    Each group is ``(ipa, [(lexeme_id, zipf, written_form), ...])``. The winner
    is highest zipf, then shorter spelling, then alphabetical.
    """
    losers: set[int] = set()
    for _ipa, members in groups:
        unique: dict[int, tuple[float, str]] = {}
        for lexeme_id, zipf, form in members:
            existing = unique.get(lexeme_id)
            if existing is None or zipf > existing[0]:
                unique[lexeme_id] = (zipf, form)
        if len(unique) <= 1:
            continue
        ranked = sorted(
            unique.items(),
            key=lambda item: (-item[1][0], len(item[1][1]), item[1][1]),
        )
        for lexeme_id, _ in ranked[1:]:
            losers.add(lexeme_id)
    return losers
