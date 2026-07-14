# Project Description: Phonetic Creativity Workbench

## 1. Product concept

The Phonetic Creativity Workbench is a browser-based writing environment for discovering, constructing, evaluating, and explaining unusual relationships between words and phrases.

Its purpose is to help writers find language that works simultaneously across several dimensions:

* phonetic similarity;
* rhyme and rhythmic compatibility;
* semantic connection;
* morphological transformation;
* alternative word segmentation;
* multilingual sound correspondence;
* names, character lore, and recurring motifs;
* comedic or rhetorical surprise.

The defining example is not merely a conventional rhyme:

> “We’re gonna be pun-stoppable, we’re not a cult / Nonsensical and nautical.”

A normal rhyme tool might notice *cult* and the ending of *nautical*. The proposed system should instead recognize the richer structure:

```text
unstoppable → pun-stoppable

not a cult → nautical
/nɑt ə kʌlt/ ≈ /ˈnɔːtɪkəl/
```

It should then explain that:

1. “Pun-stoppable” substitutes a meaningful unit inside a familiar word.
2. “Not a cult” resembles “nautical” after word boundaries and unstressed vowels are relaxed.
3. “Nautical” belongs to the song’s marine and octopus theme.
4. The imperfect phonetic match is compensated for by high thematic relevance and strong rhythmic fit.

The product is therefore not just a generator. It is an **interactive search, analysis, and composition system**.

---

# 2. Core design principle

The system should be:

> **Retrieval-first, transformation-second, generation-third.**

An unrestricted language model can produce puns, but its suggestions are difficult to reproduce, rank, inspect, or control. It may also invent pronunciations or claim relationships that do not work when spoken.

This application should instead have three layers:

### Layer 1: Deterministic linguistic analysis

This layer calculates:

* possible pronunciations;
* phoneme sequences;
* syllables;
* stress patterns;
* word boundaries;
* rhyme families;
* part of speech;
* named entities;
* semantic fields;
* meter and line length.

### Layer 2: Candidate search and transformation

This layer finds real words and phrases through explicit operations:

* sound-neighbor search;
* word-to-phrase and phrase-to-word matching;
* portmanteau construction;
* name insertion;
* prefix and suffix replacement;
* multilingual phonetic overlap;
* semantic-chain continuation;
* rhythmic substitution.

### Layer 3: Contextual reasoning

A language model may then:

* interpret the surrounding verse;
* rerank candidates for relevance;
* explain why a candidate might work;
* suggest grammatical ways to incorporate it;
* create lines under explicit constraints.

The language model should not be the sole authority on pronunciation or phonetic similarity.

---

# 3. Main user experience

## 3.1 The central lyric editor

The main interface should resemble a serious text editor rather than a chatbot.

The screen would contain:

```text
┌────────────────────────────┬──────────────────────────────┐
│                            │ Candidate Explorer           │
│ Lyric / text editor        │                              │
│                            │ Sound matches                │
│ Coloured rhyme markings    │ Boundary shifts             │
│ Semantic highlights        │ Name insertions              │
│ Stress and beat overlays   │ Semantic chains              │
│                            │ Multilingual matches         │
├────────────────────────────┴──────────────────────────────┤
│ Context, controls, timeline, pronunciation and playback   │
└───────────────────────────────────────────────────────────┘
```

The writer can select a word, phrase, line, or phonetic region and invoke a specific search operation.

A real browser editor should be implemented in TypeScript, preferably with React and Tiptap. Tiptap is a headless rich-text framework built on ProseMirror and supports custom nodes, marks, events, commands, decorations, and extensions. Those capabilities are important because rhyme links, IPA overlays, candidate insertions, and semantic annotations are not ordinary textarea features.

Python should power the linguistic backend, not the editor itself.

Streamlit, Gradio, or a Python-rendered interface may be useful for internal research consoles, but they should not be the primary production editor. The editor will eventually need precise cursor positions, incremental document updates, overlapping annotations, undoable transformations, audio synchronization, and potentially collaboration.

## 3.2 Editor annotations

Analysis should appear as optional visual layers:

* **Rhyme layer:** connects exact, slant, internal, and multisyllabic rhymes.
* **Phonetic echo layer:** shows similar consonant and vowel patterns.
* **Semantic layer:** highlights thematic groups such as finance, death, sailing, religion, or food.
* **Transformation layer:** identifies portmanteaus, substitutions, and alternative segmentations.
* **Meter layer:** displays syllable count, stress contour, and alignment to beats.
* **Multilingual layer:** displays cross-language phonetic matches.
* **Entity layer:** identifies names, character-specific terms, places, and invented vocabulary.

Annotations must never alter the text automatically. They are a lens that can be enabled, disabled, or filtered.

## 3.3 Candidate cards

Every suggestion should appear as an inspectable card:

```text
NAUTICAL
Sound match:       0.81
Boundary surprise: 0.94
Theme relevance:   0.91
Meter fit:         0.87
Grammar fit:       0.72
Novelty:           0.84

Matches:
“not a cult” → “nautical”

Why it may work:
The word boundaries disappear in rapid pronunciation.
“Nautical” also supports the marine theme.

Possible use:
“We’re not a cult — just nautical.”
```

The score should remain decomposable. A single unexplained “92% match” would hide why a candidate was selected.

---

# 4. Editor operations

Selecting text should expose the following principal operations.

## 4.1 Sound like this

Find words and phrases with a similar performed sound.

Filters should include:

* exact rhyme;
* slant rhyme;
* same stressed vowel;
* same consonant frame;
* assonance;
* consonance;
* multisyllabic correspondence;
* beginning, middle, or ending similarity;
* maximum syllable difference;
* approximate stress contour.

This mode searches phonemes, not spelling.

## 4.2 Break the boundaries

Search for different ways to divide the same or a similar sound sequence:

```text
not a cult ↔ nautical
an ocean   ↔ a notion
some others ↔ smothers
```

This is essential. Fixed word boundaries prevent ordinary rhyme tools from finding many of the strongest constructions.

The user should be able to search in both directions:

* phrase → word;
* word → phrase;
* phrase → differently segmented phrase.

## 4.3 Inject a name or motif

Given a name such as “Ina,” identify words that could absorb it:

```text
insanity   → Ina-sanity
interested → Ina-terested
```

The lyrics use a finance-related progression:

> “Can I bank on your emotion? Do I have you invested? … you’re not Ina-terested.”

The system should recognize that “bank,” “invested,” and “interest” belong to the same semantic chain. It should then see that the name “Ina” can replace or overlap part of “interested.”

The operation should support:

* prefix replacement;
* suffix replacement;
* internal insertion;
* phonetic overlap;
* syllable replacement;
* spelling-preserving and pronunciation-preserving variants.

## 4.4 Continue a semantic chain

The writer selects several related terms, and the system expands the conceptual field.

For example:

```text
bank
investment
interest
currency
capital
credit
return
dividend
deposit
stake
```

The phonetic engine then searches those terms and their related expressions for candidates fitting the current line, rhyme, name, or meter.

This is where semantic search and phonetic search intersect.

## 4.5 Cross-language echoes

The system should search sound correspondences across languages and scripts.

The supplied lyrics include English words embedded into Japanese expressions:

> “you reap what you fuckin’ SEISO” and “Sugoi ‘die’suki.”

It later uses:

> “Donmai, ‘die’joubu.”

This requires more than translation. The engine needs:

* language detection at token or phrase level;
* romanization and native-script preservation;
* multiple pronunciation candidates;
* cross-language phoneme normalization;
* optional accent profiles;
* control over vowel length and stress flexibility.

The user should be able to specify the intended speaker, accent, or permissible degree of pronunciation bending.

## 4.6 Fit this meter

The writer provides:

* a reference line;
* a beat grid;
* an audio recording;
* or a manually entered stress pattern.

The engine finds substitutions that preserve:

* approximate syllable count;
* stressed-syllable positions;
* phrase duration;
* rhyme landing point;
* syntactic role.

A candidate that sounds similar but cannot fit the line rhythmically should be ranked lower.

## 4.7 Transform while preserving constraints

The user can lock elements:

```text
Keep:
- meaning: refusal
- rhyme target: nautical
- syllables: 8–10
- end stress: final two syllables
- character motif: ocean
- tone: playful and sinister
```

The system then searches and generates only inside those constraints.

---

# 5. Linguistic processing pipeline

## 5.1 Document parsing

Each edit produces a structured representation:

```text
Document
  Section
    Stanza
      Line
        Phrase
          Token
            Character span
            Lemma
            Part of speech
            Language
            Named entity
            Pronunciations[]
            Syllables[]
            Stress pattern
```

spaCy can provide tokenization, part-of-speech information, dependency analysis, and named-entity spans, but lyric text will require custom handling for contractions, invented words, punctuation, Japanese–English switching, elongated spellings, and performance notation. spaCy’s documentation specifically notes that tokenization choices affect model results and that training and runtime tokenization should remain aligned.

A dedicated lyric tokenizer should therefore sit before or alongside general NLP models.

## 5.2 Pronunciation lattice

A word should not map to one pronunciation. It should map to a **lattice of possible pronunciations**.

For example, the system may store:

```text
“interesting”
formal:       /ˈɪntərəstɪŋ/
reduced:      /ˈɪntrəstɪŋ/
casual:       /ˈɪntrɪstɪŋ/
performed:    user-defined
```

The lattice can include:

* dictionary pronunciation;
* grapheme-to-phoneme output;
* dialect alternatives;
* reduced speech variants;
* user corrections;
* pronunciation inferred from uploaded audio;
* intentionally stylized pronunciation.

Phonemizer provides Python-accessible text-to-phone conversion for many languages and supports backends including eSpeak-ng. Epitran converts orthographic forms into IPA for supported language-script combinations.

These should be adapters behind an internal pronunciation interface rather than dependencies embedded throughout the application.

There is also a licensing consideration: Phonemizer is GPL-licensed, while Epitran’s repository uses the MIT license. The final packaging and deployment model should receive an explicit dependency-license review.

## 5.3 Phonological feature representation

Raw IPA string edit distance is insufficient.

The system should represent phonemes through articulatory features such as:

* voicing;
* place of articulation;
* manner of articulation;
* vowel height;
* vowel backness;
* rounding;
* syllabicity;
* sonority.

Then `/t/ → /d/` can be treated as a smaller change than `/t/ → /m/`.

PanPhon maps IPA segments to articulatory feature vectors and includes feature-based and weighted feature-edit-distance operations. It is therefore a suitable starting point for the phonetic distance layer.

The production engine should extend this with lyric-specific weights:

* unstressed vowel substitution should be relatively cheap;
* schwa insertion or deletion should be cheap;
* final consonant deletion may be cheap under some accent profiles;
* stressed-vowel mismatch should be expensive;
* syllable-count changes should be penalized but not forbidden;
* consonants at rhyme anchors should receive additional weight.

## 5.4 Boundary-independent representation

For phrase matching, store both:

```text
word-aware:
[nɑt] [ə] [kʌlt]

boundary-free:
nɑtəkʌlt
```

The boundary-free sequence is searched against phoneme windows from words and phrases.

Boundary positions remain metadata rather than permanent separators. This allows the system to detect when a match becomes interesting specifically because the boundaries moved.

---

# 6. Candidate-generation engines

The system should consist of several cooperating generators rather than one algorithm.

## 6.1 Phonetic nearest-neighbor engine

Input:

```text
target phoneme sequence
stress pattern
maximum syllables
accent profile
required match region
```

Output:

* words;
* inflected words;
* common phrases;
* idioms;
* named entities;
* user-corpus expressions;
* multilingual forms.

The first retrieval stage should be deliberately generous. A later reranker removes irrelevant results.

## 6.2 Resegmentation engine

This engine:

1. generates pronunciation variants for the selected phrase;
2. removes word boundaries;
3. extracts phoneme n-grams and syllable windows;
4. searches indexed words and phrases;
5. restores candidate boundaries;
6. scores how substantially the segmentation changed;
7. checks whether the result is grammatically and semantically usable.

For:

```text
not a cult
```

the engine may compare:

```text
/n ɑ t ə k ʌ l t/
```

against indexed variants of:

```text
nautical
/n ɔː t ɪ k ə l/
```

A weighted alignment would show substitutions, reductions, and deletions. The explanation layer converts that alignment into human-readable language.

## 6.3 Morphological transformation engine

This engine uses known morphemes and candidate split points:

```text
un + stoppable
interest + ed
in + sanity
```

It proposes:

* prefix replacement;
* suffix replacement;
* blending;
* clipping;
* name insertion;
* partial phonetic overlap;
* folk-etymology reinterpretation.

It must prefer transformations where the source word remains recognizable.

## 6.4 Semantic bridge engine

A semantic vector search retrieves concepts relevant to:

* selected text;
* the current verse;
* project-level themes;
* character profiles;
* user-entered topic constraints.

PostgreSQL with pgvector can store exact or approximate vector-neighbor indexes alongside the project’s relational data. pgvector supports several similarity measures and both exact and approximate nearest-neighbor search.

Semantic candidates should then be passed into the phonetic engines. Searching the entire language phonetically is too broad; semantic narrowing makes results more useful.

## 6.5 Orthographic resemblance engine

Spelling similarity remains useful, but only as one signal.

PostgreSQL’s `pg_trgm` extension supports character-trigram similarity and partial-word similarity. It can help find visually recognizable transformations such as “unstoppable” → “pun-stoppable,” although phonetic scoring must remain separate.

## 6.6 Phrase-template engine

Store productive structures such as:

```text
X on your Y
reap what you X
not a X / nautical-style boundary shift
X-invested / X-interested chain
```

The system should learn reusable mechanisms without copying the original wording.

A template describes an operation:

```text
semantic chain
→ locate polysemous member
→ replace phonetic portion with character name
→ preserve grammatical category
```

## 6.7 Controlled generative engine

After retrieval, an LLM can compose lines from approved candidates.

It receives structured constraints, for example:

```json
{
  "candidate": "nautical",
  "source_echo": "not a cult",
  "theme": ["ocean", "cult denial"],
  "syllable_range": [8, 11],
  "rhyme_anchor": "nautical",
  "tone": ["playful", "ominous"],
  "must_preserve": ["denial"]
}
```

Generated lines are then rescored by the deterministic phonetic and metrical engines.

Generation is therefore part of a loop:

```text
retrieve → generate → analyze → reject or rerank → present
```

---

# 7. Candidate ranking

A candidate should have a score vector:

```text
phonetic_similarity
stress_similarity
rhyme_strength
meter_fit
semantic_relevance
boundary_surprise
morphological_recognizability
grammatical_fit
contextual_relevance
multilingual_validity
novelty
performability
```

The overall score might initially be:

```text
score =
  0.24 phonetic_similarity
+ 0.12 stress_similarity
+ 0.10 meter_fit
+ 0.15 semantic_relevance
+ 0.10 contextual_relevance
+ 0.09 boundary_surprise
+ 0.07 grammatical_fit
+ 0.07 recognizability
+ 0.06 novelty
```

Those weights should differ by search mode.

For a rhyme search, phonetics receives more weight. For a name-insertion search, recognizability and semantic relevance become more important. For “break the boundaries,” boundary surprise becomes central.

Users should eventually be able to adjust a few understandable controls:

```text
More exact ←────────→ More adventurous
More natural ←──────→ More surprising
Meaning-first ←─────→ Sound-first
Dictionary speech ←─→ Performance speech
```

---

# 8. Worked algorithmic examples

## 8.1 “Not a cult” → “nautical”

### Step 1: Parse

```text
not | a | cult
```

### Step 2: Generate pronunciations

```text
/nɑt ə kʌlt/
/nɒɾə kʌlt/
/nɑɾə kəlt/
```

### Step 3: Flatten boundaries

```text
nɑtəkʌlt
```

### Step 4: Search phonetic index

Possible candidate:

```text
nautical → nɔtɪkəl
```

### Step 5: Feature alignment

```text
n ɑ t ə k ʌ l t
n ɔ t ɪ k ə l -
```

### Step 6: Contextual scoring

The current document contains marine concepts, octopus references, or “ancient one” mythology.

```text
phonetic:  moderate-high
semantic:  very high
boundary:  very high
meter:     high
```

### Step 7: Explanation

The application reports that the candidate becomes stronger through fast pronunciation and because its meaning supports the surrounding theme.

## 8.2 “Interested” → “Ina-terested”

### Step 1: Detect project entity

```text
Ina
```

### Step 2: Convert entity to pronunciation variants

```text
/iːnə/
/ɪnə/
```

### Step 3: Search words containing compatible opening sequences

```text
interested
insanity
inert
innovative
inevitable
```

### Step 4: Evaluate replacement points

```text
interested
in-terested
Ina-terested
```

### Step 5: Check surrounding semantic field

Previous line contains “bank” and “invested.”

### Step 6: Rank highly

The result is a recognizable word, contains the name, continues a financial semantic field, and remains grammatically usable.

---

# 9. Audio and performance analysis

A fully capable version should allow an audio file or vocal recording to be attached to the text.

The audio subsystem should support:

* word-level alignment;
* phoneme-level alignment;
* actual syllable duration;
* performed stress;
* stretched vowels;
* dropped phonemes;
* rhyme landing positions;
* tempo and beat-grid alignment.

Montreal Forced Aligner provides command-line workflows, pretrained-model support, and an API that can be integrated into scripts and projects. It is a plausible component for offline or queued alignment work.

Audio analysis should not block normal typing. It should run as a separate job and add a “performed pronunciation” track to the document.

The user can then compare:

```text
dictionary pronunciation
performed pronunciation
intended pronunciation
```

This is especially important for rap, where a rhyme may depend on deliberate vowel modification.

---

# 10. Technical architecture

## Frontend

```text
TypeScript
React
Tiptap / ProseMirror
Web Audio API
Canvas or SVG for rhyme arcs and timelines
WebSocket or server-sent updates
```

Responsibilities:

* document editing;
* cursor and selection management;
* annotation rendering;
* candidate panels;
* audio playback;
* score visualization;
* accepting or rejecting transformations;
* project settings.

## Python API

FastAPI is suitable for the backend API because it is based on Python type hints, supports async endpoints, OpenAPI schemas, WebSockets, and structured validation.

Responsibilities:

* project and document operations;
* incremental analysis requests;
* candidate search;
* explanation requests;
* authentication and permissions;
* model orchestration;
* job status.

## Linguistic services

```text
Document analysis service
Pronunciation service
Phonetic-distance service
Resegmentation service
Morphology service
Semantic retrieval service
Meter service
Multilingual service
Explanation and generation service
Audio alignment service
```

These can begin as modules in one Python application but should have explicit interfaces. Computationally expensive components can later move into independent worker processes.

## Storage

```text
PostgreSQL
├── projects
├── documents and revisions
├── tokens and spans
├── lexemes
├── pronunciations
├── semantic senses
├── candidates
├── user feedback
└── vector columns through pgvector

Object storage
├── audio
├── exports
└── model artifacts

Cache / queue
├── recent analyses
├── candidate result caches
└── background job coordination
```

## Search indexes

Maintain separate indexes for:

* spelling trigrams;
* phoneme n-grams;
* syllable endings;
* stressed-rhyme signatures;
* articulatory-feature vectors;
* semantic embeddings;
* morpheme boundaries;
* named-entity insertion points;
* phrase-frequency data.

One universal vector index will not be enough. Different searches require different representations.

---

# 11. Suggested internal data model

## Lexeme

```text
id
written_form
lemma
language
part_of_speech
frequency
senses[]
pronunciations[]
morphemes[]
```

## Pronunciation

```text
phonemes
syllables
stress
dialect
source
confidence
word_boundaries
reduction_level
```

## Phrase entry

```text
text
token sequence
phoneme sequence
boundary-free sequence
semantic embedding
frequency
register
language mixture
```

## Candidate relationship

```text
source span
target expression
operation type
phonetic alignment
semantic relationships
meter comparison
individual scores
overall rank
explanation
provenance
```

## Project profile

```text
characters and names
themes
languages
preferred accents
forbidden topics
rhyme strictness
style constraints
custom vocabulary
pronunciation corrections
```

---

# 12. Learning from the user

The product should learn from explicit behavior:

* accepted suggestion;
* rejected suggestion;
* saved but unused suggestion;
* pronunciation correction;
* score adjustment;
* “too obvious” feedback;
* “does not sound similar” feedback;
* “good sound, wrong meaning” feedback.

This creates a personal ranking profile.

The system should not silently train on private lyrics for unrelated users. Project text and feedback need clear privacy controls and separate consent for any broader model training.

---

# 13. Evaluation strategy

The product requires a purpose-built benchmark.

## Annotated test corpus

Collect examples of:

* exact rhyme;
* slant rhyme;
* multisyllabic rhyme;
* oronyms;
* portmanteaus;
* name insertions;
* semantic-chain puns;
* multilingual puns;
* pronunciation bending;
* false positives.

For each example, annotate:

```text
source span
target span
mechanism
IPA variants
semantic connection
meter relationship
human quality rating
```

## Retrieval evaluation

Measure:

* whether the known candidate appears in the top 10, 50, and 100;
* ranking position;
* false-positive rate;
* diversity of mechanisms;
* response latency.

## Human evaluation

Writers should rate:

* sound plausibility;
* contextual usefulness;
* originality;
* performability;
* explanation accuracy;
* likelihood of actually using the suggestion.

The system should be optimized for **useful discoveries per writing session**, not merely benchmark accuracy.

---

# 14. Development workstreams

This should not be approached as a disposable MVP, but it still needs ordered workstreams.

## Workstream A: Linguistic foundation

* canonical document representation;
* pronunciation adapters;
* IPA normalization;
* syllabification and stress;
* phonological feature distance;
* lyric-aware tokenization;
* phoneme and rhyme indexes.

## Workstream B: Search mechanisms

* rhyme and echo search;
* phrase-to-word resegmentation;
* morphology and portmanteaus;
* names and project entities;
* multilingual correspondence;
* semantic-phonetic intersection.

## Workstream C: Writing environment

* production text editor;
* incremental annotations;
* candidate cards;
* transformation previews;
* project profiles;
* revision history;
* export.

## Workstream D: Context and generation

* semantic-field detection;
* structured LLM reranking;
* constrained line generation;
* explanations;
* personal ranking profiles.

## Workstream E: Performance layer

* audio upload and recording;
* forced alignment;
* beat grid;
* performed-pronunciation extraction;
* duration-aware suggestions.

## Workstream F: Quality platform

* annotated corpus;
* regression tests;
* ranking experiments;
* writer feedback system;
* latency and cost monitoring;
* dependency and corpus licensing review.

---

# 15. Important risks

## Pronunciation ambiguity

Dictionary IPA will not represent every accent or performance. The system must expose alternatives and let users correct it.

## Too many clever but unusable suggestions

Phonetic search produces noise. Context, grammar, frequency, and meter must be used in ranking rather than applied only after results are displayed.

## Language-model hallucination

The LLM may invent etymologies or misdescribe sounds. Explanations should be generated from stored alignments and structured scores.

## Multilingual accuracy

Cross-language puns depend on the intended listener and accent. The product should say “plausible under this pronunciation,” not declare every match objectively correct.

## Copyright and corpora

Lyrics and dictionaries may have restrictive licenses. The product needs provenance records for each lexical, pronunciation, phrase, and training source.

## Homogenizing creativity

The application should show mechanisms and unusual neighborhoods, not continually push writers toward one statistically preferred line.

---

# 16. Product definition

The finished product is:

> A browser-based linguistic composition environment that continuously analyzes text at phonetic, semantic, morphological, rhythmic, and multilingual levels; retrieves surprising language relationships; explains their mechanics; and helps the writer transform them into usable lines without hiding the underlying reasoning.

Its core competitive capability is not “AI writes lyrics.”

It is:

> **The system can search across word boundaries, pronunciations, meanings, names, languages, and meter at the same time.**

That combined search is what makes constructions such as “not a cult / nautical” or “invested / Ina-terested” discoverable rather than accidental.
