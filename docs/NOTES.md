# Engineering Notes & Deferred Work

A living log of decisions, approximations, known data quirks, and calibration
debts accumulated while building the phases in `PHASES.md`. The point is that
"notes for later" don't sink into chat history. Append here as phases progress;
when something is addressed, mark it done with the phase that resolved it.

Legend: [ ] open · [x] resolved · (Pn) = target/origin phase.

---

## Calibration & tuning debts

- [ ] **(P7) Absolute similarity is uncalibrated.** Phonetic-distance weights are
  first-pass constants. Relative ordering is correct (`not a cult`/`nautical`
  0.91 > `not a cult`/`electric` 0.77), but unrelated pairs score too high in
  absolute terms because the column-averaged normalization compresses the range.
  Tune weights + normalization against the lyrics corpus so unrelated words land
  nearer 0. See `src/nautical/phonetics/align.py` (`_sub_cost`, `_gap_cost`,
  `_strictness_scale`) and `distance.py` (`similarity`).
- [ ] **(P7) Weight set is untested against real examples.** The lyric weights
  (cheap unstressed/schwa/final-consonant edits, expensive stressed-vowel
  mismatch) need validation against the annotated corpus, not just intuition.
  Now *measurable*: `nautical eval` replays `docs/eval_pairs.json` and reports
  per-pair rank + MRR/hit-rate, so weight changes can be judged by whether ranks
  improve. Calibration itself is still open (not done in P7).

## Deferred features (planned, not yet built)

- [ ] **(P1/later) Full lyric tokenizer.** Current `tokenize` only lowercases,
  splits on whitespace, and strips edge punctuation. Deferred: Japanese-English
  switching, elongated spellings (e.g. "MASTURRR-"), performance notation,
  trickier contractions/clitics. See `src/nautical/pronounce.py`.
- [x] **(P3/P5) Retrieval recall depends on pool size.** Single-word search is
  two-stage: a phoneme bi/tri-gram overlap index (`search/index.py`) narrows the
  lexicon to `pool` (default 1500) candidates, then the aligner reranks. Phase 5
  adds the rhyme-signature (tail) index (`rhyme_ngram` + `tail_candidate_ids`);
  when `anchor > 0`, `find_rhymes` unions the full pool with a tail pool so
  end-rhymes that share little else still surface. Raising `--pool` still helps
  for edge cases. A stressed-vowel-only index remains a possible future add.
- [x] **(P5) Syllabifier not needed for tail-anchoring.** The rhyme tail
  (`phonetics/anchor.py:rhyme_tail`) is computed directly from per-segment stress
  (last stressed vowel -> end), so it does not depend on the heuristic
  `phonology/syllable.py`. The syllabifier's heuristic intervocalic rule remains
  documented for other uses but is not on the anchoring path.
- [x] **(P2/P8) Word-final vs sequence-final consonant leniency. RESOLVED (P8).**
  `Seg` now carries `word_final`, set on the last segment of every token
  (`pronounce.enriched_segments`) and every stored candidate
  (`anchor.segs_from_stored`). `align._gap_cost` treats a consonant as cheap to
  delete (0.4) when it is sequence-final *or* word-final, so internal elisions
  like the `/t/` in "not a cult" are cheap - matching how oronyms are performed.
  The `word_boundary_leniency` flag threads through
  `align`/`score_segments`/`anchored_score` (default on); `--strict-boundaries`
  on `rhymes`/`distance` restores the old behavior.
- [x] **(P2/P8) Multi-variant alignment. RESOLVED (P8).**
  `pronounce.enriched_segment_variants` returns one segment list per CMUdict
  variant for a single word, and the capped Cartesian product (<= 8 combos, else
  primary-only) for a phrase. `phonetic_distance` and `find_rhymes` score every
  variant and keep the best per candidate (`multi_variant=True` default;
  `--primary-only` opts out). E.g. `read` (R IY D / R EH D) now matches `red`
  exactly. The flag is part of the `rhymes` cache key.
- [x] **(P5) Rhyme-tail ranking / onset-cluster gap penalty. RESOLVED (P5).**
  Phase 3 ranked by whole-word alignment similarity, which under-ranked perfect
  end-rhymes that differ only in onset length: for `stainless` (`steɪnləs`),
  `painless` (`peɪnləs`) sank to ~197 because the shorter onset forced a
  leading-consonant deletion (gap ~0.9) even though the `-eɪnləs` tail is
  identical. Phase 5 adds tail-anchored scoring (`phonetics/anchor.py`): every
  candidate gets a `tail_similarity` (rhyme tail vs rhyme tail, onset-agnostic)
  blended with `full_similarity` by the `anchor` dial. With `--anchor tail`
  (or the default `anchor=0.5`), `painless`/`brainless` rank in the top few.
  The underlying edge-gap penalty in `align.py` is left as-is (harmless once the
  tail path exists).
- [ ] **(P4/P6) Multi-word decoder surfaces sound, not meaning.** The decoder
  (`search/decoder.py`) tiles the target with real words via an onset index
  (`decode_onset`) + beam DP, reranked by `similarity + naturalness`. It works and
  produces genuine sound-alikes (`nautical` -> `no to call`, `naughty can`,
  `naught a can`, `gnaw to can`; `stainless` -> `state less`, `stayed less`,
  `stain less`, `spain less`). Two honest limitations, both by design for later
  phases:
  1. **Meaningful phrases are not distinguishable from bland ones without
     semantics.** For `nautical`, the genuine close oronym `gnaw tickle`
     (`nɔtɪkəl`, similarity 0.981) is discoverable and is ~rank 198 by *pure
     similarity* out of ~185k tilings, but is buried by score because `gnaw`/
     `tickle` are low-frequency; meanwhile bland common-word tilings (`no to
     can`) dominate the frequency-naturalness ranking. Distinguishing "a real
     phrase" from "three common words in a row" needs phrase-plausibility /
     semantics -> **Phase 6** (theme reranking, now implemented via `--theme`)
     is what makes this output useful when a verse/theme is supplied.
  2. **`not a cult` is a *loose* oronym, not a close one.** It adds a whole extra
     `/t/` (`nɑtəkʌlt`, 8 segments vs `nautical`'s 7), so its similarity is only
     ~0.90 and it sits far down the cost-ranked pool (beyond the default
     `final_cap`), even though `not a can`/`not a cull` (no extra `/t/`) surface
     easily. It is reachable only with a large `cand_per_pos` (>=~600, so `cult`
     survives the pos-4 candidate cut) and a large pool. This is inherent to raw
     phonetic tiling; the artistic `not a cult <-> nautical` pairing relies on
     rhythm/semantics that arrive in Phases 5-6. The PHASES.md success check
     ("`not a cult` near the top") is therefore not met by Phase 4 alone.
- [x] **(P4/P8) Candidate flooding by rare-word spellings. RESOLVED (P8) via a
  user-managed exclusion list.** Top-by-similarity was crowded with
  near-identical spellings of the same sound (`naught a call`, `gnaw to call`,
  `naught a cull`, `gnaw to cull`, ...). Decision: *filter, don't collapse* -
  `cull`/`gnaw` are real, distinct words, so an automatic IPA-level dedupe was
  rejected (it would silently drop legitimate alternatives). Instead
  `data/exclude.txt` (one lowercase word per line, `#` comments; loaded by
  `src/nautical/exclude.py`) plus `--exclude "cull,naught"` let the writer hide
  specific words. Applied inside `find_rhymes` (skips candidates) and
  `find_multiword` (adds to `skip_words`) before the limit, and the exclusion set
  is hashed into both cache keys so results stay correct.
- [x] **(P7) Decoder latency - mitigated by caching.** Each query still aligns
  every onset-matching word at every target position (thousands of tiny
  alignments), so a *cold* query is ~seconds (single-word `stainless` ~10s,
  multi-word decodes similar) at defaults. Phase 7 adds a SQLite result cache
  (`src/nautical/cache.py`): repeat queries are ~1 ms. Measured: `nautical eval`
  went 74.6s -> 61 ms cold->warm. The underlying per-query cost is unchanged (a
  candidate-prefilter is still a future win); caching just removes the repeat
  penalty, which is what the CLI/harness workflow hits most.
- [ ] **(P4/P9) Ranking weights uncalibrated.** Phase 9 centralizes the
  provisional stress (`0.10`), boundary (`0.10`), naturalness (`0.35`), and
  per-word penalty (`0.05`) in `search/ranking.py`. The signals now compose
  consistently, but the constants still need calibration against a larger
  judged corpus.

## Decisions

- **(P9) Shared score contract and explicit ordering key.** Single-word and
  multi-word results now carry `ScoreComponents`: phonetic/full/tail,
  stress, optional naturalness, boundary surprise, optional theme fit,
  `base_score`, and `rank_score`. CLI tables and JSON expose `rank_score` as the
  actual ordering key. `theme.apply_theme` blends context with the complete
  base score instead of raw similarity, so multi-word naturalness and the other
  Phase 9 signals are retained.
- **(P9) Boundary surprise is alignment-aware.** Internal boundaries are taken
  from `Seg.word_final` in global aligned-column space; the unavoidable final
  sequence boundary is ignored. Surprise is Jaccard distance between source and
  candidate boundary sets (`0` same segmentation, `1` wholly different).
  Multi-word results now retain a global alignment in addition to per-word
  decoder chunks.
- **(P9) Semantic chains remain standalone and gain a connected mode.**
  `nautical chain SEED` still lists neighbors. `nautical rhymes TEXT --seed
  SEED` expands a bounded lexicon neighborhood (`--seed-limit`) and combines it
  with any explicit `--theme` terms for context reranking. Broad phonetic bridge
  search across every chain member remains deferred.
- **(P9) Cache payload version.** `cache.make_key` includes a Phase 9 format
  version so pre-Phase-9 payloads without score components/global alignments
  are ignored automatically; semantic context remains post-cache.

- **(P7) Result caching: separate `cache.db`, phonetic-only key, theme after.**
  `src/nautical/cache.py` writes to its own `data/cache.db` (not `nautical.db`),
  so it survives `db build` and needs no `SCHEMA_VERSION` bump. The key
  (`make_key`) is a sha1 of the *phonetic* params only (`find_rhymes`: text,
  limit, pool, strictness, anchor, include_self; `find_multiword`: + beam,
  cand_per_pos, max/min words). `--theme` is applied *after* the cache (cheap
  vector math), so one cached search serves every theme. Caching lives at the
  service layer (`find_rhymes` / `find_multiword` gain `use_cache=True`) so the
  CLI, tests, and the eval harness all benefit; each dataclass serializes itself
  (including alignment pairs, so `--align` still renders from a cache hit).
  Invalidation is by key only: after changing phonetic weights or rebuilding the
  lexicon, run `nautical cache clear` (`cache stats` shows age via `created_at`).
  Passing an explicit `conn=` (as tests do) bypasses the cache.
- **(P7) `typer`/`click` help crash fixed two ways.** `pyproject.toml` now pins
  `typer>=0.16` (0.16 is compatible with click 8.2's required
  `make_metavar(ctx)` / `get_metavar(param, ctx)`), and `cli.py` also installs a
  small runtime compatibility shim (`_install_click_typer_compat`) that makes
  `ctx` optional. The shim is a safe no-op once typer/click agree and keeps
  `--help` working even in environments that can't be upgraded (it is what kept
  the CLI usable while the env still had typer 0.15.2).
- **(P7) Eval corpus is curated ground truth, not scraped.** `docs/eval_pairs.json`
  is hand-verified from `docs/some_lyrics.txt` (web lyric pages were too
  unreliable to auto-seed). It is user-extensible: add hand-verified pairs and
  re-run `nautical eval`. EN-JP echoes and transformation puns (`pun-stoppable`,
  `Ina-terested`, `Ina-sanity`) are deliberately excluded (out of scope for Step
  One). The harness (`src/nautical/eval.py`) makes the calibration debts below
  *measurable*. **P8 baseline** (word-boundary leniency + multi-variant now on by
  default; run after `cache clear` + full-vocab `vectors build --force`):
  hit-rate@50 7/9 (78%), MRR 0.402, median rank (hits) 2; `not a cult -> nautical`
  is rank 6 phonetically and rank 1 with `--theme "ocean, sea, ship"`; the two
  reverse multi-word decodes (`nautical -> not a cult`,
  `clean and stainless -> acting brainless`) are misses, the known Phase 4/6
  semantic gap, reported honestly rather than hidden. (P7 baseline was MRR 0.383.)
  **P9 structural-ranking baseline** (no weight calibration): hit-rate@50 remains
  7/9 (78%), MRR 0.394, median rank 2. `not a cult -> nautical` remains rank 6
  and theme-reranks to rank 1; the same two multi-word cases remain misses.
  `invested -> requested` moves from rank 4 to 22 because stress is now a real
  signal among otherwise exact tail matches. This is recorded rather than tuned
  here because calibration is explicitly outside Phase 9.

- **(P6/P8) GloVe 6B 300d, auto-downloaded on first use, full vocabulary.** The
  semantic layer uses GloVe 6B (300d). `semantics/vectors.py:ensure_vectors()`
  lazily downloads `glove.6B.zip` (~822 MB, one-time) if no cache/raw file is
  present, L2-normalizes, and caches a `float32` `.npy` plus a `vocab.txt` under
  the gitignored `data/vectors/`. Offline after that. **P8 change:** vectors are
  no longer filtered to the lexicon - the full ~400K vocabulary is kept (npy
  ~458 MB, vocab ~4.5 MB) so any theme/seed word resolves; `chain` masks its
  suggestions back to the lexicon via `most_similar(allowed=...)`. A pre-staged
  raw file or cache skips the download. Primary mirror is Stanford, fallback is
  HuggingFace (`config.GLOVE_ZIP_URLS`).
- **(P6) Theme fit is a separate signal.** `--theme` reranks by a bounded blend
  `(1-w)*similarity + w*(theme_fit+1)/2` (default `--theme-weight 0.5`) but shows
  `theme_fit` (cosine, `[-1,1]`) as its own column/JSON field - the phonetic and
  semantic scores are never merged into one opaque number. When `--theme` is set,
  a wider phonetic window is fetched before reranking so off-top but on-theme
  matches can surface.

- **(P5) Anchor dial defaults.** Single-word `find_rhymes` defaults to
  `anchor=0.5` (blend full-span + rhyme tail): it lifts end-rhymes like
  `painless`/`brainless` to the top while retaining the whole-word signal, and
  existing Phase 3 tests still hold (the blend only raises tail rhymes). The
  multi-word decoder defaults to `anchor=0.0` (full-span) since oronyms are
  inherently whole-span echoes; `--anchor tail` biases toward matching endings.
  `--anchor` accepts `tail` (1.0), `full` (0.0), or a float `0..1`.

## Phase 6 limitations / deferrals

- [ ] **(P7/P9) Theme-blend weight is uncalibrated.** `--theme-weight` default
  0.5 remains first-pass. Phase 9 fixes its input (complete `base_score`, not raw
  similarity), but tuning is deferred.
- [x] **(P6/P8) Theme/seed words limited to the lexicon-filtered vocab.
  RESOLVED (P8).** `build_vectors` no longer filters to the lexicon - it keeps all
  ~400K GloVe vectors (npy ~112 MB -> ~458 MB, vocab ~4.5 MB), so any theme/seed
  word the writer types resolves. `chain` still suggests only real lexicon words:
  `most_similar` gained an `allowed` mask and `cli.chain` passes the lexicon set.
  `--theme`/`theme_fit` need no mask (plain vector lookups). One-time
  `nautical vectors build --force` regenerates the cache from the local raw file.
- [ ] **(P6/later) Multi-word theme fit is a bag-of-words mean.** A phrase's
  `theme_fit` is the mean of its member-word vectors (OOV skipped); it ignores
  order and composition. Fine for reranking; revisit if phrase semantics matter.

## Approximations made (intentional, documented)

- **(P1) Stress-aware vowel reduction.** `AH0 -> ə`, `ER0 -> ɚ`; other stress
  levels keep `ʌ` / `ɝ`. `src/nautical/phonology/arpabet.py`.
- **(P2) r-colored vowels.** `ɝ`/`ɚ` are absent from PanPhon; approximated as the
  mean of `ə` and `ɹ` feature vectors. `src/nautical/phonetics/features.py`.
- **(P2) Diphthongs as one slot.** `eɪ oʊ aɪ ɔɪ aʊ` are averaged from their two
  PanPhon component vectors into a single alignment slot (one slot per ARPAbet
  phone). Affricates `tʃ`/`dʒ` queried via tie-bar `t͡ʃ`/`d͡ʒ`.

## Known data quirks

- **(P1) `nautical` = `N AO1 T AH0 K AH0 L` -> `nɔtəkəl`** in this CMUdict, not
  the `nɔtɪkəl`/`IH0` form used illustratively in `PROJECT.MD`. Both reduced
  vowels are schwa. (Helps the core example: shares an exact `ə` with
  `not a cult` = `nɑtəkʌlt`.)

## Resolved conventions & gotchas

- [x] **(P0) `conda run` + Unicode hang.** Default `conda run` re-encodes child
  stdout as cp1252 on Windows and crashes/hangs on IPA + Rich box characters.
  Resolved: CLI forces UTF-8 on stdout/stderr, and we always run output commands
  with `conda run --no-capture-output -n general_env_1 ...` (documented in
  `.cursor/rules/python-env.mdc`).
- [x] **(P1) g2p_en first-run download.** `g2p_en` needs a one-time nltk tagger
  download; it was already present in `general_env_1`, so the OOV path works
  offline. Revisit only if setting up a fresh environment.
- [x] **(P8) PanPhon cp1252 crash on Windows.** `panphon.FeatureTable()` reads
  its bundled `ipa_all.csv` / `feature_weights.csv` via
  `importlib.resources.files(...).open()` with **no encoding**, so it uses the
  platform default. In an activated env on a cp1252 console (i.e. not UTF-8
  mode), the first feature lookup crashed with `UnicodeDecodeError: 'charmap'
  codec can't decode byte 0x90` (the CSV holds IPA). This was masked during
  development because a persisted `PYTHONUTF8=1` / `conda run` made the default
  UTF-8. Resolved in `phonetics/features.py:_patch_panphon_utf8()`, which wraps
  the `files` used by `panphon.featuretable` so its `.open()` defaults to UTF-8 -
  no env vars, no re-exec, no panphon edit; applied once before the table is
  built and active in both the CLI and tests.
