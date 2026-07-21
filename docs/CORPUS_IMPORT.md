# Corpus import

## Three levels of use

### 1. Reference only

For a paper book, record source, score and errors without copying the passage.

### 2. Current exercise only

Provide the Agent with the relevant passage/question for review and save only
short evidence in the Session.

### 3. Structured local index

Prepare a Manifest and JSONL files in your private local directory.

```yaml
corpus_id: my-private-reading
source_type: licensed_private
authenticity: official_practice_book
title: My legally obtained practice material
storage:
  mode: external_reference
  local_path: D:\IELTS\my-private-reading
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

Passage item:

```json
{"passage_id":"P-001","title":"...","body":["A. ...","B. ..."],"source_type":"licensed_private","topics":["science"]}
```

Question item:

```json
{"question_id":"Q-001","module":"reading","passage_id":"P-001","question_type":"multiple_choice","content":"...","options":{"A":"...","B":"..."},"correct_answer":"B","evidence_location":"Paragraph B","source_type":"licensed_private","authenticity":"official_practice_book","review_status":"verified"}
```

Question and passage IDs are global inside one IELTS_HOME. Prefix private IDs
with the corpus ID, for example `my-private-reading:Q-001` and
`my-private-reading:P-001`. Imports reject an ID already owned by another
corpus instead of overwriting it. Item-level `corpus_id`, `source_type` and
`authenticity`, when supplied, must agree with the Manifest.

Import and inspect:

```powershell
ielts-coach corpus import manifest.yaml
ielts-coach corpus stats --corpus-id my-private-reading
ielts-coach question search "keyword" --module reading
```

Reindex after editing the JSONL:

```powershell
ielts-coach corpus reindex my-private-reading
```

Duplicate content is detected by hash. The importer deliberately does not bulk
OCR or parse a commercial book automatically.
