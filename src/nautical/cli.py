"""Nautical command-line interface."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

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


if __name__ == "__main__":
    app()
