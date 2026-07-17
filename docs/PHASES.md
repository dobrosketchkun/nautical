# Step One — Build Phases

Step one (see `STEP_ONE.md`) is **not** a one-shot build. It is the deepest engine in the project, so we build it in layers, each one checkable in the terminal against `some_lyrics.txt` before the next layer depends on it.

Guiding rule: **every phase ends with a command we can both run and judge.** If a result looks wrong, the phase boundaries tell us which layer to blame.

Everything is offline, Python, SQLite, terminal-first, and licensing-clean (MIT/BSD/Apache; no GPL).

---

## Phase 0 — Skeleton & data

**Goal:** project set up and all offline data present.

* Python project layout, dependency file, pinned versions.
* Acquire and stage offline data: CMUdict, a permissive g2p model, PanPhon, GloVe vectors, a word-frequency list.
* SQLite schema: lexemes, pronunciations, frequencies, (later) indexes and cached results.
* A loader that ingests the data into SQLite.

**Check:** `nautical stats` prints counts (words, pronunciations, vectors loaded) — proves the data pipeline works.

**Deferred/none.** Pure plumbing.

---

## Phase 1 — Pronunciation layer

**Goal:** any word or phrase → phoneme lattice + boundary-free representation.

* Dictionary lookup (CMUdict) with a **g2p fallback** for out-of-vocabulary words (`spifflicated`, `takodachi`).
* Normalize to a single internal phoneme representation.
* Keep word boundaries as **metadata**, and expose the flattened boundary-free string.
* Handle multiple pronunciations (a lattice, not one answer).

**Check:**
```text
nautical pronounce "not a cult"   → phonemes + boundary-free string
nautical pronounce "nautical"
nautical pronounce "spifflicated"  → g2p fallback works
```

---

## Phase 2 — Phonetic distance

**Goal:** a decomposed, feature-weighted distance between two sounds.

* PanPhon feature vectors + weighted edit distance.
* Lyric weights: cheap unstressed-vowel swaps / schwa / final-consonant drops; expensive stressed-vowel mismatch; penalized (not forbidden) syllable-count change.
* **Strictness dial** exposed.
* Emit the **phoneme alignment** (the explanation).

**Check:**
```text
nautical distance "not a cult" "nautical"   → high score + alignment
nautical distance "not a cult" "electric"   → low score
```
The `not a cult` / `nautical` alignment should visibly show the cheap substitutions and the final-`t` deletion.

---

## Phase 3 — Single-word search

**Goal:** given a selection, return ranked **single-word** sound-alikes.

* Build a phonetic index over the lexicon (in SQLite).
* Query returns ranked words with decomposed scores + alignment.
* First retrieval stage is deliberately generous; scoring trims it.

**Check:**
```text
nautical rhymes "not a cult"   → "nautical" appears near the top
nautical rhymes "stainless"    → "brainless", "painless", ...
```

---

## Phase 4 — Phonetic decoder (multi-word)

**Goal:** given a selection, return ranked **multi-word** sequences that sound like it.

* Beam / DP search that "spells out" the target sound using sequences of real words.
* **Naturalness ranking** via word frequency, so `not a cult` outranks `nawt ick ull`.
* Playful oronyms (`gnaw tickle`, `knot tickle`) still surface, ranked lower.

**Check:**
```text
nautical rhymes "nautical" --multiword
   → "not a cult", "gnaw tickle", "knot tickle", ...
```
This is the hardest phase and the one that proves the core idea.

---

## Phase 5 — Anchoring & dials

**Goal:** wire in the two anchoring modes and the control dials.

* **Tail-anchored** (from last stressed syllable) and **full-span** (whole selection echoes), computed both and slidable.
* Strictness dial (exact ↔ adventurous) affecting scoring and cutoffs.

**Check:**
```text
nautical rhymes "clean and stainless" --anchor tail   → "-ainless" family
nautical rhymes "clean and stainless" --anchor full   → "acting brainless"-type echoes
```

---

## Phase 6 — Semantic context

**Goal:** the two context features, both offline via GloVe.

* **Theme-filtering:** rerank/filter results by relevance to a given verse/theme.
* **Semantic chains:** expand a seed (`bank` → `invested`, `interest`, `currency`, ...).

**Check:**
```text
nautical rhymes "not a cult" --theme "ocean, sea, ship"   → nautical/marine matches float up
nautical chain "bank"                                     → financial word pool
```

---

## Phase 7 — Polish, caching, evaluation

**Goal:** make it pleasant and prove it against the real lyrics.

* Result caching in SQLite; readable CLI output for scores + alignments.
* A small **evaluation harness**: feed known pairs from `some_lyrics.txt`
  (`not a cult ↔ nautical`, `clean and stainless ↔ acting brainless`, ...)
  and report whether each is rediscovered and at what rank.

**Check:** the harness reports the known matches are found in sensible positions — this is the "step one done" bar from `STEP_ONE.md`.

---

## Phase 8 — Boundary leniency, variants, and exclusions

**Goal:** improve lyric-facing correctness and make noisy result families
controllable.

* Word-final consonant leniency across phrase boundaries.
* Multi-pronunciation scoring for query text.
* User-managed persistent and per-query exclusions.
* Full-vocabulary semantic vectors and Windows/Unicode robustness.

**Check:** alternate pronunciations match correctly, strict boundaries remain
available, and excluded words disappear before result limits are applied.

---

## Phase 9 — Coherent ranking and connected context

**Goal:** make every displayed signal participate consistently in an
explainable rank, measure resegmentation, and connect semantic expansion to
rhyme discovery without removing standalone exploration.

* Shared score components for single- and multi-word results:
  phonetic/full/tail, stress, naturalness where applicable, boundary surprise,
  theme fit, base score, and explicit final `rank_score`.
* Stress and boundary surprise contribute to the provisional base rank.
* Theme reranking blends with the complete base score, preserving multi-word
  naturalness and word-count costs.
* Boundary surprise compares internal word-boundary positions after global
  phoneme alignment.
* `nautical chain SEED` remains standalone.
* `nautical rhymes TEXT --seed SEED` expands a bounded semantic neighborhood
  and uses it as ranking context.
* JSON includes structured alignments and all score components.

**Checks:**
```text
nautical rhymes "not a cult" --anchor full
  → boundary surprise is high for "nautical"; Rank is the visible sort key

nautical rhymes "nautical" --multiword
  → Stress, Bound, Nat, and Rank are present; global alignment is in JSON

nautical chain "bank"
  → standalone finance neighborhood remains available

nautical rhymes "emotion" --seed "bank"
  → expanded finance context participates in reranking
```

**Deferred:** calibration of Phase 9 weights against a larger judged corpus,
and broad bridge search across every term in a semantic chain.

---

## Suggested grouping

If we want fewer, larger checkpoints:

* **Foundation:** Phases 0–2 (data, pronunciation, distance).
* **Search:** Phases 3–5 (single-word, decoder, anchoring). ← the heart of step one.
* **Context & proof:** Phases 6–7 (semantics, evaluation).
* **Consistency:** Phases 8–9 (lyric correctness, coherent ranking, connected context).

We can stop and reassess after any phase.
