"""CLI integration checks for the Phase 9 score/context contract."""

import json

from typer.testing import CliRunner

from nautical import cli
from nautical.phonetics.align import Alignment
from nautical.search.ranking import ScoreComponents
from nautical.search.words import RhymeResult


runner = CliRunner()


def _result() -> RhymeResult:
    return RhymeResult(
        word="brainless",
        frequency=1.0,
        syllable_count=2,
        ipa="breɪnləs",
        alignment=Alignment(pairs=[], total_cost=0.0),
        scores=ScoreComponents(
            phonetic_similarity=0.9,
            full_similarity=0.8,
            tail_similarity=1.0,
            stress_similarity=1.0,
            boundary_surprise=0.25,
            base_score=1.025,
            rank_score=1.025,
        ),
    )


def test_rhymes_help_exposes_seed_workflow():
    result = runner.invoke(cli.app, ["rhymes", "--help"])
    assert result.exit_code == 0
    assert "--seed" in result.stdout
    assert "--seed-limit" in result.stdout


def test_seed_expansion_and_json_score_contract(monkeypatch):
    seen = {}

    monkeypatch.setattr(cli, "_ensure_vectors_or_exit", lambda: object())
    monkeypatch.setattr(cli.vectors_service, "lexicon_words", lambda: {"bank", "money"})
    monkeypatch.setattr(
        cli.theme_service,
        "expand_seed_terms",
        lambda seeds, vectors, limit, allowed: ["bank", "money"],
    )
    monkeypatch.setattr(cli.word_search, "find_rhymes", lambda *args, **kwargs: [_result()])

    def fake_apply_theme(results, terms, vectors, weight, min_theme):
        seen["terms"] = terms
        return results

    monkeypatch.setattr(cli.theme_service, "apply_theme", fake_apply_theme)

    result = runner.invoke(
        cli.app,
        ["rhymes", "stainless", "--seed", "bank", "--seed-limit", "1", "--json", "--no-cache"],
    )
    assert result.exit_code == 0, result.stdout
    assert seen["terms"] == ["bank", "money"]
    payload = json.loads(result.stdout)
    assert payload[0]["rank_score"] == 1.025
    assert payload[0]["boundary_surprise"] == 0.25
    assert payload[0]["context_terms"] == ["bank", "money"]
    assert "alignment" in payload[0]
