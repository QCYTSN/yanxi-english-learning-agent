---
name: ielts-corpus
description: "Manage the local IELTS corpus and question bank. Use directly to register user-owned materials, index passages and questions, search or draw tasks, avoid repeats, inspect provenance, or explain copyright-safe import formats."
---

# IELTS Corpus manager

Use deterministic CLI results; never claim a question exists from memory.

## Efficient workflow

- For search, draw, show or list, run only the matching command and return its
  useful result without a global study preflight.
- Read `references/selection-policy.md` only when choosing a learning task,
  `references/import-format.md` only for import, and
  `references/provenance.md` only for source/authenticity questions.
- Do not load all three references for a routine search.

```bash
ielts-coach corpus import <manifest.yaml>
ielts-coach question search "urban" --module reading
ielts-coach question show <question-id>
ielts-coach question draw --module writing --task task2 --exclude-completed
```

Preserve corpus ID, source type, authenticity, review status and content hash.
Reveal keys only when the learning workflow permits it. Do not locate or bundle
pirated materials, infer authenticity from availability, or label synthetic or
reported questions as official. The importer accepts prepared JSONL; it is not
a full PDF/OCR engine.
