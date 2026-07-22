# Current core scope — V0.6

## Identity

IELTS AI Coach is an **agent-native, local-first IELTS Academic learning
system**. Claude Code, Codex or OpenCode supplies the model intelligence. The
project supplies six Skills, deterministic CLI tools, local data, indexed
questions, provenance, learning memory and planning.

The runtime is intent-first: a clear module request goes directly to its
specialist. Global onboarding, diagnostic, profile and allocation checks are not
mandatory preflight for every learning turn.

Formal saved practice uses a revisioned Study Runtime. Skills submit learner
work and validated feedback through CLI operations; Markdown remains the
human-readable mirror and SQLite remains the structured store. Writing and
Reading teaching contracts enforce the non-negotiable learning rules before
results are saved.

It is not a standalone chatbot that calls another model API.

## Six modules

1. `ielts`: router, diagnostic and daily recommendation
2. `ielts-writing`: active Writing coaching and criterion records
3. `ielts-speaking`: stories, mocks, Voice handoff and report review
4. `ielts-reading`: guided solving, wrong-answer explanation and close reading
5. `ielts-progress`: four-skill records, profiles, trends and allocation
6. `ielts-corpus`: BYOC provenance, indexing, search and question drawing

Listening remains inside Progress because audio timing and acoustic analysis are
not yet implemented. When transcript, question and key exist, Progress may
perform a limited evidence-based listening review.

## User score strategy

Default target direction:

- Listening 7.5–8.0
- Reading 7.5–8.0
- Writing 6.5–7.0
- Speaking 5.5–6.0

Start near 35/35/20/10. Listening/Reading raise the overall score; Writing and
Speaking protect minimum sub-scores. The split changes only with data and within
the configured maximum shift.

## Required loops

### Writing

Independent response → evidence → cautious score → no more than three priority
problems → learner V2 → version comparison → detailed correction → optional
higher-band alternative → structured archive.

### Reading

Independent answer or progressive hints → passage location → paraphrase map →
correct-answer reasoning → distractor reasoning → error tag → next-question
rule → question-level archive.

### Speaking

Question selection → uninterrupted Voice/Live mock → source observations and
optional provisional source score → independent local official-rubric review →
partial or complete evidence-labelled profile → error archive → targeted drill.
Personal experiences replace fixed universal scripts.

### Listening

Independent legitimate practice → score and wrong-answer record → limited
transcript-based review where evidence exists → pattern analysis.

## Corpus policy

The repository contains system code, schemas, tools, documentation and original
starter data. Third-party content remains BYOC and local. The system records
source type, authenticity, review status and content hash; it does not provide
unauthorised copies.

## Deferred

Frontend, authentication, cloud sync, multi-user accounts, full PDF/OCR book
parsing, automatic speech-to-text, acoustic pronunciation scoring, RAG, model
fine-tuning, autonomous multi-agent orchestration and paid API integration.
