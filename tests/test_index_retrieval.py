"""U5 retrieval: IDF length-normalized scoring, dedupe, skeleton, pool acceptance."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest

from nautical import eval as eval_service
from nautical.phonetics.align import Seg
from nautical.phonetics.anchor import stress_skeleton_key
from nautical.search.index import (
    candidate_ids,
    segment_ngrams,
    skeleton_candidate_ids,
    tail_candidate_ids,
)


BASELINE_PATH = Path(__file__).parent / "u5_pool1500_baseline.json"


def _minimal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE lexeme (
            id INTEGER PRIMARY KEY,
            frequency REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE pronunciation (
            id INTEGER PRIMARY KEY,
            lexeme_id INTEGER,
            ngram_count INTEGER NOT NULL DEFAULT 0,
            rhyme_ngram_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE phoneme_ngram (
            ngram TEXT NOT NULL,
            pronunciation_id INTEGER NOT NULL,
            PRIMARY KEY (ngram, pronunciation_id)
        );
        CREATE TABLE rhyme_ngram (
            ngram TEXT NOT NULL,
            pronunciation_id INTEGER NOT NULL,
            PRIMARY KEY (ngram, pronunciation_id)
        );
        CREATE TABLE ngram_df (
            kind TEXT NOT NULL,
            ngram TEXT NOT NULL,
            df INTEGER NOT NULL,
            idf REAL NOT NULL,
            PRIMARY KEY (kind, ngram)
        );
        CREATE TABLE stress_skeleton (
            skeleton TEXT NOT NULL,
            pronunciation_id INTEGER NOT NULL,
            PRIMARY KEY (skeleton, pronunciation_id)
        );
        """
    )


def _idf(n: int, df: int) -> float:
    return math.log((n + 1) / (df + 1)) + 1.0


def test_segment_ngrams_short_and_long():
    assert segment_ngrams([]) == []
    assert segment_ngrams(["a"]) == ["a"]
    grams = segment_ngrams(["a", "b", "c"])
    assert "a\u001fb" in grams
    assert "a\u001fb\u001fc" in grams


def test_dedupe_prevents_repeat_gram_inflation(tmp_path):
    """A doc that would have had duplicate grams still scores once per gram."""
    conn = sqlite3.connect(tmp_path / "t.db")
    _minimal_schema(conn)
    # Pron 1: only the rare gram once. Pron 2: same rare + many common (long).
    rare = "x\u001fy"
    common = "a\u001fb"
    n = 3
    conn.executemany(
        "INSERT INTO pronunciation(id, ngram_count) VALUES (?, ?)",
        [(1, 1), (2, 10), (3, 1)],
    )
    conn.execute(
        "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        (rare, 1),
    )
    # UNIQUE forbids a second (rare, 1) row — simulate binary TF.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
            (rare, 1),
        )
    conn.executemany(
        "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        [(rare, 2), *[(f"c\u001f{i}", 2) for i in range(9)], (common, 3)],
    )
    for ngram, df in ((rare, 2), (common, 1)):
        conn.execute(
            "INSERT INTO ngram_df(kind, ngram, df, idf) VALUES ('full', ?, ?, ?)",
            (ngram, df, _idf(n, df)),
        )
    # Query shares only the rare gram with 1 and 2; 1 is shorter → higher score.
    ranked = candidate_ids(conn, ["x", "y"], pool=10)
    assert ranked[0] == 1
    assert 2 in ranked
    assert 3 not in ranked
    conn.close()


def test_idf_prefers_rare_shared_gram_over_many_common(tmp_path):
    """One rare shared gram outranks several high-df common grams."""
    conn = sqlite3.connect(tmp_path / "t.db")
    _minimal_schema(conn)
    n = 100
    rare = "q\u001fr"
    commons = [f"m\u001f{i}" for i in range(5)]
    conn.executemany(
        "INSERT INTO pronunciation(id, ngram_count) VALUES (?, ?)",
        [(1, 1), (2, 5)],
    )
    conn.execute(
        "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        (rare, 1),
    )
    conn.executemany(
        "INSERT INTO phoneme_ngram(ngram, pronunciation_id) VALUES (?, ?)",
        [(g, 2) for g in commons],
    )
    conn.execute(
        "INSERT INTO ngram_df(kind, ngram, df, idf) VALUES ('full', ?, ?, ?)",
        (rare, 1, _idf(n, 1)),
    )
    for g in commons:
        conn.execute(
            "INSERT INTO ngram_df(kind, ngram, df, idf) VALUES ('full', ?, ?, ?)",
            (g, 80, _idf(n, 80)),
        )
    grams = [rare, *commons]
    placeholders = ",".join("?" * len(grams))
    ranked = candidate_ids(conn, ["q", "r"], pool=10)
    # Query ["q","r"] only hits the rare gram → pron 1. Extend via SQL with commons:
    from nautical.search.index import _ensure_ln

    _ensure_ln(conn)
    rows = conn.execute(
        f"""
        SELECT t.pronunciation_id,
               SUM(d.idf) / (0.5 + _nautical_ln(1.0 + p.ngram_count)) AS score
        FROM phoneme_ngram AS t
        JOIN ngram_df AS d ON d.kind = 'full' AND d.ngram = t.ngram
        JOIN pronunciation AS p ON p.id = t.pronunciation_id
        WHERE t.ngram IN ({placeholders})
        GROUP BY t.pronunciation_id
        ORDER BY score DESC
        """,
        grams,
    ).fetchall()
    assert ranked == [1]
    assert rows[0][0] == 1, f"rare-gram doc should win, got {rows}"
    conn.close()


def test_stress_skeleton_key_and_lookup(tmp_path):
    segs = [
        Seg(ipa="n", stress="", is_vowel=False),
        Seg(ipa="ɔ", stress="1", is_vowel=True),
        Seg(ipa="t", stress="", is_vowel=False),
        Seg(ipa="ɪ", stress="0", is_vowel=True),
        Seg(ipa="k", stress="", is_vowel=False),
        Seg(ipa="ə", stress="0", is_vowel=True),
        Seg(ipa="l", stress="", is_vowel=False),
    ]
    key = stress_skeleton_key(segs)
    assert key == "ɔ"

    conn = sqlite3.connect(tmp_path / "t.db")
    _minimal_schema(conn)
    conn.executemany(
        "INSERT INTO lexeme(id, frequency) VALUES (?, ?)",
        [(10, 1.0), (20, 5.0), (30, 0.1)],
    )
    conn.executemany(
        "INSERT INTO pronunciation(id, lexeme_id) VALUES (?, ?)",
        [(1, 10), (2, 20), (3, 30)],
    )
    conn.executemany(
        "INSERT INTO stress_skeleton(skeleton, pronunciation_id) VALUES (?, ?)",
        [(key, 1), (key, 2), ("æ\u001fi", 3)],
    )
    hits = skeleton_candidate_ids(conn, segs, pool=10)
    assert set(hits) == {1, 2}
    # Higher frequency first.
    assert skeleton_candidate_ids(conn, segs, pool=1) == [2]
    conn.close()


def test_tail_candidate_ids_uses_rhyme_kind(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    _minimal_schema(conn)
    gram = "eɪ\u001fn"
    conn.execute(
        "INSERT INTO pronunciation(id, rhyme_ngram_count) VALUES (1, 1)"
    )
    conn.execute(
        "INSERT INTO rhyme_ngram(ngram, pronunciation_id) VALUES (?, 1)", (gram,)
    )
    conn.execute(
        "INSERT INTO ngram_df(kind, ngram, df, idf) VALUES ('rhyme', ?, 1, ?)",
        (gram, _idf(1, 1)),
    )
    assert tail_candidate_ids(conn, ["eɪ", "n"], pool=5) == [1]
    conn.close()


def test_schema_v8_has_idf_tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        assert meta["schema_version"] == "8"
        assert int(meta["ngram_df_count"]) > 0
        assert int(meta["stress_skeleton_count"]) > 0
        # No duplicate (ngram, pron) rows.
        dup = conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT ngram, pronunciation_id, COUNT(*) AS c "
            "  FROM phoneme_ngram GROUP BY ngram, pronunciation_id HAVING c > 1"
            ")"
        ).fetchone()[0]
        assert dup == 0
        # Sample: stainless skeleton resolves.
        row = conn.execute(
            "SELECT p.id, p.arpabet, p.ipa_segments FROM pronunciation p "
            "JOIN lexeme l ON l.id = p.lexeme_id WHERE l.written_form = 'stainless'"
        ).fetchone()
        assert row is not None
        from nautical.phonetics.anchor import segs_from_stored

        segs = segs_from_stored(row[1], row[2])
        key = stress_skeleton_key(segs)
        assert key
        # Same skeleton indexes meter mates (cap may omit low-frequency self).
        mates = conn.execute(
            "SELECT l.written_form FROM stress_skeleton s "
            "JOIN pronunciation p ON p.id = s.pronunciation_id "
            "JOIN lexeme l ON l.id = p.lexeme_id "
            "WHERE s.skeleton = ?",
            (key,),
        ).fetchall()
        forms = {r[0] for r in mates}
        assert "stainless" in forms
        assert "brainless" in forms or "painless" in forms
        assert skeleton_candidate_ids(conn, segs, pool=50)
    finally:
        conn.close()


def test_pool600_eval_matches_or_beats_pool1500_baseline(db_path):
    """Acceptance: IDF retrieval at pool=600 ≥ pre-U5 COUNT at pool=1500."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    pairs = [
        p
        for p in eval_service.load_pairs()
        if p.get("mode", "single") == "single"
        and p.get("polarity", "positive") != "negative"
        and not p.get("theme")
    ]
    assert len(pairs) == baseline["total"]

    conn = sqlite3.connect(db_path)
    try:
        report = eval_service.run_eval(
            pairs,
            limit=50,
            conn=conn,
            use_cache=False,
            include_diversity=False,
            pool=600,
        )
    finally:
        conn.close()

    assert report.hit_rate >= baseline["hit_rate"] - 1e-9, (
        f"hit_rate {report.hit_rate} < baseline {baseline['hit_rate']}"
    )
    assert report.mrr >= baseline["mrr"] - 1e-9, (
        f"mrr {report.mrr} < baseline {baseline['mrr']}"
    )
