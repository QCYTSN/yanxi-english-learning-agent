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

The `allow_cloud_upload` profile field is an advisory policy for the Agent; the
CLI cannot technically prevent a remote Agent client from transmitting text it
has already read. Do not ask an Agent to open private material unless its
licence and the selected provider permit that processing.

## Indexing boundary

The structured importer indexes user-prepared JSONL. It does not scrape, OCR or
distribute commercial books. Database provenance does not grant redistribution
rights.

Officially accessible web resources may remain copyrighted. Link to their owner
unless an explicit licence permits repackaging.
