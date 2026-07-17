# Nautical — Phonetic Creativity Workbench

**Nautical** is an offline, terminal-first engine for discovering how words and
phrases *sound alike* — including across word boundaries. Give it a word or a
phrase you already wrote and ask *"what sounds like this?"*; it returns a ranked,
**explainable** list of real single words and invented multi-word sequences that
echo the sound.

It is built to rediscover the kind of playful oronyms found in real lyrics:

- `not a cult` ↔ `nautical`
- `clean and stainless` ↔ `acting brainless`
- `nautical` → `not a cult`, `gnaw tickle`, `knot tickle`

The guiding principle is **retrieval-first, transformation-second, generation-third**:
find what already sounds like your selection before manufacturing altered forms.
This first vertical ("Step One") covers retrieval and the phonetic decoder; the
browser UI and word-transformation "puns" are deferred (see [Roadmap](#roadmap)).

---

## Table of contents

- [Key ideas](#key-ideas)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [The dials (how to tune results)](#the-dials-how-to-tune-results)
- [How it works](#how-it-works)
- [Python library API](#python-library-api)
- [Data & storage](#data--storage)
- [Windows / conda note](#windows--conda-note)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)

---

## Key ideas

- **Boundary-free matching.** Everything is compared as phoneme sequences; word
  boundaries are kept only as metadata, never as hard separators. That is what
  lets `not a cult` (3 words) match `nautical` (1 word).
- **Feature-weighted phonetic distance.** Similarity uses articulatory features
  (via PanPhon) with lyric-tuned weights: unstressed-vowel and schwa edits are
  cheap, word-final consonant deletion is cheap, stressed-vowel mismatches are
  expensive.
- **Two anchoring modes, on a dial.** *Full-span* (the whole selection echoes)
  ↔ *tail-anchored* (match from the last stressed syllable — clean end-rhymes).
- **A phonetic decoder for multi-word results.** A beam search "spells out" a
  target sound with sequences of real words, kept sane by word-frequency
  naturalness scoring (so `not a cult` outranks `nawt ick ull`, but playful
  oronyms like `gnaw tickle` still surface lower down).
- **Semantics from the start.** Rerank results by how well they fit a verse's
  **theme**, browse a standalone semantic **chain**, or pass `--seed` to expand
  a concept and use that neighborhood directly while ranking rhymes.
- **Every result is explained.** Each candidate ships with its phoneme alignment
  and a decomposed score (phonetic / tail / stress / naturalness /
  boundary-surprise / theme-fit), plus the explicit `rank_score` used to order it.
- **Fully offline.** No paid APIs, no phone-home model servers. SQLite for
  storage; everything runs in-process.

---

## Requirements

- **Python ≥ 3.10** (developed against the `general_env_1` conda environment).
- Dependencies (installed automatically, see `pyproject.toml`):
  `cmudict`, `wordfreq`, `typer`, `rich`, `g2p_en`, `panphon`, `numpy`.
- **~2 GB temporary free disk** while building semantic vectors; after a
  successful build Nautical deletes the archive/raw text and retains only the
  ~460 MB normalized matrix + vocabulary. The phonetic core is much smaller.
- Network access **once** to download GloVe (only if you use `chain`/`--theme`).
  Everything else is offline.

---

## Installation

From a cloned project:

```bash
# Activate the environment (conda example)
conda activate general_env_1

# Normal local install — exposes the `nautical` command
pip install .

# Or, for development, keep imports linked to the checkout
pip install -e .

# One-time: build the lexicon (CMUdict + word frequencies) into SQLite
nautical db build
```

That is enough for all phonetic commands (`pronounce`, `distance`, `rhymes`).

The semantic commands (`chain`, and `rhymes --theme`) need word vectors. They
**auto-download and build on first use**, or you can pre-build them:

```bash
# Downloads GloVe once; retains only matrix + vocab after a successful build
nautical vectors build
```

You can verify your setup at any time:

```bash
nautical stats          # lexicon counts, DB size, cache info
nautical vectors stats  # vector-cache dimensions and paths
```

---

## Quick start

```bash
# Single-word sound-alikes
nautical rhymes "stainless"

# Boundary-free: rediscover the headline oronym
nautical rhymes "not a cult" --anchor full

# Multi-word decoder: spell a word out with real words
nautical rhymes "nautical" --multiword

# Show the phoneme alignment (the explanation) for each result
nautical rhymes "stainless" --align

# Rerank by a verse theme
nautical rhymes "barnacle" --theme "ocean, sea, ship"

# Expand a semantic seed and use its neighborhood as rhyme context
nautical rhymes "emotion" --seed "bank"

# Compare two texts directly
nautical distance "not a cult" "nautical"

# Expand a seed into related words to rhyme against
nautical chain "bank"
```

> On Windows with conda, prefix output commands with `--no-capture-output`
> (see [Windows / conda note](#windows--conda-note)).

---

## Command reference

Run `nautical --help`, or `nautical <command> --help`, for the full option list.

### `nautical rhymes TEXT` — find sound-alikes

The primary command. Single-word by default; add `--multiword` for the decoder.

| Option | Default | Meaning |
|--------|---------|---------|
| `--limit N` | 25 | Max results to return. |
| `--pool N` | 1500 | Candidate pool size (recall knob; higher = more thorough, slower). |
| `--strictness F` | 0.5 | 0 = forgiving/adventurous, 1 = strict/exact. |
| `--anchor V` | 0.5 (single) / 0.0 (multiword) | `full`, `tail`, or a float 0..1. Blends full-span vs rhyme-tail similarity. |
| `--min-similarity F` | 0.0 | Drop results below this similarity. |
| `--theme "a, b, c"` | — | Rerank by semantic fit to these terms. |
| `--seed "a, b"` | — | Expand semantic seed terms, then use the expanded neighborhood as context. |
| `--seed-limit N` | 25 | Number of lexicon neighbors added per seed search. |
| `--theme-weight F` | 0.5 | Blend: 0 = phonetics only, 1 = theme only. |
| `--min-theme F` | — | Drop results whose theme_fit is below this (−1..1). |
| `--include-self` | off | Include the query word itself in results. |
| `--multiword` | off | Use the multi-word phonetic decoder. |
| `--beam N` | 60 | Beam width for the decoder. |
| `--max-words N` / `--min-words N` | 5 / 2 | Word-count bounds per multi-word result. |
| `--align` | off | Print the phoneme alignment for each result. |
| `--strict-boundaries` | off | Disable cheap word-final consonant deletion. |
| `--primary-only` | off | Score only the query's primary pronunciation (skip variants). |
| `--exclude "w1,w2"` | — | Drop these words; merged with `exclude.txt` in the resolved data directory. |
| `--no-cache` | off | Bypass the query-result cache for this search. |
| `--json` | off | Emit JSON instead of a table. |

Examples:

```bash
nautical rhymes "emotion" --anchor tail --limit 10
nautical rhymes "stainless" --exclude "spineless,skinless"
nautical rhymes "not a cult" --multiword --max-words 3 --min-words 2
nautical rhymes "barnacle" --theme "ocean, sea, ship" --theme-weight 0.7 --json
nautical rhymes "emotion" --seed "bank" --seed-limit 15
```

### `nautical distance TEXT_A TEXT_B` — score two texts

Prints IPA for both sides, the similarity/stress scores, and the full phoneme
alignment as an explanation.

Options: `--strictness`, `--strict-boundaries`, `--primary-only`, `--json`.

```bash
nautical distance "read" "red"          # multi-variant: matches R EH D exactly
nautical distance "not a cult" "nautical" --align  # alignment shown by default
```

### `nautical pronounce TEXT` — word/phrase → IPA

Converts to IPA via CMUdict with a `g2p_en` fallback for invented words.

Options: `--all` (show every pronunciation variant), `--json`.

```bash
nautical pronounce "nautical"
nautical pronounce "spifflicated" --all
```

### `nautical chain SEED` — semantic expansion

Expands a seed word (or comma-separated seeds) into a standalone pool of
semantically related **lexicon** words. Requires vectors. To connect that pool
directly to rhyme discovery, use `nautical rhymes TEXT --seed SEED`.

Options: `--limit`, `--json`.

```bash
nautical chain "bank" --limit 15
nautical chain "ocean, sea"
```

### `nautical eval` — measure rediscovery quality

Replays the packaged curated corpus and reports each pair's
rediscovery **rank**, plus **MRR**, **hit-rate**, and median rank. Useful when
tuning phonetic weights.

Options: `--pairs PATH`, `--limit N` (rank window), `--no-cache`, `--json`.

```bash
nautical eval
nautical eval --limit 25 --no-cache
```

### `nautical db build` — build the lexicon

Creates the schema and ingests CMUdict + word frequencies into SQLite. Run once
after install (and again with `--force` after a schema change).

```bash
nautical db build          # build if absent
nautical db build --force  # drop and rebuild
```

### `nautical vectors build` — build the semantic cache

Downloads GloVe 6B (once) and caches the full ~400K-word normalized matrix.

```bash
nautical vectors build
nautical vectors build --force   # rebuild from the local raw file
```

### `nautical cache …` — manage the query cache

Search results are cached in a separate `cache.db` in the resolved data directory,
keyed on the phonetic
parameters (themes are applied *after* the cache, so one cached search serves
every theme). Clear it after changing phonetic weights or rebuilding the lexicon.

```bash
nautical cache stats
nautical cache clear
```

### `nautical stats` — database + cache overview

Shows lexeme/pronunciation counts, DB size, schema version, and cache summary.

---

## The dials (how to tune results)

- **Strictness** (`--strictness 0..1`): slide between *adventurous* slant rhymes
  and *exact* matches. Low values let feature-similar sounds through cheaply.
- **Anchor** (`--anchor full|tail|0..1`): `full` rewards a whole-selection echo
  (great for oronyms like `not a cult ↔ nautical`); `tail` rewards clean
  end-rhymes (`stainless → brainless, painless`). The default blends both.
- **Theme** (`--theme` + `--theme-weight`): float on-theme candidates up without
  hiding the phonetic score — `theme_fit` is reported as its own column.
- **Semantic seed** (`--seed` + `--seed-limit`): expand a concept through the
  same neighborhood used by `chain`, then use the expanded terms as context.
- **Boundary surprise**: compares internal word boundaries after phoneme
  alignment. `stainless → brainless` is low-surprise; `not a cult → nautical`
  is high-surprise. It is reported separately and contributes a small,
  provisional ranking bonus.
- **Word-boundary leniency** (on by default; `--strict-boundaries` to disable):
  makes word-final consonants cheap to drop, matching how singers elide them
  (the `/t/` in *not a cult*). Turn it off for stricter, literal matching.
- **Multi-variant scoring** (on by default; `--primary-only` to disable): scores
  every CMUdict pronunciation of the query and keeps the best per candidate
  (e.g. `read` = R IY D / R EH D).
- **Exclusions**: hide specific words via `--exclude "w1,w2"` and/or by adding
  lines to `exclude.txt` in the resolved data directory (one lowercase word per
  line, `#` comments). This
  is a *filter*, not a sound-collapse — distinct words that merely sound alike
  stay separate; you decide what to hide.

---

## How it works

```text
selection (word or phrase)
  → pronounce (CMUdict, g2p fallback)   → phoneme lattice (IPA)
  → flatten boundaries                  → boundary-free phoneme string
  → search:
       single-word n-gram index         → word candidates      (search/words.py)
       phonetic decoder + naturalness    → multi-word candidates (search/decoder.py)
  → score: feature-weighted alignment (phonetics/align.py, distance.py)
           anchored blend full ↔ tail   (phonetics/anchor.py)
           stress + boundary surprise   (search/ranking.py)
           naturalness (multi-word)     (search/decoder.py)
  → context rerank (theme/seed, GloVe)  (semantics/)
  → present rank_score + components + phoneme alignment
```

Search is two-stage: a phoneme bi/tri-gram overlap index retrieves a generous
candidate pool, then the feature-weighted aligner (Needleman–Wunsch) reranks it.
When anchoring favors the tail, a separate rhyme-signature index is unioned in so
end-rhymes that share little else still surface. The multi-word decoder tiles the
target with real words via an onset index + beam DP, ranked by a blend of
phonetic fit and word-frequency naturalness.

All candidates use the same named score contract. `rank_score` is the actual
ordering key; `similarity` remains the phonetic component. Theme/seed context is
blended with the complete base score, so multi-word naturalness, stress, and
boundary surprise are not discarded during semantic reranking. Phase 9 weights
are provisional; calibration against a larger judged corpus remains deferred.
`rank_score` is therefore an ordering value and may exceed 1 — it is not a
probability or a replacement for the separately reported similarity.

---

## Python library API

The supported embedding API is the `Nautical` client. An explicit data
directory makes application instances isolated and reproducible:

```python
from nautical import Nautical

engine = Nautical(data_dir="./nautical-data")
engine.initialize()  # builds the phonetic lexicon if absent

response = engine.rhymes("stainless", limit=10)
for candidate in response.candidates:
    print(candidate.word, candidate.rank_score, candidate.boundary_surprise)
```

Semantic methods build/download vectors only when requested:

```python
engine.build_vectors()
response = engine.rhymes("emotion", seed="bank")
neighbors = engine.chain("bank")
```

Expected setup failures raise subclasses of `NauticalError`; library calls do
not raise Typer exits or print Rich tables. Existing low-level modules remain
available for internal/advanced use, but `Nautical` and the result types exported
from `nautical` are the supported public surface.

---

## Data & storage

Mutable artifacts never live inside an installed wheel. The data directory is
resolved in this order:

1. `Nautical(data_dir=...)`
2. `NAUTICAL_DATA_DIR`
3. `<checkout>/data` when running from an editable/source checkout
4. the platform user-data directory for a normal installation

Typical normal-install defaults are `%LOCALAPPDATA%\nautical` on Windows,
`~/.local/share/nautical` on Linux, and
`~/Library/Application Support/nautical` on macOS. `nautical stats` prints the
resolved directory.

| Relative path | What | Rebuild with |
|------|------|--------------|
| `nautical.db` | Lexicon, pronunciations, phonetic indexes | `nautical db build` |
| `cache.db` | Query-result cache | `nautical cache clear` (auto-rebuilds) |
| `exclude.txt` | Your word exclusion list (hand-edited) | — |
| `vectors/glove.6B.300d.npy` | Normalized full-vocabulary matrix | `nautical vectors build` |
| `vectors/glove.6B.300d.vocab.txt` | Matrix row vocabulary | `nautical vectors build` |

Storage is SQLite (single-file, zero-setup). Similarity math runs in-process.
The downloaded GloVe ZIP and extracted raw text are build inputs and are deleted
after both runtime vector files are validated.

---


## Project layout

```text
src/nautical/
  client.py            # supported embeddable Nautical API
  cli.py               # Typer CLI (all commands)
  config.py            # platform/editable data path resolution
  pronounce.py         # CMUdict + g2p → IPA, enriched segments/variants
  g2p.py               # grapheme→phoneme fallback
  exclude.py           # user exclusion list loader
  cache.py             # SQLite query-result cache
  eval.py              # evaluation harness
  phonology/           # ARPAbet→IPA, syllabification helpers
  phonetics/
    features.py        # PanPhon feature distance
    align.py           # Needleman–Wunsch alignment + gap/sub costs
    distance.py        # high-level phonetic distance
    anchor.py          # rhyme-tail extraction + anchored scoring
  search/
    index.py           # phoneme n-gram + rhyme-tail indexes
    words.py           # single-word search
    decoder.py         # multi-word phonetic decoder (beam DP)
    normalize.py       # phonetic normalization for indexing
  semantics/
    vectors.py         # GloVe load/build (full vocabulary)
    theme.py           # theme reranking + seed parsing
  db/loader.py         # schema + ingest (CMUdict, wordfreq)
  resources/           # packaged evaluation corpus

docs/                  # PROJECT.MD, STEP_ONE.md, PHASES.md, NOTES.md, eval_pairs.json
tests/                 # pytest suite
```

---

## Roadmap

**In scope (built):** boundary-free retrieval, feature-weighted distance,
single-word search, multi-word decoder, tail/full-span anchoring, coherent
decomposed ranking, boundary-surprise scoring, theme reranking, standalone and
connected semantic chains, caching, evaluation harness.

**Deferred (later phases):**

- Word-*transformation* "puns" (portmanteau / morpheme substitution, e.g.
  `unstoppable → pun-stoppable`; name insertion, e.g. `interested → Ina-terested`).
- Audio / forced alignment.
- Japanese–English cross-language echoes.
- The browser editor UI.

## PS

The name of the repo is a wink to rhymes by Cali in [『TAKO∞TAKOVER』 - Ninomae Ina'nis](https://www.youtube.com/watch?v=6sAQ1wuYzxk)