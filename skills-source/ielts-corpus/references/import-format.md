# Corpus import format

## Manifest

```yaml
corpus_id: my-private-corpus
title: My legally obtained practice material
source_type: licensed_private
authenticity: official_practice_book
storage:
  mode: external_reference
  local_path: D:\IELTS\my-private-corpus
permissions:
  bundled_with_project: false
  redistribution_allowed: false
  local_personal_use_only: true
files:
  - kind: passages
    path: passages.jsonl
  - kind: questions
    path: questions.jsonl
```

## Passage JSONL item

```json
{"passage_id":"my-private-corpus:P-001","title":"...","body":["Paragraph A...","Paragraph B..."],"source_type":"licensed_private","topics":["science"]}
```

## Question JSONL item

```json
{"question_id":"my-private-corpus:Q-001","module":"reading","passage_id":"my-private-corpus:P-001","question_type":"multiple_choice","content":"...","options":{"A":"...","B":"..."},"correct_answer":"B","evidence_location":"Paragraph B","source_type":"licensed_private","authenticity":"official_practice_book","review_status":"verified"}
```

The source files stay in the user's local corpus. The database stores a local
index and structured fields.

IDs must be globally unique within IELTS_HOME. Item provenance must match the
Manifest; mismatches are rejected rather than silently relabelled.
