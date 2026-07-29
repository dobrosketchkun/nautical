"""GloVe 6B (300d) static word vectors (full vocabulary).

The raw 822 MB ``glove.6B.zip`` is downloaded once (if absent) and the single
dimension we use is extracted, then streamed line by line. Every vector is kept
(the full ~400K vocabulary) so any theme/seed word the user types resolves, not
just words in our lexicon; ``chain`` masks its neighbor suggestions back to the
lexicon at query time. Vectors are L2-normalized (so cosine similarity is a plain
dot product) and cached as a compact ``float32`` ``.npy`` matrix plus a parallel
``vocab.txt``. Everything is offline after the one-time download; a pre-staged raw
file or cache skips it entirely.
"""

from __future__ import annotations

import sqlite3
import urllib.request
import zipfile
from pathlib import Path
from urllib.error import URLError

import numpy as np

from ..config import (
    DEFAULT_PATHS,
    DB_PATH,
    GLOVE_DIM,
    GLOVE_ZIP_URLS,
    NauticalPaths,
)
from ..errors import NauticalError


class VectorsUnavailable(NauticalError):
    """Raised when vectors cannot be loaded or built (e.g. no lexicon)."""


def _log(message: str) -> None:
    # Lazily import rich so importing this module stays cheap and console-free.
    try:
        from rich.console import Console

        Console(stderr=True).print(message)
    except Exception:
        print(message)


def lexicon_words(db_path: Path | None = None) -> set[str]:
    """Return the set of lowercase written forms from the lexicon."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    if not db_path.exists():
        raise VectorsUnavailable(
            f"No lexicon database at {db_path}. Run `nautical db build` first."
        )
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT written_form FROM lexeme").fetchall()
    finally:
        conn.close()
    return {form.lower() for (form,) in rows if form}


# Backwards-compatible alias for existing callers/tests.
_lexicon_words = lexicon_words


def download_glove(
    dest: Path | None = None,
    *,
    paths: NauticalPaths | None = None,
) -> Path:
    """Download ``glove.6B.zip`` and extract the target-dimension text file.

    Returns the path to the extracted ``glove.6B.<dim>d.txt``. Tries each URL in
    :data:`GLOVE_ZIP_URLS` in turn.
    """
    paths = paths or DEFAULT_PATHS
    dest = Path(dest) if dest is not None else paths.glove_raw
    paths.ensure_vectors_dir()
    member = f"glove.6B.{GLOVE_DIM}d.txt"
    zip_path = paths.glove_zip if dest == paths.glove_raw else dest.parent / "glove.6B.zip"

    if not zip_path.exists():
        last_error: Exception | None = None
        for url in GLOVE_ZIP_URLS:
            try:
                _log(f"[cyan]Downloading[/cyan] {url} (~822 MB, one-time)...")
                urllib.request.urlretrieve(url, zip_path)
                last_error = None
                break
            except (URLError, OSError) as exc:  # pragma: no cover - network path
                last_error = exc
                _log(f"[yellow]Failed:[/yellow] {url} ({exc})")
                if zip_path.exists():
                    zip_path.unlink()
        if last_error is not None:  # pragma: no cover - network path
            raise VectorsUnavailable(
                f"Could not download GloVe from any mirror: {last_error}"
            )

    _log(f"[cyan]Extracting[/cyan] {member}...")
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as src, open(dest, "wb") as out:
            out.write(src.read())
    return dest


def _migrate_legacy_matrix(paths: NauticalPaths) -> None:
    """Rename the pre-Phase-10 full-vocabulary cache if it exists."""
    legacy = paths.vectors_dir / f"glove.6B.{GLOVE_DIM}d.filtered.npy"
    if not paths.glove_matrix.exists() and legacy.exists():
        legacy.replace(paths.glove_matrix)


def _cleanup_build_inputs(paths: NauticalPaths) -> None:
    """Keep only the two files required at runtime."""
    paths.glove_raw.unlink(missing_ok=True)
    paths.glove_zip.unlink(missing_ok=True)


def vectors_ready(paths: NauticalPaths | None = None) -> bool:
    """Return whether both runtime artifacts exist, migrating old cache names."""
    paths = paths or DEFAULT_PATHS
    _migrate_legacy_matrix(paths)
    ready = paths.glove_matrix.exists() and paths.glove_vocab.exists()
    if ready:
        _cleanup_build_inputs(paths)
    return ready


def build_vectors(
    force: bool = False,
    db_path: Path | None = None,
    *,
    paths: NauticalPaths | None = None,
) -> dict[str, int]:
    """Cache the full normalized GloVe matrix (no lexicon filtering).

    Every vector in the raw file is kept so any theme/seed word resolves; the
    lexicon mask is applied later, only for ``chain`` suggestions. Downloads the
    raw file first if it is absent. The ``db_path`` argument is accepted for
    backward compatibility but no longer used. Returns a small stats dict.
    """
    paths = paths or DEFAULT_PATHS
    paths.ensure_vectors_dir()
    if vectors_ready(paths) and not force:
        _cleanup_build_inputs(paths)
        vocab = paths.glove_vocab.read_text(encoding="utf-8").split("\n")
        vocab = [w for w in vocab if w]
        return {"rows": len(vocab), "dim": GLOVE_DIM}

    if not paths.glove_raw.exists():
        download_glove(paths=paths)

    words: list[str] = []
    rows: list[np.ndarray] = []
    _log(f"[cyan]Loading[/cyan] full vocabulary from {paths.glove_raw.name}...")
    with open(paths.glove_raw, "r", encoding="utf-8") as fh:
        for line in fh:
            space = line.find(" ")
            if space <= 0:
                continue
            word = line[:space]
            vec = np.fromstring(line[space + 1 :], sep=" ", dtype=np.float32)
            if vec.shape[0] != GLOVE_DIM:
                continue
            norm = np.linalg.norm(vec)
            if norm == 0.0:
                continue
            words.append(word)
            rows.append(vec / norm)

    if not rows:
        raise VectorsUnavailable(
            "No vectors parsed from the GloVe file; is the file correct?"
        )

    matrix = np.vstack(rows).astype(np.float32)
    np.save(paths.glove_matrix, matrix)
    paths.glove_vocab.write_text("\n".join(words), encoding="utf-8")
    # Validate both runtime artifacts before discarding the large build inputs.
    if not paths.glove_matrix.exists() or not paths.glove_vocab.exists():
        raise VectorsUnavailable("Vector cache build did not produce both runtime files.")
    _cleanup_build_inputs(paths)
    _log(f"[green]Cached[/green] {matrix.shape[0]:,} vectors x {matrix.shape[1]}d.")
    return {"rows": matrix.shape[0], "dim": matrix.shape[1]}


class Vectors:
    """A loaded, L2-normalized word-vector matrix with a word->row index."""

    def __init__(self, matrix: np.ndarray, vocab: list[str]) -> None:
        self.matrix = matrix
        self.vocab = vocab
        self.index: dict[str, int] = {w: i for i, w in enumerate(vocab)}

    @classmethod
    def load(cls, paths: NauticalPaths | None = None) -> "Vectors":
        paths = paths or DEFAULT_PATHS
        if not vectors_ready(paths):
            raise VectorsUnavailable(
                "Vector cache missing. Run `nautical vectors build`."
            )
        _cleanup_build_inputs(paths)
        matrix = np.load(paths.glove_matrix, mmap_mode="r")
        vocab = [
            w for w in paths.glove_vocab.read_text(encoding="utf-8").split("\n") if w
        ]
        return cls(matrix, vocab)

    @classmethod
    def from_mapping(cls, mapping: dict[str, "np.ndarray | list[float]"]) -> "Vectors":
        """Build directly from ``{word: vector}`` (vectors are L2-normalized).

        Handy for tests without touching disk or the network.
        """
        words = list(mapping)
        rows = []
        for w in words:
            vec = np.asarray(mapping[w], dtype=np.float32)
            norm = np.linalg.norm(vec)
            rows.append(vec / norm if norm else vec)
        matrix = np.vstack(rows).astype(np.float32) if rows else np.zeros((0, 0))
        return cls(matrix, words)

    def get(self, word: str) -> np.ndarray | None:
        """Return the normalized vector for ``word`` (case-insensitive) or None."""
        row = self.index.get(word.lower())
        if row is None:
            return None
        return np.asarray(self.matrix[row])

    def term_vector(self, terms: list[str]) -> np.ndarray | None:
        """Mean of the resolved term vectors, renormalized. None if none resolve.

        Unknown terms are skipped and reported.
        """
        vecs = []
        unknown = []
        for term in terms:
            vec = self.get(term)
            if vec is None:
                unknown.append(term)
            else:
                vecs.append(vec)
        if unknown:
            _log(f"[yellow]Unknown term(s) skipped:[/yellow] {', '.join(unknown)}")
        if not vecs:
            return None
        mean = np.mean(np.vstack(vecs), axis=0)
        norm = np.linalg.norm(mean)
        return mean / norm if norm else mean

    def similarity(self, a: str, b: str) -> float | None:
        """Cosine similarity between two words, or None if either is unknown."""
        va, vb = self.get(a), self.get(b)
        if va is None or vb is None:
            return None
        return float(np.dot(va, vb))

    def most_similar(
        self,
        vector: np.ndarray,
        topn: int = 25,
        exclude: set[str] | None = None,
        allowed: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return the ``topn`` nearest vocabulary words to ``vector`` by cosine.

        When ``allowed`` is given, only words in that set are returned (used to
        mask the full vocabulary back down to lexicon words for ``chain``).
        """
        if self.matrix.shape[0] == 0:
            return []
        exclude = {w.lower() for w in (exclude or set())}
        allowed = {w.lower() for w in allowed} if allowed is not None else None
        scores = np.asarray(self.matrix) @ np.asarray(vector, dtype=np.float32)
        # Over-fetch then filter excludes / allowed; argpartition avoids a full sort.
        fetch = min(len(scores), max(topn * 20, topn + len(exclude) + 64))
        if fetch >= len(scores):
            candidates = np.argsort(-scores)
        else:
            part = np.argpartition(-scores, fetch - 1)[:fetch]
            candidates = part[np.argsort(-scores[part])]
        out: list[tuple[str, float]] = []
        for idx in candidates:
            word = self.vocab[int(idx)]
            if word in exclude:
                continue
            if allowed is not None and word not in allowed:
                continue
            out.append((word, float(scores[idx])))
            if len(out) >= topn:
                break
        return out


_CACHE: dict[Path, Vectors] = {}


def ensure_vectors(
    db_path: Path | None = None,
    *,
    paths: NauticalPaths | None = None,
) -> Vectors:
    """Return a loaded :class:`Vectors`, building/downloading it if necessary.

    This is the lazy "just works on a fresh checkout" entry point used by the
    semantic CLI commands.
    """
    paths = paths or DEFAULT_PATHS
    key = paths.vectors_dir
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    if not vectors_ready(paths):
        build_vectors(db_path=db_path, paths=paths)
    loaded = Vectors.load(paths)
    _CACHE[key] = loaded
    return loaded
