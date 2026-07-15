"""Phase 7 tests: evaluation harness rank-finding and aggregates."""

import sqlite3

import pytest

from nautical import eval as eval_service


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_normalize():
    assert eval_service._normalize("  Not a Cult! ") == "not a cult"
    assert eval_service._normalize("brainless.") == "brainless"


def test_load_pairs_skips_meta_keys():
    pairs = eval_service.load_pairs()  # the real curated corpus
    assert pairs and all("query" in p and "expected" in p for p in pairs)


def test_run_eval_finds_rhyme_and_reports_aggregates(db_path):
    conn = _conn(db_path)
    pairs = [
        {"query": "stainless", "expected": "brainless", "mode": "single", "anchor": "tail"},
        {
            "query": "stainless",
            "expected": "zzznotarealword",
            "mode": "single",
            "anchor": "tail",
        },
    ]
    try:
        report = eval_service.run_eval(pairs, limit=25, conn=conn)
    finally:
        conn.close()

    hit, miss = report.rows
    assert hit.found and hit.rank is not None and hit.rank <= 5
    assert hit.similarity is not None
    assert not miss.found and miss.rank is None and miss.similarity is None

    assert report.total == 2
    assert report.hits == 1
    assert report.hit_rate == pytest.approx(0.5)
    assert report.mrr == pytest.approx((1.0 / hit.rank) / 2)
    assert report.median_rank == hit.rank


def test_run_eval_empty_report():
    report = eval_service.run_eval([], limit=10)
    assert report.total == 0
    assert report.hit_rate == 0.0
    assert report.mrr == 0.0
    assert report.median_rank is None
