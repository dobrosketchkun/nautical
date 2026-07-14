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
