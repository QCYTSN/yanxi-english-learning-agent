# Privacy and copyright

The repository contains code, Skills, schemas, import tools, documentation and
original starter data. It does not contain Cambridge IELTS books, commercial
question banks or user records.

## Local storage is not local inference

Corpus files and records are stored locally. When a remote Agent reads a passage,
that content may be sent to the selected model provider or intermediary. Users
must confirm that their licence and provider settings permit this processing.

## Data minimisation

Prefer source references, current exercises, relevant paragraphs, local paths
outside Git, redacted personal data, and no automatic private-corpus backup.

Before a Skill intentionally sends indexed private material to a remote model,
it must run `xiyan privacy check --remote` with a source, question or
corpus identifier. When `allow_cloud_upload` is false, private sources are
blocked unless the learner gives explicit one-time consent for that operation.
Consent is not persisted.

This gate cannot undo text that an external Agent client read before checking.
Do not ask an Agent to open private material until its licence, provider and
processing route have been considered.

Runtime telemetry is optional and metadata-only: module, event label, token
counts, latency and tool-call count. Its schema rejects prompt text, learner
answers, transcripts and corpus content.

## Indexing boundary

The structured importer indexes user-prepared JSONL. It does not scrape, OCR or
distribute commercial books. Database provenance does not grant redistribution
rights.

Officially accessible web resources may remain copyrighted. Link to their owner
unless an explicit licence permits repackaging.
