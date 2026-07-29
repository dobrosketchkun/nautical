"""U3 tune smoke tests."""

import sqlite3

from nautical import tune as tune_service
from nautical.scoring_weights import DEFAULT_WEIGHTS


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_tune_smoke_two_trials(db_path, tmp_path):
    pairs = [
        {
            "query": "stainless",
            "expected": "brainless",
            "mode": "single",
            "anchor": "tail",
        },
        {
            "query": "stainless",
            "expected": "zzznotarealword",
            "mode": "single",
            "anchor": "tail",
            "polarity": "negative",
            "max_rank": 5,
        },
    ]
    conn = _conn(db_path)
    try:
        report = tune_service.run_tune(
            pairs=pairs,
            trials=2,
            seed=1,
            limit=25,
            use_cache=False,
            base=DEFAULT_WEIGHTS,
            conn=conn,
            include_diversity=False,
        )
    finally:
        conn.close()

    assert report.seed == 1
    assert len(report.trials) == 3  # baseline + 2
    assert isinstance(report.best.weights, type(DEFAULT_WEIGHTS))
    out = tune_service.write_best(report, tmp_path / "scoring_weights.json")
    assert out.is_file()
