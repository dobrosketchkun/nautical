"""Phase 8 tests: user-managed exclusion list."""

import sqlite3

from nautical.exclude import load_exclusions, parse_exclude_flag, resolve_exclusions
from nautical.search.decoder import find_multiword, multiword_cache_key
from nautical.search.words import find_rhymes, rhymes_cache_key


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_load_exclusions_missing_file(tmp_path):
    assert load_exclusions(tmp_path / "nope.txt") == set()


def test_load_exclusions_parses_comments_and_case(tmp_path):
    path = tmp_path / "exclude.txt"
    path.write_text("# comment\nCull\n\nnaught  # inline\n", encoding="utf-8")
    assert load_exclusions(path) == {"cull", "naught"}


def test_parse_exclude_flag_splits_commas_and_spaces():
    assert parse_exclude_flag("cull, naught  Skinless") == {
        "cull",
        "naught",
        "skinless",
    }
    assert parse_exclude_flag(None) == set()


def test_resolve_merges_file_and_flag(tmp_path):
    path = tmp_path / "exclude.txt"
    path.write_text("cull\n", encoding="utf-8")
    assert resolve_exclusions("naught", path) == frozenset({"cull", "naught"})


def test_find_rhymes_drops_excluded_word(db_path):
    baseline, _ = find_rhymes("stainless", limit=200, conn=_conn(db_path))
    words = [r.word for r in baseline]
    assert "brainless" in words
    filtered, _ = find_rhymes(
        "stainless", limit=200, exclude=frozenset({"brainless"}), conn=_conn(db_path)
    )
    assert "brainless" not in [r.word for r in filtered]
    assert "painless" in [r.word for r in filtered]


def test_find_multiword_drops_excluded_word(db_path):
    baseline, _ = find_multiword("nautical", limit=50, conn=_conn(db_path))
    assert baseline, "expected at least one tiling"
    victim = baseline[0].words[0]
    filtered, _ = find_multiword(
        "nautical", limit=50, exclude=frozenset({victim}), conn=_conn(db_path)
    )
    assert all(victim not in r.words for r in filtered)


def test_cache_key_differs_with_exclusions():
    base = rhymes_cache_key("stainless", 25, 1500, 0.5, 0.5, False)
    excl = rhymes_cache_key(
        "stainless", 25, 1500, 0.5, 0.5, False, exclude=frozenset({"brainless"})
    )
    assert base != excl

    mbase = multiword_cache_key("nautical", 25, 300, 350, 5, 2, 0.5, 0.0)
    mexcl = multiword_cache_key(
        "nautical", 25, 300, 350, 5, 2, 0.5, 0.0, exclude=frozenset({"knot"})
    )
    assert mbase != mexcl
