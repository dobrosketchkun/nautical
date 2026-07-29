"""Nautical command-line interface."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import cache as cache_service
from . import eval as eval_service
from . import exclude as exclude_service
from . import pronounce as pronounce_service
from .client import Nautical
from .db import loader
from .db.quality import DEFAULT_MIN_QUALITY
from .errors import NauticalError, NotInitializedError
from .phonetics import distance as distance_service
from .search import decoder as multiword_search
from .search import words as word_search
from .semantics import theme as theme_service
from .semantics import vectors as vectors_service
from . import tune as tune_service

# Force UTF-8 on stdout/stderr so IPA and box-drawing characters survive on
# Windows consoles (default cp1252 cannot encode them).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def _install_click_typer_compat() -> None:
    """Keep ``--help`` rendering under click >= 8.2 with older typer.

    click 8.2 made ``Parameter.make_metavar(ctx)`` and
    ``ParamType.get_metavar(param, ctx)`` require the ``ctx`` argument, but
    typer 0.15 calls them without it (and typer's ``TyperArgument`` overrides
    ``make_metavar(self)``), so help rendering raises ``TypeError``. Upgrading
    typer is the clean fix, but this makes the CLI robust even when the
    environment can't be upgraded. It is a safe no-op once typer/click agree.
    """
    import inspect

    import click
    from click.core import Parameter
    from click.types import ParamType

    if getattr(_install_click_typer_compat, "_done", False):
        return

    def _resolve_ctx(ctx):
        if ctx is not None:
            return ctx
        ctx = click.get_current_context(silent=True)
        if ctx is not None:
            return ctx
        return click.Context(click.Command("nautical"))

    if "ctx" in inspect.signature(ParamType.get_metavar).parameters:
        _orig_get_metavar = ParamType.get_metavar

        def _get_metavar(self, param, ctx=None):  # type: ignore[override]
            return _orig_get_metavar(self, param, _resolve_ctx(ctx))

        ParamType.get_metavar = _get_metavar

    if "ctx" in inspect.signature(Parameter.make_metavar).parameters:
        _orig_make_metavar = Parameter.make_metavar

        def _make_metavar(self, ctx=None):  # type: ignore[override]
            return _orig_make_metavar(self, _resolve_ctx(ctx))

        Parameter.make_metavar = _make_metavar

    # typer's TyperArgument overrides make_metavar(self); click 8.2 calls it as
    # make_metavar(ctx). Give it a signature that works either way.
    try:
        from typer.core import TyperArgument
    except ImportError:
        TyperArgument = None
    if TyperArgument is not None:

        def _typer_arg_make_metavar(self, ctx=None):  # type: ignore[override]
            if self.metavar is not None:
                return self.metavar
            var = (self.name or "").upper()
            if not self.required:
                var = f"[{var}]"
            try:
                type_var = self.type.get_metavar(self, _resolve_ctx(ctx))
            except TypeError:
                type_var = self.type.get_metavar(self)
            if type_var:
                var += f":{type_var}"
            if self.nargs != 1:
                var += "..."
            return var

        TyperArgument.make_metavar = _typer_arg_make_metavar

    _install_click_typer_compat._done = True  # type: ignore[attr-defined]


_install_click_typer_compat()

app = typer.Typer(help="Nautical - offline phonetic rhyme discovery workbench.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(db_app, name="db")
vectors_app = typer.Typer(help="Semantic vector operations (GloVe).")
app.add_typer(vectors_app, name="vectors")
cache_app = typer.Typer(help="Query-result cache operations.")
app.add_typer(cache_app, name="cache")

console = Console()
engine = Nautical()


def _resolve_engine(weights_path: str | None = None) -> Nautical:
    if weights_path:
        return Nautical(weights_path=weights_path)
    return engine


@db_app.command("build")
def db_build(
    force: bool = typer.Option(
        False, "--force", help="Drop the existing database and rebuild from scratch."
    ),
) -> None:
    """Create the schema and ingest CMUdict + wordfreq into SQLite."""
    with console.status("Building lexicon from CMUdict + wordfreq..."):
        stats = engine.build_db(force=force)
    console.print(
        f"[green]Built[/green] {stats['lexeme_count']:,} lexemes / "
        f"{stats['pronunciation_count']:,} pronunciations "
        f"({stats['lexeme_with_frequency']:,} with frequency)."
    )


@app.command("stats")
def stats() -> None:
    """Print database counts and metadata."""
    try:
        all_stats = engine.stats()
        info = all_stats["database"]
    except NotInitializedError:
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
    if "lexeme_quality_ge_default" in info:
        table.add_row(
            f"Lexemes quality ≥ {DEFAULT_MIN_QUALITY}",
            f"{int(info.get('lexeme_quality_ge_default', 0)):,}",
        )
    if "lexeme_mean_quality" in info:
        table.add_row("Mean quality", info.get("lexeme_mean_quality", "?"))
    table.add_row("DB size", f"{size_mb:.1f} MB")
    table.add_row("Schema version", info.get("schema_version", "?"))
    table.add_row("Built at", info.get("built_at", "?"))
    table.add_row("DB path", info.get("db_path", "?"))

    cache_info = all_stats["cache"]
    cache_mb = cache_info["size_bytes"] / (1024 * 1024)
    table.add_row("Cache", f"{cache_info['rows']:,} entries ({cache_mb:.1f} MB)")
    table.add_row("Data directory", all_stats["data_dir"])
    table.add_row("Vectors ready", "yes" if all_stats["vectors_ready"] else "no")
    console.print(table)


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete all cached query results."""
    removed = engine.clear_cache()
    console.print(f"[green]Cleared[/green] {removed:,} cached result set(s).")


@cache_app.command("stats")
def cache_stats() -> None:
    """Print cache row count, size, and age span."""
    info = engine.cache_stats()
    size_mb = info["size_bytes"] / (1024 * 1024)
    table = Table(title="Nautical query cache")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Entries", f"{info['rows']:,}")
    table.add_row("Size", f"{size_mb:.1f} MB")
    table.add_row("Oldest", str(info["oldest"] or "-"))
    table.add_row("Newest", str(info["newest"] or "-"))
    table.add_row("Path", info["path"])
    console.print(table)


@vectors_app.command("build")
def vectors_build(
    force: bool = typer.Option(
        False, "--force", help="Rebuild the vector cache even if it exists."
    ),
    dim: int = typer.Option(
        vectors_service.GLOVE_DIM, "--dim", help="GloVe dimension (informational)."
    ),
) -> None:
    """Download (if needed) and cache the full GloVe vocabulary (~400K vectors)."""
    if dim != vectors_service.GLOVE_DIM:
        console.print(
            f"[yellow]Note:[/yellow] this build is wired for "
            f"{vectors_service.GLOVE_DIM}d; --dim is informational."
        )
    try:
        with console.status("Building GloVe vector cache (downloads once)..."):
            stats = engine.build_vectors(force=force)
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Cached[/green] {stats['rows']:,} vectors x {stats['dim']}d."
    )


@vectors_app.command("stats")
def vectors_stats() -> None:
    """Print vector-cache dimensions, row count, and paths."""
    matrix_path = engine.paths.glove_matrix
    vocab_path = engine.paths.glove_vocab
    if not vectors_service.vectors_ready(engine.paths):
        console.print(
            "[red]No vector cache.[/red] Run [bold]nautical vectors build[/bold]."
        )
        raise typer.Exit(code=1)

    vecs = vectors_service.Vectors.load(engine.paths)
    size_mb = matrix_path.stat().st_size / (1024 * 1024)
    table = Table(title="Nautical vectors")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Rows", f"{len(vecs.vocab):,}")
    table.add_row("Dimensions", str(vecs.matrix.shape[1]))
    table.add_row("Matrix size", f"{size_mb:.1f} MB")
    table.add_row("Matrix path", str(matrix_path))
    table.add_row("Vocab path", str(vocab_path))
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
    try:
        phrase = engine.pronounce(text)
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

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
    strict_boundaries: bool = typer.Option(
        False,
        "--strict-boundaries",
        help="Disable cheap word-final consonant deletion (word-boundary leniency).",
    ),
    primary_only: bool = typer.Option(
        False,
        "--primary-only",
        help="Score only each side's primary pronunciation (skip variants).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Phonetic distance between two texts, with the aligning explanation."""
    try:
        result = engine.distance(
            text_a,
            text_b,
            strictness=strictness,
            word_boundary_leniency=not strict_boundaries,
            multi_variant=not primary_only,
        )
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

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


def _ensure_vectors_or_exit() -> vectors_service.Vectors:
    """Load vectors (building/downloading if needed) or exit with guidance."""
    try:
        with console.status("Loading semantic vectors (downloads once if absent)..."):
            return engine.ensure_vectors()
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


_ALIGN_LEGEND = "[dim]align legend: = match  ~ substitute  + insert  x delete[/dim]"


def _alignment_to_json(alignment) -> list[dict]:
    """Return a stable structured representation of an alignment."""
    return [
        {
            "src": pair.src.ipa if pair.src else None,
            "tgt": pair.tgt.ipa if pair.tgt else None,
            "op": pair.op,
            "cost": round(pair.cost, 4),
        }
        for pair in alignment.pairs
    ]


def _result_summary(count: int, elapsed: float, cached: bool) -> str:
    tag = " [green](cached)[/green]" if cached else ""
    return f"[dim]{count} result(s) in {elapsed * 1000:.0f} ms{tag}[/dim]"


def _format_primary_with_variants(
    primary: str, variants: list[str], max_show: int = 3
) -> str:
    """Render primary spelling with a compact alternate-forms suffix."""
    if not variants:
        return primary
    shown = variants[:max_show]
    suffix = "/".join(shown)
    if len(variants) > max_show:
        suffix += "…"
    return f"{primary}  [{suffix}]"


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
    theme: str = typer.Option(
        None,
        "--theme",
        help="Rerank by semantic fit to these terms, e.g. 'ocean, sea, ship'.",
    ),
    seed: str = typer.Option(
        None,
        "--seed",
        help="Expand semantic seed(s) into context terms, then rerank matches.",
    ),
    seed_limit: int = typer.Option(
        25,
        "--seed-limit",
        min=0,
        help="Number of lexicon neighbors used to expand --seed.",
    ),
    theme_weight: float = typer.Option(
        None,
        "--theme-weight",
        min=0.0,
        max=1.0,
        help="Blend: 0 = phonetics, 1 = theme (default from scoring weights).",
    ),
    min_theme: float = typer.Option(
        None, "--min-theme", help="Drop results whose theme_fit is below this (-1..1)."
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
    strict_boundaries: bool = typer.Option(
        False,
        "--strict-boundaries",
        help="Disable cheap word-final consonant deletion (word-boundary leniency).",
    ),
    primary_only: bool = typer.Option(
        False,
        "--primary-only",
        help="Score only the query's primary pronunciation (skip variants).",
    ),
    exclude: str = typer.Option(
        None,
        "--exclude",
        help="Words to drop, merged with exclude.txt in the resolved data directory.",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the query-result cache for this search."
    ),
    diversity: float = typer.Option(
        0.35,
        "--diversity",
        min=0.0,
        max=1.0,
        help="Multi-word only: MMR word-overlap threshold (0 = pure rank order).",
    ),
    prefix_cap: int = typer.Option(
        3,
        "--prefix-cap",
        min=0,
        help="Multi-word only: max results sharing the same first word (0 = no cap).",
    ),
    min_quality: float = typer.Option(
        DEFAULT_MIN_QUALITY,
        "--quality",
        min=0.0,
        max=1.0,
        help="Min lexicon quality (0 = admit junk spellings / rare names).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Find single-word (or, with --multiword, multi-word) sound-alikes."""
    word_boundary_leniency = not strict_boundaries
    multi_variant = not primary_only
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
            theme=theme,
            seed=seed,
            seed_limit=seed_limit,
            theme_weight=theme_weight,
            min_theme=min_theme,
            show_align=show_align,
            word_boundary_leniency=word_boundary_leniency,
            exclude=exclude,
            diversity=diversity,
            prefix_cap=prefix_cap,
            min_quality=min_quality,
            use_cache=not no_cache,
            as_json=as_json,
        )
        return

    anchor_val = _parse_anchor(anchor, default=0.5)
    try:
        response = engine.rhymes(
            text,
            limit=limit,
            pool=pool,
            strictness=strictness,
            anchor=anchor_val,
            min_similarity=min_similarity,
            theme=theme,
            seed=seed,
            seed_limit=seed_limit,
            theme_weight=theme_weight,
            min_theme=min_theme,
            include_self=include_self,
            word_boundary_leniency=word_boundary_leniency,
            multi_variant=multi_variant,
            exclude=exclude,
            min_quality=min_quality,
            use_cache=not no_cache,
        )
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    results = response.candidates
    theme_terms = response.context_terms
    elapsed = response.elapsed_ms / 1000.0
    cached = response.cached
    if seed and not as_json:
        seed_terms = theme_service.parse_terms(seed)
        neighbors = [term for term in theme_terms if term not in seed_terms]
        console.print(
            f"[dim]seed context ({', '.join(seed_terms)}): "
            f"{', '.join(neighbors) if neighbors else 'no neighbors'}[/dim]"
        )

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "word": r.word,
                        "rank_score": round(r.rank_score, 4),
                        "similarity": round(r.similarity, 4),
                        "full_similarity": round(r.full_similarity, 4),
                        "tail_similarity": round(r.tail_similarity, 4),
                        "stress_similarity": round(r.stress_similarity, 4),
                        "boundary_surprise": round(r.boundary_surprise, 4),
                        "frequency": r.frequency,
                        "syllable_count": r.syllable_count,
                        "ipa": r.ipa,
                        "variants": list(r.variants),
                        "quality": round(r.quality, 4),
                        "alignment": _alignment_to_json(r.alignment),
                        **(
                            {"theme_fit": round(r.theme_fit, 4)}
                            if r.theme_fit is not None
                            else {}
                        ),
                        **({"context_terms": theme_terms} if theme_terms else {}),
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
    table.add_column("Rank", justify="right", style="magenta")
    table.add_column("Sim", justify="right", style="magenta")
    table.add_column("Full", justify="right")
    table.add_column("Tail", justify="right")
    if theme_terms:
        table.add_column("Theme", justify="right", style="green")
    table.add_column("Stress", justify="right")
    table.add_column("Bound", justify="right")
    table.add_column("Qual", justify="right")
    table.add_column("Syll", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        row = [
            str(i),
            _format_primary_with_variants(r.word, r.variants),
            f"{r.rank_score:.3f}",
            f"{r.similarity:.3f}",
            f"{r.full_similarity:.2f}",
            f"{r.tail_similarity:.2f}",
        ]
        if theme_terms:
            row.append(f"{r.theme_fit:+.2f}" if r.theme_fit is not None else "-")
        row += [
            f"{r.stress_similarity:.2f}",
            f"{r.boundary_surprise:.2f}",
            f"{r.quality:.2f}",
            str(r.syllable_count),
            r.ipa,
        ]
        table.add_row(*row)
    console.print(table)
    console.print(_result_summary(len(results), elapsed, cached))

    if show_align:
        console.print(_ALIGN_LEGEND)
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
    theme: str | None,
    seed: str | None,
    seed_limit: int,
    theme_weight: float | None,
    min_theme: float | None,
    show_align: bool,
    word_boundary_leniency: bool = True,
    exclude: str | None = None,
    diversity: float = 0.35,
    prefix_cap: int = 3,
    min_quality: float = DEFAULT_MIN_QUALITY,
    use_cache: bool = True,
    as_json: bool = False,
) -> None:
    try:
        response = engine.rhymes_multiword(
            text,
            limit=limit,
            pool=pool,
            beam_width=beam,
            max_words=max_words,
            min_words=min_words,
            strictness=strictness,
            anchor=anchor,
            min_similarity=min_similarity,
            theme=theme,
            seed=seed,
            seed_limit=seed_limit,
            theme_weight=theme_weight,
            min_theme=min_theme,
            word_boundary_leniency=word_boundary_leniency,
            exclude=exclude,
            diversity=diversity,
            prefix_cap=prefix_cap,
            min_quality=min_quality,
            use_cache=use_cache,
        )
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    results = response.candidates
    theme_terms = response.context_terms
    elapsed = response.elapsed_ms / 1000.0
    cached = response.cached
    if seed and not as_json:
        seed_terms = theme_service.parse_terms(seed)
        neighbors = [term for term in theme_terms if term not in seed_terms]
        console.print(
            f"[dim]seed context ({', '.join(seed_terms)}): "
            f"{', '.join(neighbors) if neighbors else 'no neighbors'}[/dim]"
        )

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "phrase": r.phrase,
                        "words": r.words,
                        "rank_score": round(r.rank_score, 4),
                        "similarity": round(r.similarity, 4),
                        "stress_similarity": round(r.stress_similarity, 4),
                        "naturalness": round(r.naturalness, 4),
                        "freq_naturalness": round(r.scores.freq_naturalness, 4)
                        if r.scores.freq_naturalness is not None
                        else None,
                        "pos_plausibility": round(r.scores.pos_plausibility, 4)
                        if r.scores.pos_plausibility is not None
                        else None,
                        "function_ok": round(r.scores.function_ok, 4)
                        if r.scores.function_ok is not None
                        else None,
                        "boundary_surprise": round(r.boundary_surprise, 4),
                        "num_words": r.num_words,
                        "ipa": r.ipa,
                        "variants": list(r.variants),
                        "quality": round(r.quality, 4),
                        "alignment": _alignment_to_json(r.alignment),
                        "chunks": [
                            {
                                "word": word,
                                "alignment": _alignment_to_json(alignment),
                            }
                            for word, alignment in r.chunks
                        ],
                        **(
                            {"theme_fit": round(r.theme_fit, 4)}
                            if r.theme_fit is not None
                            else {}
                        ),
                        **({"context_terms": theme_terms} if theme_terms else {}),
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
    table.add_column("Rank", justify="right", style="magenta")
    table.add_column("Sim", justify="right")
    table.add_column("Nat", justify="right")
    if theme_terms:
        table.add_column("Theme", justify="right", style="green")
    table.add_column("Stress", justify="right")
    table.add_column("Bound", justify="right")
    table.add_column("Qual", justify="right")
    table.add_column("Words", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        row = [
            str(i),
            _format_primary_with_variants(r.phrase, r.variants),
            f"{r.rank_score:.3f}",
            f"{r.similarity:.3f}",
            f"{r.naturalness:.2f}",
        ]
        if theme_terms:
            row.append(f"{r.theme_fit:+.2f}" if r.theme_fit is not None else "-")
        row += [
            f"{r.stress_similarity:.2f}",
            f"{r.boundary_surprise:.2f}",
            f"{r.quality:.2f}",
            str(r.num_words),
            r.ipa,
        ]
        table.add_row(*row)
    console.print(table)
    console.print(_result_summary(len(results), elapsed, cached))

    if show_align:
        console.print(_ALIGN_LEGEND)
        for r in results:
            console.print(f"\n[cyan]{r.phrase}[/cyan] ({r.score:.3f})")
            for word, alignment in r.chunks:
                console.print(f"  [dim]{word}[/dim]")
                console.print(alignment.pretty())


@app.command("chain")
def chain(
    seed: str = typer.Argument(..., help="Seed word(s), comma-separated (e.g. 'bank')."),
    limit: int = typer.Option(25, "--limit", help="Number of related words to return."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Expand a seed into a pool of semantically related words (GloVe)."""
    seeds = theme_service.parse_terms(seed)
    if not seeds:
        console.print("[yellow]Provide at least one seed word.[/yellow]")
        raise typer.Exit(code=1)

    try:
        neighbors = engine.chain(seeds, limit=limit)
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    if not neighbors:
        console.print(
            f"[yellow]No related words found, or seeds are not in the vocabulary:[/yellow] "
            f"{', '.join(seeds)}"
        )

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "seed": seeds,
                    "related": [
                        {"word": word, "similarity": round(score, 4)}
                        for word, score in neighbors
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    table = Table(title=f"Semantic chain: {', '.join(seeds)}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Word", style="cyan")
    table.add_column("Similarity", justify="right", style="magenta")
    for i, (word, score) in enumerate(neighbors, start=1):
        table.add_row(str(i), word, f"{score:.3f}")
    console.print(table)


@app.command("eval")
def eval_cmd(
    pairs_path: str = typer.Option(
        None, "--pairs", help="Corpus JSON (default: packaged eval_pairs.json)."
    ),
    limit: int = typer.Option(50, "--limit", help="Rank window: hit if within top-N."),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the query-result cache."
    ),
    weights_path: str = typer.Option(
        None, "--weights", help="Scoring weights JSON (default: data_dir file or built-ins)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Replay the curated corpus and report rediscovery rank + MRR/hit-rate."""
    path = Path(pairs_path) if pairs_path else eval_service.DEFAULT_PAIRS_PATH
    active = _resolve_engine(weights_path)
    started = time.perf_counter()
    try:
        report = active.evaluate(
            pairs_path=pairs_path, limit=limit, use_cache=not no_cache
        )
    except FileNotFoundError:
        console.print(f"[red]Corpus not found:[/red] {path}")
        raise typer.Exit(code=1)
    except NauticalError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    if not report.rows:
        console.print(f"[yellow]No pairs in corpus:[/yellow] {path}")
        raise typer.Exit(code=1)
    elapsed = time.perf_counter() - started

    if as_json:
        payload = {
            "limit": report.limit,
            "total": report.total,
            "hits": report.hits,
            "hit_rate": round(report.hit_rate, 4),
            "mrr": round(report.mrr, 4),
            "median_rank": report.median_rank,
            "negative_total": report.negative_total,
            "negative_leaks": report.negative_leaks,
            "negative_leak_rate": round(report.negative_leak_rate, 4),
            "mean_negative_leak_rank": report.mean_negative_leak_rank,
            "diversity": None
            if report.diversity is None
            else {
                "query": report.diversity.query,
                "top_k": report.diversity.top_k,
                "distinct_ipa_ratio": round(report.diversity.distinct_ipa_ratio, 4),
                "distinct_first_word_ratio": round(
                    report.diversity.distinct_first_word_ratio, 4
                ),
            },
            "rows": [
                {
                    "query": r.query,
                    "expected": r.expected,
                    "mode": r.mode,
                    "anchor": r.anchor,
                    "theme": r.theme,
                    "polarity": r.polarity,
                    "found": r.found,
                    "rank": r.rank,
                    "success": r.success,
                    "similarity": round(r.similarity, 4)
                    if r.similarity is not None
                    else None,
                    "rank_score": round(r.rank_score, 4)
                    if r.rank_score is not None
                    else None,
                    "boundary_surprise": round(r.boundary_surprise, 4)
                    if r.boundary_surprise is not None
                    else None,
                    "theme_fit": round(r.theme_fit, 4)
                    if r.theme_fit is not None
                    else None,
                }
                for r in report.rows
            ],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title=f"Evaluation ({path.name})")
    table.add_column("Query", style="cyan")
    table.add_column("Expected", style="cyan")
    table.add_column("Pol")
    table.add_column("Mode")
    table.add_column("Anchor")
    table.add_column("Theme", style="green")
    table.add_column("Rank", justify="right", style="magenta")
    table.add_column("OK")
    table.add_column("Sim", justify="right")
    table.add_column("Score", justify="right")
    for r in report.rows:
        rank_str = str(r.rank) if r.rank is not None else "[red]-[/red]"
        sim_str = f"{r.similarity:.3f}" if r.similarity is not None else "-"
        score_str = f"{r.rank_score:.3f}" if r.rank_score is not None else "-"
        ok = "[green]y[/green]" if r.success else "[red]n[/red]"
        table.add_row(
            r.query,
            r.expected,
            r.polarity[:3],
            r.mode,
            r.anchor,
            r.theme or "-",
            rank_str,
            ok,
            sim_str,
            score_str,
        )
    console.print(table)

    median = report.median_rank
    median_str = f"{median:.0f}" if median is not None else "-"
    console.print(
        f"[bold]hit-rate@{report.limit}:[/bold] {report.hits}/{report.total} "
        f"({report.hit_rate:.0%})   "
        f"[bold]MRR:[/bold] {report.mrr:.3f}   "
        f"[bold]median rank (hits):[/bold] {median_str}"
    )
    if report.negative_total:
        mean_leak = report.mean_negative_leak_rank
        mean_str = f"{mean_leak:.1f}" if mean_leak is not None else "-"
        console.print(
            f"[bold]negatives:[/bold] leaks {report.negative_leaks}/"
            f"{report.negative_total} ({report.negative_leak_rate:.0%})   "
            f"[bold]mean leak rank:[/bold] {mean_str}"
        )
    if report.diversity is not None:
        d = report.diversity
        console.print(
            f"[bold]diversity@{d.top_k} ({d.query}):[/bold] "
            f"IPA {d.distinct_ipa_ratio:.2f}   "
            f"first-word {d.distinct_first_word_ratio:.2f}"
        )
    console.print(_result_summary(report.total + report.negative_total, elapsed, cached=False))


@app.command("tune")
def tune_cmd(
    trials: int = typer.Option(40, "--trials", min=0, help="Random-search trial count."),
    seed: int = typer.Option(0, "--seed", help="RNG seed for reproducibility."),
    limit: int = typer.Option(50, "--limit", help="Eval rank window."),
    subset: int = typer.Option(
        None,
        "--subset",
        help="Evaluate only the first N corpus pairs (faster smoke).",
    ),
    pairs_path: str = typer.Option(
        None, "--pairs", help="Corpus JSON (default: packaged eval_pairs.json)."
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass result cache."),
    write: bool = typer.Option(
        False, "--write", help="Write best weights to data_dir/scoring_weights.json."
    ),
    weights_path: str = typer.Option(
        None, "--weights", help="Starting weights JSON (default: built-ins / data_dir)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Random-search scoring weights against the eval corpus.

    Objective: MRR(positives) - 0.5 * negative_leak_rate. Larger trial budgets
    are slow until U4 speeds cold queries; use --subset / --trials for smoke.
    """
    active = _resolve_engine(weights_path)
    try:
        active._require_db()
    except NotInitializedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    pairs = eval_service.load_pairs(Path(pairs_path) if pairs_path else None)
    vectors = (
        active.ensure_vectors() if any(p.get("theme") for p in pairs) else None
    )
    started = time.perf_counter()
    with console.status(f"Tuning ({trials} trials)..."):
        report = tune_service.run_tune(
            pairs=pairs,
            trials=trials,
            seed=seed,
            limit=limit,
            use_cache=not no_cache,
            base=active.weights,
            vectors=vectors,
            db_path=active.paths.db_path,
            cache_db_path=active.paths.cache_db_path,
            subset=subset,
            include_diversity=False,
        )
    elapsed = time.perf_counter() - started

    out_path = None
    if write:
        out_path = str(tune_service.write_best(report, active.weights_path))

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "seed": report.seed,
                    "improved": report.improved,
                    "baseline": {
                        "objective": round(report.baseline.objective, 4),
                        "mrr": round(report.baseline.mrr, 4),
                        "negative_leak_rate": round(
                            report.baseline.negative_leak_rate, 4
                        ),
                        "hit_rate": round(report.baseline.hit_rate, 4),
                        "weights": report.baseline.weights.to_dict(),
                    },
                    "best": {
                        "objective": round(report.best.objective, 4),
                        "mrr": round(report.best.mrr, 4),
                        "negative_leak_rate": round(report.best.negative_leak_rate, 4),
                        "hit_rate": round(report.best.hit_rate, 4),
                        "weights": report.best.weights.to_dict(),
                    },
                    "written": out_path,
                    "elapsed_s": round(elapsed, 2),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    console.print(
        f"[bold]baseline[/bold]  obj={report.baseline.objective:.3f}  "
        f"MRR={report.baseline.mrr:.3f}  "
        f"neg_leak={report.baseline.negative_leak_rate:.0%}  "
        f"hit={report.baseline.hit_rate:.0%}"
    )
    console.print(
        f"[bold]best[/bold]      obj={report.best.objective:.3f}  "
        f"MRR={report.best.mrr:.3f}  "
        f"neg_leak={report.best.negative_leak_rate:.0%}  "
        f"hit={report.best.hit_rate:.0%}"
    )
    if report.improved:
        console.print("[green]Improved over defaults.[/green]")
    else:
        console.print("[yellow]No improvement over defaults.[/yellow]")
    if out_path:
        console.print(f"Wrote weights to [cyan]{out_path}[/cyan]")
    console.print(f"({len(report.trials)} configs in {elapsed:.1f}s, seed={report.seed})")


if __name__ == "__main__":
    app()
