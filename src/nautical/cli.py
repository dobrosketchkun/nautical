"""Nautical command-line interface."""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.table import Table

from . import pronounce as pronounce_service
from .db import loader
from .phonetics import distance as distance_service
from .search import decoder as multiword_search
from .search import words as word_search

# Force UTF-8 on stdout/stderr so IPA and box-drawing characters survive on
# Windows consoles (default cp1252 cannot encode them).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

app = typer.Typer(help="Nautical - offline phonetic rhyme discovery workbench.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(db_app, name="db")

console = Console()


@db_app.command("build")
def db_build(
    force: bool = typer.Option(
        False, "--force", help="Drop the existing database and rebuild from scratch."
    ),
) -> None:
    """Create the schema and ingest CMUdict + wordfreq into SQLite."""
    with console.status("Building lexicon from CMUdict + wordfreq..."):
        stats = loader.build_db(force=force)
    console.print(
        f"[green]Built[/green] {stats['lexeme_count']:,} lexemes / "
        f"{stats['pronunciation_count']:,} pronunciations "
        f"({stats['lexeme_with_frequency']:,} with frequency)."
    )


@app.command("stats")
def stats() -> None:
    """Print database counts and metadata."""
    try:
        info = loader.get_stats()
    except FileNotFoundError:
        console.print(
            "[red]No database found.[/red] Run [bold]nautical db build[/bold] first."
        )
        raise typer.Exit(code=1)

    size_mb = int(info.get("db_size_bytes", "0")) / (1024 * 1024)

    table = Table(title="Nautical database")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Lexemes", f"{int(info.get('lexeme_count', 0)):,}")
    table.add_row("Pronunciations", f"{int(info.get('pronunciation_count', 0)):,}")
    table.add_row(
        "Lexemes with frequency", f"{int(info.get('lexeme_with_frequency', 0)):,}"
    )
    table.add_row("DB size", f"{size_mb:.1f} MB")
    table.add_row("Schema version", info.get("schema_version", "?"))
    table.add_row("Built at", info.get("built_at", "?"))
    table.add_row("DB path", info.get("db_path", "?"))
    console.print(table)


def _phrase_to_dict(phrase: pronounce_service.PhrasePronunciation) -> dict:
    return {
        "text": phrase.text,
        "boundary_free": phrase.boundary_free,
        "tokens": [
            {
                "word": word_pron.word,
                "boundaries": list(phrase.boundaries[i]),
                "variants": [
                    {
                        "source": variant.source,
                        "arpabet": variant.arpabet,
                        "ipa": variant.ipa,
                        "stress": variant.stress,
                        "syllable_count": variant.syllable_count,
                    }
                    for variant in word_pron.variants
                ],
            }
            for i, word_pron in enumerate(phrase.tokens)
        ],
    }


@app.command("pronounce")
def pronounce(
    text: str = typer.Argument(..., help="Word or phrase to pronounce."),
    show_all: bool = typer.Option(
        False, "--all", help="Show every pronunciation variant, not just the primary."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Convert a word or phrase to IPA (CMUdict, with g2p fallback)."""
    phrase = pronounce_service.pronounce_phrase(text)

    if as_json:
        typer.echo(json.dumps(_phrase_to_dict(phrase), ensure_ascii=False, indent=2))
        return

    table = Table(title=f"Pronunciation: {text}")
    table.add_column("Token", style="cyan")
    table.add_column("Source")
    table.add_column("ARPAbet")
    table.add_column("IPA", style="magenta")
    table.add_column("Stress")
    table.add_column("Syll", justify="right")

    for word_pron in phrase.tokens:
        if not word_pron.variants:
            table.add_row(word_pron.word, "-", "(no pronunciation)", "", "", "")
            continue
        variants = word_pron.variants if show_all else word_pron.variants[:1]
        for i, variant in enumerate(variants):
            table.add_row(
                word_pron.word if i == 0 else "",
                variant.source,
                " ".join(variant.arpabet),
                variant.ipa,
                variant.stress,
                str(variant.syllable_count),
            )

    console.print(table)
    console.print(
        f"[bold]boundary-free:[/bold] [magenta]{phrase.boundary_free}[/magenta]"
    )


@app.command("distance")
def distance(
    text_a: str = typer.Argument(..., help="First word or phrase."),
    text_b: str = typer.Argument(..., help="Second word or phrase."),
    strictness: float = typer.Option(
        0.5, "--strictness", min=0.0, max=1.0, help="0 = forgiving, 1 = strict."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Phonetic distance between two texts, with the aligning explanation."""
    result = distance_service.phonetic_distance(text_a, text_b, strictness=strictness)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "text_a": result.text_a,
                    "text_b": result.text_b,
                    "ipa_a": result.ipa_a,
                    "ipa_b": result.ipa_b,
                    "similarity": round(result.similarity, 4),
                    "stress_similarity": round(result.stress_similarity, 4),
                    "total_cost": round(result.total_cost, 4),
                    "alignment": [
                        {
                            "src": pair.src.ipa if pair.src else None,
                            "tgt": pair.tgt.ipa if pair.tgt else None,
                            "op": pair.op,
                            "cost": round(pair.cost, 4),
                        }
                        for pair in result.alignment.pairs
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    table = Table(title=f"Distance: {text_a}  vs  {text_b}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("IPA A", f"[magenta]{result.ipa_a}[/magenta]")
    table.add_row("IPA B", f"[magenta]{result.ipa_b}[/magenta]")
    table.add_row("Similarity", f"{result.similarity:.3f}")
    table.add_row("Stress similarity", f"{result.stress_similarity:.3f}")
    table.add_row("Total cost", f"{result.total_cost:.3f}")
    console.print(table)
    console.print(result.alignment.pretty())


def _parse_anchor(value: str | None, default: float) -> float:
    """Parse an ``--anchor`` value: ``tail`` -> 1.0, ``full`` -> 0.0, or a float."""
    if value is None:
        return default
    token = value.strip().lower()
    if token == "tail":
        return 1.0
    if token == "full":
        return 0.0
    try:
        parsed = float(token)
    except ValueError:
        raise typer.BadParameter(
            f"--anchor must be 'tail', 'full', or a float 0..1 (got {value!r})."
        )
    return max(0.0, min(1.0, parsed))


@app.command("rhymes")
def rhymes(
    text: str = typer.Argument(..., help="Word or phrase to find sound-alikes for."),
    limit: int = typer.Option(25, "--limit", help="Max results to return."),
    pool: int = typer.Option(1500, "--pool", help="Candidate pool size (recall knob)."),
    strictness: float = typer.Option(
        0.5, "--strictness", min=0.0, max=1.0, help="0 = forgiving, 1 = strict."
    ),
    anchor: str = typer.Option(
        None,
        "--anchor",
        help="'tail', 'full', or a float 0..1 (0 = full-span, 1 = rhyme tail). "
        "Default: 0.5 single-word, 0.0 multi-word.",
    ),
    min_similarity: float = typer.Option(
        0.0, "--min-similarity", min=0.0, max=1.0, help="Drop results below this sim."
    ),
    include_self: bool = typer.Option(
        False, "--include-self", help="Include the query word itself in results."
    ),
    multiword: bool = typer.Option(
        False, "--multiword", help="Decode multi-word sound-alikes (e.g. 'not a cult')."
    ),
    beam: int = typer.Option(60, "--beam", help="Beam width for the multi-word decoder."),
    max_words: int = typer.Option(
        5, "--max-words", help="Max words per multi-word result."
    ),
    min_words: int = typer.Option(
        2, "--min-words", help="Min words per multi-word result."
    ),
    show_align: bool = typer.Option(
        False, "--align", help="Print the phoneme alignment for each result."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Find single-word (or, with --multiword, multi-word) sound-alikes."""
    if multiword:
        _rhymes_multiword(
            text,
            limit=limit,
            pool=pool,
            beam=beam,
            max_words=max_words,
            min_words=min_words,
            strictness=strictness,
            anchor=_parse_anchor(anchor, default=0.0),
            min_similarity=min_similarity,
            show_align=show_align,
            as_json=as_json,
        )
        return

    results = word_search.find_rhymes(
        text,
        limit=limit,
        pool=pool,
        strictness=strictness,
        anchor=_parse_anchor(anchor, default=0.5),
        include_self=include_self,
    )
    if min_similarity > 0.0:
        results = [r for r in results if r.similarity >= min_similarity]

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "word": r.word,
                        "similarity": round(r.similarity, 4),
                        "full_similarity": round(r.full_similarity, 4),
                        "tail_similarity": round(r.tail_similarity, 4),
                        "stress_similarity": round(r.stress_similarity, 4),
                        "frequency": r.frequency,
                        "syllable_count": r.syllable_count,
                        "ipa": r.ipa,
                    }
                    for r in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not results:
        console.print(f"[yellow]No matches found for[/yellow] {text!r}.")
        return

    table = Table(title=f"Rhymes for: {text}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Word", style="cyan")
    table.add_column("Sim", justify="right", style="magenta")
    table.add_column("Full", justify="right")
    table.add_column("Tail", justify="right")
    table.add_column("Stress", justify="right")
    table.add_column("Syll", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        table.add_row(
            str(i),
            r.word,
            f"{r.similarity:.3f}",
            f"{r.full_similarity:.2f}",
            f"{r.tail_similarity:.2f}",
            f"{r.stress_similarity:.2f}",
            str(r.syllable_count),
            r.ipa,
        )
    console.print(table)

    if show_align:
        for r in results:
            console.print(f"\n[cyan]{r.word}[/cyan] ({r.similarity:.3f})")
            console.print(r.alignment.pretty())


def _rhymes_multiword(
    text: str,
    limit: int,
    pool: int,
    beam: int,
    max_words: int,
    min_words: int,
    strictness: float,
    anchor: float,
    min_similarity: float,
    show_align: bool,
    as_json: bool,
) -> None:
    results = multiword_search.find_multiword(
        text,
        limit=limit,
        beam_width=beam,
        cand_per_pos=pool,
        max_words=max_words,
        min_words=min_words,
        strictness=strictness,
        anchor=anchor,
    )
    if min_similarity > 0.0:
        results = [r for r in results if r.similarity >= min_similarity]

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "phrase": r.phrase,
                        "words": r.words,
                        "score": round(r.score, 4),
                        "similarity": round(r.similarity, 4),
                        "stress_similarity": round(r.stress_similarity, 4),
                        "naturalness": round(r.naturalness, 4),
                        "num_words": r.num_words,
                        "ipa": r.ipa,
                    }
                    for r in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not results:
        console.print(f"[yellow]No multi-word matches found for[/yellow] {text!r}.")
        return

    table = Table(title=f"Multi-word sound-alikes for: {text}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Phrase", style="cyan")
    table.add_column("Score", justify="right", style="magenta")
    table.add_column("Sim", justify="right")
    table.add_column("Nat", justify="right")
    table.add_column("Words", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        table.add_row(
            str(i),
            r.phrase,
            f"{r.score:.3f}",
            f"{r.similarity:.3f}",
            f"{r.naturalness:.2f}",
            str(r.num_words),
            r.ipa,
        )
    console.print(table)

    if show_align:
        for r in results:
            console.print(f"\n[cyan]{r.phrase}[/cyan] ({r.score:.3f})")
            for word, alignment in r.chunks:
                console.print(f"  [dim]{word}[/dim]")
                console.print(alignment.pretty())


if __name__ == "__main__":
    app()
