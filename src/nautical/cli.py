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
from .db import loader
from .phonetics import distance as distance_service
from .search import decoder as multiword_search
from .search import words as word_search
from .semantics import theme as theme_service
from .semantics import vectors as vectors_service

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

    cache_info = cache_service.stats()
    cache_mb = cache_info["size_bytes"] / (1024 * 1024)
    table.add_row("Cache", f"{cache_info['rows']:,} entries ({cache_mb:.1f} MB)")
    console.print(table)


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete all cached query results."""
    removed = cache_service.clear()
    console.print(f"[green]Cleared[/green] {removed:,} cached result set(s).")


@cache_app.command("stats")
def cache_stats() -> None:
    """Print cache row count, size, and age span."""
    info = cache_service.stats()
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
            stats = vectors_service.build_vectors(force=force)
    except vectors_service.VectorsUnavailable as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Cached[/green] {stats['rows']:,} vectors x {stats['dim']}d."
    )


@vectors_app.command("stats")
def vectors_stats() -> None:
    """Print vector-cache dimensions, row count, and paths."""
    from .config import GLOVE_MATRIX, GLOVE_VOCAB

    if not (GLOVE_MATRIX.exists() and GLOVE_VOCAB.exists()):
        console.print(
            "[red]No vector cache.[/red] Run [bold]nautical vectors build[/bold]."
        )
        raise typer.Exit(code=1)

    vecs = vectors_service.Vectors.load()
    size_mb = GLOVE_MATRIX.stat().st_size / (1024 * 1024)
    table = Table(title="Nautical vectors")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Rows", f"{len(vecs.vocab):,}")
    table.add_row("Dimensions", str(vecs.matrix.shape[1]))
    table.add_row("Matrix size", f"{size_mb:.1f} MB")
    table.add_row("Matrix path", str(GLOVE_MATRIX))
    table.add_row("Vocab path", str(GLOVE_VOCAB))
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
    result = distance_service.phonetic_distance(
        text_a,
        text_b,
        strictness=strictness,
        word_boundary_leniency=not strict_boundaries,
        multi_variant=not primary_only,
    )

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
            return vectors_service.ensure_vectors()
    except vectors_service.VectorsUnavailable as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


_ALIGN_LEGEND = "[dim]align legend: = match  ~ substitute  + insert  x delete[/dim]"


def _result_summary(count: int, elapsed: float, cached: bool) -> str:
    tag = " [green](cached)[/green]" if cached else ""
    return f"[dim]{count} result(s) in {elapsed * 1000:.0f} ms{tag}[/dim]"


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
    theme_weight: float = typer.Option(
        0.5, "--theme-weight", min=0.0, max=1.0, help="Blend: 0 = phonetics, 1 = theme."
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
        help="Comma/space-separated words to drop, merged with data/exclude.txt.",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the query-result cache for this search."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Find single-word (or, with --multiword, multi-word) sound-alikes."""
    theme_terms = theme_service.parse_terms(theme) if theme else []
    word_boundary_leniency = not strict_boundaries
    multi_variant = not primary_only
    exclusions = exclude_service.resolve_exclusions(exclude)
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
            theme_terms=theme_terms,
            theme_weight=theme_weight,
            min_theme=min_theme,
            show_align=show_align,
            word_boundary_leniency=word_boundary_leniency,
            exclusions=exclusions,
            use_cache=not no_cache,
            as_json=as_json,
        )
        return

    # When reranking by theme, pull a wider phonetic window so a semantically
    # relevant but phonetically lower match can float into the final top-N.
    fetch_limit = max(limit, 200) if theme_terms else limit
    anchor_val = _parse_anchor(anchor, default=0.5)
    use_cache = not no_cache
    cached = use_cache and cache_service.cache_get(
        word_search.rhymes_cache_key(
            text, fetch_limit, pool, strictness, anchor_val, include_self,
            word_boundary_leniency, multi_variant, exclusions,
        )
    ) is not None
    started = time.perf_counter()
    results = word_search.find_rhymes(
        text,
        limit=fetch_limit,
        pool=pool,
        strictness=strictness,
        anchor=anchor_val,
        include_self=include_self,
        word_boundary_leniency=word_boundary_leniency,
        multi_variant=multi_variant,
        exclude=exclusions,
        use_cache=use_cache,
    )
    elapsed = time.perf_counter() - started
    if min_similarity > 0.0:
        results = [r for r in results if r.similarity >= min_similarity]

    if theme_terms:
        vecs = _ensure_vectors_or_exit()
        results = theme_service.apply_theme(
            results, theme_terms, vecs, weight=theme_weight, min_theme=min_theme
        )
    results = results[:limit]

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
                        **(
                            {"theme_fit": round(r.theme_fit, 4)}
                            if r.theme_fit is not None
                            else {}
                        ),
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
    if theme_terms:
        table.add_column("Theme", justify="right", style="green")
    table.add_column("Stress", justify="right")
    table.add_column("Syll", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        row = [
            str(i),
            r.word,
            f"{r.similarity:.3f}",
            f"{r.full_similarity:.2f}",
            f"{r.tail_similarity:.2f}",
        ]
        if theme_terms:
            row.append(f"{r.theme_fit:+.2f}" if r.theme_fit is not None else "-")
        row += [f"{r.stress_similarity:.2f}", str(r.syllable_count), r.ipa]
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
    theme_terms: list[str],
    theme_weight: float,
    min_theme: float | None,
    show_align: bool,
    word_boundary_leniency: bool = True,
    exclusions: frozenset[str] | None = None,
    use_cache: bool = True,
    as_json: bool = False,
) -> None:
    exclusions = exclusions or frozenset()
    fetch_limit = max(limit, 100) if theme_terms else limit
    cached = use_cache and cache_service.cache_get(
        multiword_search.multiword_cache_key(
            text, fetch_limit, beam, pool, max_words, min_words, strictness, anchor,
            word_boundary_leniency, exclusions,
        )
    ) is not None
    started = time.perf_counter()
    results = multiword_search.find_multiword(
        text,
        limit=fetch_limit,
        beam_width=beam,
        cand_per_pos=pool,
        max_words=max_words,
        min_words=min_words,
        strictness=strictness,
        anchor=anchor,
        word_boundary_leniency=word_boundary_leniency,
        exclude=exclusions,
        use_cache=use_cache,
    )
    elapsed = time.perf_counter() - started
    if min_similarity > 0.0:
        results = [r for r in results if r.similarity >= min_similarity]

    if theme_terms:
        vecs = _ensure_vectors_or_exit()
        results = theme_service.apply_theme(
            results, theme_terms, vecs, weight=theme_weight, min_theme=min_theme
        )
    results = results[:limit]

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
                        **(
                            {"theme_fit": round(r.theme_fit, 4)}
                            if r.theme_fit is not None
                            else {}
                        ),
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
    if theme_terms:
        table.add_column("Theme", justify="right", style="green")
    table.add_column("Words", justify="right")
    table.add_column("IPA")
    for i, r in enumerate(results, start=1):
        row = [
            str(i),
            r.phrase,
            f"{r.score:.3f}",
            f"{r.similarity:.3f}",
            f"{r.naturalness:.2f}",
        ]
        if theme_terms:
            row.append(f"{r.theme_fit:+.2f}" if r.theme_fit is not None else "-")
        row += [str(r.num_words), r.ipa]
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

    vecs = _ensure_vectors_or_exit()
    seed_vec = vecs.term_vector(seeds)
    if seed_vec is None:
        console.print(
            f"[yellow]None of the seed(s) are in the vocabulary:[/yellow] "
            f"{', '.join(seeds)}"
        )
        raise typer.Exit(code=1)

    # Full-vocab vectors resolve any seed, but chain suggestions should stay
    # within our lexicon; mask neighbors to real lexicon words.
    try:
        allowed = vectors_service._lexicon_words()
    except vectors_service.VectorsUnavailable:
        allowed = None
    neighbors = vecs.most_similar(
        seed_vec, topn=limit, exclude=set(seeds), allowed=allowed
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

    if not neighbors:
        console.print(f"[yellow]No related words found for[/yellow] {seeds}.")
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
        None, "--pairs", help="Corpus JSON (default: docs/eval_pairs.json)."
    ),
    limit: int = typer.Option(50, "--limit", help="Rank window: hit if within top-N."),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the query-result cache."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Replay the curated corpus and report rediscovery rank + MRR/hit-rate."""
    path = Path(pairs_path) if pairs_path else eval_service.DEFAULT_PAIRS_PATH
    try:
        pairs = eval_service.load_pairs(path)
    except FileNotFoundError:
        console.print(f"[red]Corpus not found:[/red] {path}")
        raise typer.Exit(code=1)
    if not pairs:
        console.print(f"[yellow]No pairs in corpus:[/yellow] {path}")
        raise typer.Exit(code=1)

    # Load vectors once only if some pair asks for a theme rerank.
    vectors = None
    if any(p.get("theme") for p in pairs):
        vectors = _ensure_vectors_or_exit()

    started = time.perf_counter()
    report = eval_service.run_eval(
        pairs, limit=limit, use_cache=not no_cache, vectors=vectors
    )
    elapsed = time.perf_counter() - started

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "limit": report.limit,
                    "total": report.total,
                    "hits": report.hits,
                    "hit_rate": round(report.hit_rate, 4),
                    "mrr": round(report.mrr, 4),
                    "median_rank": report.median_rank,
                    "rows": [
                        {
                            "query": r.query,
                            "expected": r.expected,
                            "mode": r.mode,
                            "anchor": r.anchor,
                            "theme": r.theme,
                            "found": r.found,
                            "rank": r.rank,
                            "similarity": round(r.similarity, 4)
                            if r.similarity is not None
                            else None,
                            "theme_fit": round(r.theme_fit, 4)
                            if r.theme_fit is not None
                            else None,
                        }
                        for r in report.rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    table = Table(title=f"Evaluation ({path.name})")
    table.add_column("Query", style="cyan")
    table.add_column("Expected", style="cyan")
    table.add_column("Mode")
    table.add_column("Anchor")
    table.add_column("Theme", style="green")
    table.add_column("Rank", justify="right", style="magenta")
    table.add_column("Sim", justify="right")
    for r in report.rows:
        rank_str = str(r.rank) if r.rank is not None else "[red]-[/red]"
        sim_str = f"{r.similarity:.3f}" if r.similarity is not None else "-"
        table.add_row(
            r.query,
            r.expected,
            r.mode,
            r.anchor,
            r.theme or "-",
            rank_str,
            sim_str,
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
    console.print(_result_summary(report.total, elapsed, cached=False))


if __name__ == "__main__":
    app()
