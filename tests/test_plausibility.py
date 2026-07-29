"""U1.4 Level-1 phrase plausibility tests."""

import math
import re
import sqlite3

import pytest

from nautical.search.decoder import find_multiword
from nautical.search.plausibility import (
    CLOSED_CLASS_TAGS,
    function_ok,
    geometric_freq,
    load_pos_lm_from_rows,
    phrase_naturalness,
)


def _conn(db_path):
    return sqlite3.connect(db_path)


def test_geometric_freq_penalizes_rare_member():
    # Arithmetic mean of [1, 1, 0] would be 0.67; geometric collapses toward 0.
    high = [1e-1, 1e-1, 1e-1]
    mixed = [1e-1, 1e-1, 1e-7]
    assert geometric_freq(high) > geometric_freq(mixed)


def test_function_ok_saturation():
    assert function_ok(["DT", "TO", "MD"], ["no", "to", "can"]) == pytest.approx(0.0)
    assert function_ok(["DT", "NN", "NN"], ["the", "cat", "hat"]) == 1.0  # 1/3
    assert function_ok(["NN", "NN", "NN"], ["no", "to", "'cause"]) == pytest.approx(0.0)
    # 2/3 closed saturates (needed so "no to X" 3-word tilings are demoted)
    assert function_ok(["DT", "IN", "NN"], ["the", "in", "house"]) == pytest.approx(1.0 - 2.0 / 3.0)
    assert function_ok(["DT", "TO", "NN"], ["no", "to", "call"]) == pytest.approx(1.0 - 2.0 / 3.0)


def test_pos_lm_prefers_grammatical_tag_sequence():
    # Tiny synthetic LM: DT→NN→NN is attested; DT→TO→MD is not (must back off).
    rows = [
        (1, "", "DT", math.log(0.3)),
        (1, "", "NN", math.log(0.4)),
        (1, "", "TO", math.log(0.15)),
        (1, "", "MD", math.log(0.15)),
        (2, "DT", "NN", math.log(0.8)),
        (2, "NN", "NN", math.log(0.7)),
        (2, "DT", "TO", math.log(0.05)),
        (2, "TO", "MD", math.log(0.05)),
        (3, "<s> <s>", "DT", math.log(0.5)),
        (3, "<s> DT", "NN", math.log(0.8)),
        (3, "DT NN", "NN", math.log(0.7)),
    ]
    lm = load_pos_lm_from_rows(rows)
    good = lm.pos_plausibility(["DT", "NN", "NN"])
    bad = lm.pos_plausibility(["DT", "TO", "MD"])
    assert good > bad


def test_phrase_naturalness_blend_reports_components():
    rows = [
        (1, "", "DT", math.log(0.25)),
        (1, "", "NN", math.log(0.5)),
        (1, "", "TO", math.log(0.25)),
    ]
    lm = load_pos_lm_from_rows(rows)
    nat, freq_g, pos_p, func = phrase_naturalness(
        [1e-2, 1e-2, 1e-2], ["DT", "TO", "MD"], lm
    )
    assert 0.0 <= nat <= 1.0
    assert 0.0 <= freq_g <= 1.0
    assert 0.0 <= pos_p <= 1.0
    assert func == pytest.approx(0.0)


def test_multiword_drops_no_to_class_from_top10(db_path):
    results, _ = find_multiword("nautical", limit=10, conn=_conn(db_path))
    assert results
    junk = re.compile(r"^(no|know) to\b")
    top10 = [r.phrase for r in results]
    assert not any(junk.match(p) for p in top10), top10
    top5 = results[:5]
    assert any(
        (r.scores.function_ok or 0.0) >= 0.99 for r in top5
    ), [(r.phrase, r.scores.function_ok, r.scores.pos_plausibility) for r in top5]
    assert all(r.scores.freq_naturalness is not None for r in results)
    assert all(r.scores.pos_plausibility is not None for r in results)
