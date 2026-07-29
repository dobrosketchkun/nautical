"""SQLite-backed result cache for expensive searches.

Lives in its own ``cache.db`` under the resolved data directory (separate from
the lexicon), so it survives a lexicon rebuild. Values are
opaque JSON payloads; each caller serializes/deserializes its own result type.
The cache key is derived from the phonetic search parameters only - semantic
reranking (``--theme``) is applied after the cache, so one cached search serves
every theme.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .config import CACHE_DB_PATH, ensure_data_dir

_CACHE_FORMAT_VERSION = "u3-v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_cache (
    key        TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else CACHE_DB_PATH
    if path == CACHE_DB_PATH:
        ensure_data_dir()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def make_key(kind: str, text: str, params: dict) -> str:
    """Stable cache key from a search kind, query text, and its parameters.

    Callers should include ``weights_hash`` and lexicon identity
    (``schema_version``, ``built_at``) in ``params`` so weight/DB changes
    invalidate automatically.
    """
    normalized = json.dumps(
        {
            "format": _CACHE_FORMAT_VERSION,
            "kind": kind,
            "text": text.strip().lower(),
            "params": params,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def lexicon_identity(db_path: Path | None = None) -> dict[str, str]:
    """Return ``schema_version`` / ``built_at`` for cache keys (empty if unavailable)."""
    from .config import DB_PATH
    from .db import loader

    path = Path(db_path) if db_path is not None else DB_PATH
    if not path.exists():
        return {"schema_version": "", "built_at": ""}
    try:
        info = loader.get_stats(path)
    except (OSError, FileNotFoundError, Exception):
        return {"schema_version": "", "built_at": ""}
    return {
        "schema_version": str(info.get("schema_version", "")),
        "built_at": str(info.get("built_at", "")),
    }


def cache_get(key: str, db_path: Path | None = None) -> dict | list | None:
    """Return the cached payload for ``key`` or ``None`` on a miss."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT payload FROM query_cache WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return json.loads(row[0])


def cache_put(key: str, payload: dict | list, db_path: Path | None = None) -> None:
    """Store ``payload`` (JSON-serializable) under ``key``."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO query_cache(key, created_at, payload) "
            "VALUES (?, ?, ?)",
            (
                key,
                time.strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clear(db_path: Path | None = None) -> int:
    """Delete all cached rows; return how many were removed."""
    conn = _connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
        conn.execute("DELETE FROM query_cache")
        conn.commit()
    finally:
        conn.close()
    return count


def stats(db_path: Path | None = None) -> dict:
    """Return cache row count, file size, oldest/newest timestamps, and path."""
    path = Path(db_path) if db_path is not None else CACHE_DB_PATH
    if not path.exists():
        return {"rows": 0, "size_bytes": 0, "oldest": None, "newest": None, "path": str(path)}
    conn = _connect(path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
        span = conn.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM query_cache"
        ).fetchone()
    finally:
        conn.close()
    return {
        "rows": rows,
        "size_bytes": path.stat().st_size,
        "oldest": span[0],
        "newest": span[1],
        "path": str(path),
    }
