-- Nautical SQLite schema (Phase 0).
-- Phonetic/IPA columns and search indexes are added in later phases.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS lexeme (
    id           INTEGER PRIMARY KEY,
    written_form TEXT UNIQUE NOT NULL,   -- UNIQUE creates the lookup index
    frequency    REAL NOT NULL DEFAULT 0
);

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
