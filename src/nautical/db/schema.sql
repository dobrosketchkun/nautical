-- Nautical SQLite schema (Phase 0).
-- Phonetic/IPA columns and search indexes are added in later phases.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS lexeme (
    id           INTEGER PRIMARY KEY,
    written_form TEXT UNIQUE NOT NULL,   -- UNIQUE creates the lookup index
    frequency    REAL NOT NULL DEFAULT 0,
    zipf         REAL NOT NULL DEFAULT 0,
    pos_tag      TEXT,
    is_possessive INTEGER NOT NULL DEFAULT 0,
    is_abbrev    INTEGER NOT NULL DEFAULT 0,
    is_propn     INTEGER NOT NULL DEFAULT 0,
    is_variant   INTEGER NOT NULL DEFAULT 0,
    quality      REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_lexeme_quality ON lexeme(quality);

CREATE TABLE IF NOT EXISTS pronunciation (
    id             INTEGER PRIMARY KEY,
    lexeme_id      INTEGER NOT NULL REFERENCES lexeme(id),
    arpabet        TEXT NOT NULL,        -- space-joined ARPAbet phones w/ stress digits
    stress         TEXT,                 -- concatenated stress digits, e.g. "010"
    syllable_count INTEGER,
    ipa            TEXT,                 -- normalized IPA string, e.g. "nɔtɪkəl"
    ipa_segments   TEXT,                 -- space-joined IPA segments, e.g. "n ɔ t ɪ k ə l"
    source         TEXT
);

CREATE INDEX IF NOT EXISTS idx_pron_lexeme ON pronunciation(lexeme_id);

-- Phoneme n-gram inverted index for generous candidate retrieval (Phase 3).
CREATE TABLE IF NOT EXISTS phoneme_ngram (
    ngram            TEXT NOT NULL,
    pronunciation_id INTEGER NOT NULL REFERENCES pronunciation(id)
);

CREATE INDEX IF NOT EXISTS idx_phoneme_ngram ON phoneme_ngram(ngram);

-- Normalized-onset index for the multi-word phonetic decoder (Phase 4).
-- Anchors decode candidates by their leading (consonant-exact, vowel-broad)
-- segments so a target position can fetch words that could start there.
CREATE TABLE IF NOT EXISTS decode_onset (
    onset_key        TEXT NOT NULL,
    pronunciation_id INTEGER NOT NULL REFERENCES pronunciation(id)
);

CREATE INDEX IF NOT EXISTS idx_decode_onset ON decode_onset(onset_key);

-- Rhyme-signature n-gram index for tail-anchored retrieval (Phase 5).
-- Mirrors phoneme_ngram, but built only from each pronunciation's rhyme tail
-- (last stressed vowel to end), so end-rhymes can be retrieved directly.
CREATE TABLE IF NOT EXISTS rhyme_ngram (
    ngram            TEXT NOT NULL,
    pronunciation_id INTEGER NOT NULL REFERENCES pronunciation(id)
);

CREATE INDEX IF NOT EXISTS idx_rhyme_ngram ON rhyme_ngram(ngram);

-- Penn-tag POS n-gram LM for multi-word phrase plausibility (U1.4).
-- Trained from NLTK Treebank at db build; queried with trigram→bigram→unigram backoff.
CREATE TABLE IF NOT EXISTS pos_lm (
    order_n  INTEGER NOT NULL,   -- 1, 2, or 3
    context  TEXT NOT NULL,      -- "" | "DT" | "DT TO"
    tag      TEXT NOT NULL,
    log_prob REAL NOT NULL,
    PRIMARY KEY (order_n, context, tag)
);
