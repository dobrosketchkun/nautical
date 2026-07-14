"""Shared test fixtures."""

import pytest

from nautical.db import loader


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Build the SQLite lexicon once per test session into a temp file."""
    path = tmp_path_factory.mktemp("db") / "nautical.db"
    loader.build_db(force=True, db_path=path)
    return path
