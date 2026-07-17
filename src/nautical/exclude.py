"""User-managed word exclusion list.

Words listed here (or passed via ``--exclude``) are dropped from search results.
This is deliberately a *filter*, not a sound-collapse: distinct words that merely
sound alike (``cull`` / ``gnaw``) stay separate, and the user decides what to hide.

Format of ``exclude.txt`` in the resolved data directory: one lowercase word
per line; blank lines and ``#`` comments are ignored.
"""

from __future__ import annotations

from pathlib import Path

from .config import EXCLUDE_PATH


def load_exclusions(path: Path | None = None) -> set[str]:
    """Return the set of excluded words from the file (empty if it is absent)."""
    path = Path(path) if path is not None else EXCLUDE_PATH
    if not path.exists():
        return set()
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            words.add(line)
    return words


def parse_exclude_flag(value: str | None) -> set[str]:
    """Parse a ``--exclude`` value ('cull, naught') into a lowercase word set."""
    if not value:
        return set()
    return {w.strip().lower() for w in value.replace(",", " ").split() if w.strip()}


def resolve_exclusions(
    flag: str | None = None, path: Path | None = None
) -> frozenset[str]:
    """Merge the persistent exclusion file with an inline ``--exclude`` flag."""
    return frozenset(load_exclusions(path) | parse_exclude_flag(flag))
