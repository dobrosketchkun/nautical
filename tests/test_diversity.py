"""U1.2 tests: presentation-layer multi-word diversity."""

from dataclasses import dataclass

import pytest

from nautical.search.diversity import select_diverse, word_overlap_distance


@dataclass
class _Row:
    words: list[str]
    phrase: str = ""

    def __post_init__(self) -> None:
        if not self.phrase:
            self.phrase = " ".join(self.words)


def test_word_overlap_distance_identical_and_disjoint():
    assert word_overlap_distance(["no", "to", "can"], ["no", "to", "can"]) == 0.0
    assert word_overlap_distance(["a", "b"], ["c", "d"]) == 1.0


def test_word_overlap_distance_partial_overlap():
    # |{no,to,can} ∩ {no,to,call}| / 3 = 2/3 → distance 1/3
    assert word_overlap_distance(
        ["no", "to", "can"], ["no", "to", "call"]
    ) == pytest.approx(1.0 - 2.0 / 3.0)
    # |{naughty,can} ∩ {no,to,can}| / 3 = 1/3 → distance 2/3
    assert word_overlap_distance(
        ["naughty", "can"], ["no", "to", "can"]
    ) == pytest.approx(1.0 - 1.0 / 3.0)


def test_select_diverse_zero_is_pure_rank_order():
    rows = [
        _Row(["no", "to", "can"]),
        _Row(["no", "to", "call"]),
        _Row(["no", "to", "kill"]),
        _Row(["naughty", "can"]),
    ]
    assert select_diverse(rows, limit=3, diversity=0.0, prefix_cap=3) == rows[:3]


def test_select_diverse_mmr_and_prefix_cap():
    rows = [
        _Row(["no", "to", "can"]),
        _Row(["no", "to", "cause"]),
        _Row(["no", "to", "call"]),
        _Row(["no", "to", "kill"]),
        _Row(["naughty", "can"]),
        _Row(["gnaw", "to", "can"]),
        _Row(["note", "a", "cult"]),
    ]
    selected = select_diverse(rows, limit=5, diversity=0.35, prefix_cap=3)
    assert len(selected) <= 5
    # First-word counts respect the prefix cap.
    counts: dict[str, int] = {}
    for row in selected:
        counts[row.words[0]] = counts.get(row.words[0], 0) + 1
    assert all(n <= 3 for n in counts.values())
    # Near-duplicates of "no to can" are skipped by MMR; a different prefix enters.
    phrases = [r.phrase for r in selected]
    assert phrases[0] == "no to can"
    assert "naughty can" in phrases or "gnaw to can" in phrases or "note a cult" in phrases
