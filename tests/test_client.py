"""Phase 10 tests for path resolution and the supported Python facade."""

import shutil
from importlib.resources import files

import pytest

import nautical
from nautical import cache as cache_service
from nautical import config
from nautical.client import Nautical
from nautical.errors import NotInitializedError


def test_path_resolution_precedence(monkeypatch, tmp_path):
    env_dir = tmp_path / "env"
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("NAUTICAL_DATA_DIR", str(env_dir))
    assert config.NauticalPaths.resolve().data_dir == env_dir.resolve()
    assert config.NauticalPaths.resolve(explicit).data_dir == explicit.resolve()


def test_path_resolution_source_then_platform(monkeypatch, tmp_path):
    checkout = tmp_path / "checkout"
    monkeypatch.delenv("NAUTICAL_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "_source_checkout_root", lambda: checkout)
    assert config.NauticalPaths.resolve().data_dir == (checkout / "data").resolve()

    monkeypatch.setattr(config, "_source_checkout_root", lambda: None)
    monkeypatch.setattr(config, "user_data_dir", lambda *args, **kwargs: str(tmp_path / "user"))
    assert config.NauticalPaths.resolve().data_dir == (tmp_path / "user").resolve()


def test_public_api_exports_client_and_result_types():
    assert nautical.Nautical is Nautical
    assert nautical.RhymeResult is not None
    assert nautical.ScoreComponents is not None
    assert files("nautical.db").joinpath("schema.sql").is_file()
    assert files("nautical.resources").joinpath("eval_pairs.json").is_file()


def test_uninitialized_client_has_actionable_error(tmp_path):
    engine = Nautical(tmp_path / "missing")
    with pytest.raises(NotInitializedError, match="build_db"):
        engine.rhymes("stainless")


def test_client_rhyme_search_uses_isolated_data_dir(db_path, tmp_path):
    data_dir = tmp_path / "client"
    data_dir.mkdir()
    shutil.copy2(db_path, data_dir / "nautical.db")
    engine = Nautical(data_dir)

    response = engine.rhymes("stainless", limit=3, use_cache=False)
    assert response.mode == "single"
    assert response.candidates
    assert all(result.rank_score for result in response.candidates)


def test_two_clients_do_not_share_cache_files(tmp_path):
    first = Nautical(tmp_path / "first")
    second = Nautical(tmp_path / "second")
    cache_service.cache_put("one", {"value": 1}, first.paths.cache_db_path)

    assert first.cache_stats()["rows"] == 1
    assert second.cache_stats()["rows"] == 0
