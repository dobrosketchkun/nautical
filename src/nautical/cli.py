"""Nautical command-line interface."""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.table import Table

from . import pronounce as pronounce_service
from .db import loader

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


if __name__ == "__main__":
    app()
