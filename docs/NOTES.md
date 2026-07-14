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

## Deferred features (planned, not yet built)

- [ ] **(P1/later) Full lyric tokenizer.** Current `tokenize` only lowercases,
  splits on whitespace, and strips edge punctuation. Deferred: Japanese-English
  switching, elongated spellings (e.g. "MASTURRR-"), performance notation,
  trickier contractions/clitics. See `src/nautical/pronounce.py`.
- [ ] **(P3/P5) Retrieval recall depends on pool size.** Single-word search is
  two-stage: a phoneme bi/tri-gram overlap index (`search/index.py`) narrows the
  lexicon to `pool` (default 1500) candidates, then the Phase 2 aligner reranks.
  If a known good answer is missing, raise `--pool` or add a unigram/rhyme-tail
  fallback index. Deferred specialized indexes (rhyme-signature, stressed-vowel)
  are Phase 5.
- [ ] **(P5) Syllabifier is heuristic.** `phonology/syllable.py` uses a simplified
  intervocalic-consonant rule (single consonant -> next onset; clusters -> last
  consonant to next onset, rest to preceding coda). Refine for tail-anchoring
  (from last stressed syllable) in Phase 5.
- [ ] **(P2/later) Word-final vs sequence-final consonant leniency.** Cheap
  final-consonant deletion currently applies only at the end of the whole
  boundary-free sequence, not at each word boundary within a phrase.
- [ ] **(P2/later) Multi-variant alignment.** Distance aligns only each token's
  primary (first CMUdict) variant; the full pronunciation lattice is ignored when
  scoring.
- [ ] **(P5) Rhyme-tail ranking / onset-cluster gap penalty.** Phase 3 ranks by
  whole-word alignment similarity, which under-ranks perfect end-rhymes that
  differ only in onset length. Example: for `stainless` (`steɪnləs`), `brainless`
  ranks ~19 (two onset subs, no gap) but `painless` (`peɪnləs`) ranks ~197
  because the shorter onset forces a leading-consonant deletion (gap ~0.9) even
  though the `-eɪnləs` rhyme tail is identical. Fix in Phase 5 with a
  rhyme-signature (stressed-vowel-to-end) index / blended score, and/or cheaper
  edge (onset) gaps. See `src/nautical/phonetics/align.py` (`_gap_cost`).
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
     semantics -> **Phase 6** (theme reranking) is what makes this output useful.
  2. **`not a cult` is a *loose* oronym, not a close one.** It adds a whole extra
     `/t/` (`nɑtəkʌlt`, 8 segments vs `nautical`'s 7), so its similarity is only
     ~0.90 and it sits far down the cost-ranked pool (beyond the default
     `final_cap`), even though `not a can`/`not a cull` (no extra `/t/`) surface
     easily. It is reachable only with a large `cand_per_pos` (>=~600, so `cult`
     survives the pos-4 candidate cut) and a large pool. This is inherent to raw
     phonetic tiling; the artistic `not a cult <-> nautical` pairing relies on
     rhythm/semantics that arrive in Phases 5-6. The PHASES.md success check
     ("`not a cult` near the top") is therefore not met by Phase 4 alone.
- [ ] **(P4) Candidate flooding by rare-word spellings.** Top-by-similarity is
  crowded with near-identical spellings of the same sound (`naught a call`,
  `gnaw to call`, `naught a cull`, `gnaw to cull`, ...). Naturalness partly
  suppresses these; an IPA-level dedupe (keep the most natural spelling per
  sound) would declutter and is a cheap future improvement.
- [ ] **(P7) Decoder latency.** Each query aligns every onset-matching word at
  every target position (thousands of tiny alignments), so a query is ~4s
  (`nautical`) to ~7s (`stainless`) at defaults (`beam=300`, `cand_per_pos=350`).
  Fine for a CLI but a caching / candidate-prefilter target for Phase 7.
- [ ] **(P4) Decoder ranking blend uncalibrated.** `_W_NATURALNESS=0.35`,
  `_W_WORDS=0.05` in `search/decoder.py` are first-pass constants; calibrate in
  Phase 7 against `some_lyrics.txt`.

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
