"""U3 ScoringWeights load/save and hash tests."""

from pathlib import Path

import pytest

from nautical.scoring_weights import (
    DEFAULT_WEIGHTS,
    ScoringWeights,
    load_weights,
    save_weights,
)


def test_defaults_round_trip(tmp_path: Path):
    path = tmp_path / "scoring_weights.json"
    save_weights(DEFAULT_WEIGHTS, path)
    loaded = load_weights(path)
    assert loaded == DEFAULT_WEIGHTS
    assert loaded.to_dict() == DEFAULT_WEIGHTS.to_dict()


def test_from_dict_ignores_unknown_keys():
    w = ScoringWeights.from_dict(
        {"stress_weight": 0.2, "not_a_real_field": 99.0}
    )
    assert w.stress_weight == pytest.approx(0.2)
    assert w.boundary_weight == DEFAULT_WEIGHTS.boundary_weight


def test_weights_hash_changes_when_value_changes():
    a = DEFAULT_WEIGHTS.weights_hash()
    b = DEFAULT_WEIGHTS.with_updates(stress_weight=0.25).weights_hash()
    assert a != b
    assert len(a) == 16


def test_missing_file_returns_defaults(tmp_path: Path):
    assert load_weights(tmp_path / "missing.json") == DEFAULT_WEIGHTS
