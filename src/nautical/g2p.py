"""Grapheme-to-phoneme fallback for words not in CMUdict.

Wraps ``g2p_en`` (Apache-2.0), which predicts ARPAbet phones (with stress) for
arbitrary spellings such as invented words. The model is created lazily on first
use so the one-time nltk data download is deferred until actually needed; after
that it runs fully offline.
"""

from __future__ import annotations

import re
from functools import lru_cache

# ARPAbet phones are 1-2 uppercase letters with an optional stress digit.
_PHONE_RE = re.compile(r"^[A-Z]{1,2}[0-9]?$")


@lru_cache(maxsize=1)
def _get_g2p():
    try:
        from g2p_en import G2p
    except ImportError as exc:  # pragma: no cover - environment issue
        raise RuntimeError(
            "g2p_en is not installed. Install it into general_env_1 "
            "(`pip install -e .`) to enable pronunciation of out-of-vocabulary words."
        ) from exc
    try:
        return G2p()
    except Exception as exc:  # pragma: no cover - first-run data download issue
        raise RuntimeError(
            "Could not initialize g2p_en (its nltk data may be missing and no "
            "network is available for the one-time download)."
        ) from exc


def grapheme_to_arpabet(word: str) -> list[str]:
    """Predict ARPAbet phones for ``word``, filtering out non-phone tokens."""
    phones = _get_g2p()(word)
    return [p for p in phones if _PHONE_RE.match(p)]
