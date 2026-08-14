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
  - kind: assessment_packs
    path: assessment-packs.jsonl
```

## Passage JSONL item

```json
{"passage_id":"my-private-corpus:P-001","title":"...","body":["Paragraph A...","Paragraph B..."],"source_type":"licensed_private","topics":["science"]}
```

## Question JSONL item

```json
{"question_id":"my-private-corpus:Q-001","module":"reading","passage_id":"my-private-corpus:P-001","question_type":"multiple_choice","content":"...","options":{"A":"...","B":"..."},"correct_answer":"B","evidence_location":"Paragraph B","source_type":"licensed_private","authenticity":"official_practice_book","review_status":"reviewed"}
```

The source files stay in the user's local corpus. The database stores a local
index and structured fields.

IDs must be globally unique within IELTS_HOME. Item provenance must match the
Manifest; mismatches are rejected rather than silently relabelled.

## Assessment-pack JSONL item

An assessment pack groups content into a declared practice contract. It does
not duplicate copyrighted source text; it references indexed local item IDs.

```json
{"pack_id":"my-private-corpus:R-TEST-01","module":"reading","title":"Academic Reading Test 1","practice_mode":"full_mock","standard_profile":"ielts-academic","standard_version":"2026-07","source_type":"licensed_private","authenticity":"official_practice_book","rights_status":"local_private","review_status":"reviewed","passage_ids":["my-private-corpus:P-001","my-private-corpus:P-002","my-private-corpus:P-003"],"question_ids":["40 indexed question IDs, abbreviated here"],"structure":{"time_limit_minutes":60,"passages":[{"passage_id":"my-private-corpus:P-001","question_count":13,"word_count":850},{"passage_id":"my-private-corpus:P-002","question_count":13,"word_count":850},{"passage_id":"my-private-corpus:P-003","question_count":14,"word_count":850}]}}
```

The `question_ids` array above is abbreviated for readability; an importable
full pack lists every referenced ID. Use `xiyan conformance pack <file>` before import. A full Reading pack
must contain three passages and 40 questions; a full Listening pack four
10-question parts; a full Writing pack both tasks with correct weighting; and a
full Speaking pack Parts 1-3 with Part 2/3 linkage and official timings.
