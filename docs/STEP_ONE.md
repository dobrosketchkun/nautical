# Step One: Rhyme Discovery — "What sounds like this?"

This document narrows the full vision in `PROJECT.MD` down to the **first thing we build**. It reflects the decisions made while discussing the concept and the example lyrics in `some_lyrics.txt`.

The full product remains the goal. This is the first vertical of it.

---

## 1. Scope of step one

### In scope

The single feature: the writer **selects a word or phrase they already wrote** and asks *"what sounds like this?"* The system returns a ranked, explainable list of real words and multi-word sequences that sound like the selection.

Concretely, it must be able to rediscover matches like the ones already present in `some_lyrics.txt`:

* `not a cult` → `nautical` (and the reverse: `nautical` → `not a cult`)
* `clean and stainless` → `acting brainless`
* `nautical` → `not a cult`, `gnaw tickle`, `knot tickle` (playful oronyms are wanted, not noise)

### Explicitly deferred (the "puns")

These are *constructions* (modifying a word), not *retrieval* (finding an existing sound-alike). They come later:

* portmanteau / morpheme substitution — `unstoppable` → `pun-stoppable`
* name / motif insertion — `interested` → `Ina-terested`
* audio / forced alignment
* Japanese–English cross-language echoes
* the browser editor UI

The dividing line for step one is **retrieval vs. transformation**: find what already sounds like this (including across word boundaries and as multi-word phrases) — do not manufacture altered forms yet.

---

## 2. What "sounds like this" means here

### 2.1 Boundary-free matching

Everything is compared as **phoneme sequences with word boundaries kept only as metadata**, never as hard separators. This is what lets `not a cult` (3 words) match `nautical` (1 word). Boundary shift is a *ranking signal*, not a separate feature.

### 2.2 Match types (all in, with a strictness dial)

* perfect / exact rhyme
* slant / near rhyme (feature-weighted)
* assonance (shared stressed vowels)
* multisyllabic rhyme (2+ syllables matched as a unit)

The writer slides between **more exact ↔ more adventurous**.

### 2.3 Two anchoring modes (with a dial between them)

The engine computes **both** and lets the writer slide between them:

* **Tail-anchored** — match from the last stressed syllable onward. Clean, usable end-rhymes. (`clean and stainless` → `-ainless` → `brainless`, `painless`.)
* **Full-span** — the whole selection echoes. The dense internal / multisyllabic stuff. (`clean and stainless` ↔ `acting brainless` as a full 3-beat echo.)

Same dial family as strictness: **rhyme the ending ↔ echo the whole thing**.

### 2.4 Multi-word results via a phonetic decoder

Single-word matches are a lookup against a sound index. Multi-word matches are produced by a **phonetic decoder** that "spells out" a target sound using sequences of real words. This is what invents `not a cult` from `/nɔtɪkəl/`.

* The decoder can produce non-attested but valid sequences (that is the point).
* It is kept sane by **word-frequency / naturalness scoring**, so `not a cult` outranks `nawt ick ull` — but playful oronyms (`gnaw tickle`) still surface as lower-ranked options.

---

## 3. Ranking

Each candidate carries a **decomposed** score (never a single opaque number):

* `phonetic_similarity` — feature-weighted distance
* `stress_similarity`
* `naturalness` — word frequency / phrase plausibility
* `boundary_surprise` — how much the word boundaries moved
* `theme_fit` — semantic relevance to the surrounding verse (see §4)

Phase 9 adds an explicit `rank_score`, the actual ordering key assembled from
those named components. Stress and boundary surprise now affect ranking instead
of being display-only signals. Multi-word naturalness remains part of the base
score, and theme/seed context blends with that complete base rather than
restarting from raw phonetic similarity.

Boundary surprise is the Jaccard distance between internal word-boundary
positions after phoneme alignment. The final sequence boundary is ignored:
same segmentation scores `0`, while a complete resegmentation approaches `1`.
Its current contribution, like the other Phase 9 weights, is provisional;
weight calibration is explicitly deferred.

Lyric-specific phonetic weights:

* unstressed-vowel substitution → cheap
* schwa insertion / deletion → cheap
* final-consonant deletion → cheap (under a relaxed profile)
* stressed-vowel mismatch → expensive
* syllable-count change → penalized, not forbidden

Every result ships with its **phoneme alignment** as the human-readable explanation.

---

## 4. Context features (in from the start)

Two distinct features, both powered by the same offline word-vector file:

1. **Theme-filtering of results** — rerank/filter rhyme candidates by how well they fit the theme of the current verse (a marine verse floats `nautical`, `barnacle`, `tentacle`).
2. **Semantic chains ("the `bank` example")** — expand a seed word into a related pool (`bank` → `invested` → `interest` → `currency` → `dividend`) to then rhyme against.

Both forms are available:

* `nautical chain "bank"` keeps the semantic neighborhood disconnected for
  open-ended browsing.
* `nautical rhymes TEXT --seed "bank"` expands the same neighborhood and uses
  it directly as context while ranking sound matches.

---

## 5. Technical decisions

### Runtime

* **Python**, run from the **terminal / CLI** for step one. No web UI yet — a terminal is enough for both of us to check result quality.
* **Fully offline.** No paid APIs, no model servers that phone home.

### Storage

* **SQLite**, not PostgreSQL. Single-file, offline, zero-setup. (Postgres/pgvector is a later-scale concern, not now.)
* Vector / phonetic similarity is done in-process; SQLite stores the lexicon, pronunciations, indexes, frequencies, and cached results.

### Offline data + libraries

| Need | Choice | Notes |
|------|--------|-------|
| Pronunciations (words) | CMUdict | US English, permissive license |
| g2p fallback (invented words) | permissively-licensed g2p | for `spifflicated`, etc. — avoid GPL (no eSpeak/phonemizer) |
| Phonetic feature distance | PanPhon | articulatory feature vectors + weighted edit distance |
| Semantics (theme + chains) | GloVe / word2vec static vectors | local file, offline |
| Naturalness | word-frequency list | ranks decoder output |

**Licensing lean:** prefer MIT/BSD/Apache. Avoid GPL dependencies (rules out eSpeak-ng / phonemizer for the pronunciation path).

---

## 6. Engine pipeline (step one)

```text
selection (word or phrase)
  → pronounce (CMUdict, g2p fallback)  → phoneme lattice
  → flatten boundaries                 → boundary-free phoneme string
  → search:
       single-word index               → word candidates
       phonetic decoder + freq          → multi-word candidates
  → score (phonetic / stress / naturalness / boundary_surprise)
  → context-rerank (GloVe; explicit theme and/or expanded seed)
  → present rank_score + components + phoneme alignment (explanation)
```

Both anchoring modes (tail / full-span) run in the search step; the dial adjusts which results and weights dominate.

---

## 7. What "step one done" looks like

A terminal tool where we can:

1. give it a word or phrase from `some_lyrics.txt`;
2. get back ranked single-word and multi-word sound-alikes;
3. see the decomposed scores and the phoneme alignment for each;
4. optionally pass a theme/seed to rerank by context;
5. slide strictness and tail↔full-span.

**Success test:** it rediscovers the known matches already in the lyrics — `not a cult ↔ nautical`, `clean and stainless ↔ acting brainless` — in a sensible ranked position, with explanations that hold up when spoken.

---

## 8. Rough build order

1. Pronunciation layer (CMUdict + g2p fallback) → phoneme lattice, boundary-free representation.
2. Phonetic feature distance (PanPhon) with lyric weights + strictness.
3. Single-word sound index + search (prove `not a cult → nautical`).
4. Phonetic decoder for multi-word results + naturalness ranking (prove `nautical → not a cult`).
5. Tail-anchored vs. full-span anchoring modes.
6. Semantic layer (GloVe): theme-filtering + `bank`-style chains.
7. CLI polish + explanations + SQLite caching.
