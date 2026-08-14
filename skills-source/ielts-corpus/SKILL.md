---
name: ielts-corpus
description: "Manage the local IELTS corpus and question bank. Use directly to register user-owned materials, index passages and questions, search or draw tasks, avoid repeats, inspect provenance, or explain copyright-safe import formats."
---

# IELTS Corpus manager

Use deterministic CLI results; never claim a question exists from memory.

## Efficient workflow

- For search, draw, show or list, run the matching command without a global preflight.
- Read `references/selection-policy.md` only when choosing a learning task,
  `references/import-format.md` only for import, and
  `references/provenance.md` only for source/authenticity questions.
- Do not load all three references for a routine search.

```bash
xiyan corpus import <manifest.yaml>
xiyan question search "urban" --module reading
xiyan question show <question-id>
xiyan question draw --module writing --task task2 --exclude-completed
```

Preserve corpus ID, source type, authenticity, review status and content hash.
Reveal keys only when permitted. Never bundle pirated material, infer
authenticity from availability, or label reported/synthetic items official.
The importer accepts prepared JSONL, not PDF/OCR.

Conformance is separate from provenance. Run `xiyan conformance pack`;
only a reviewed, verified `full_mock` may support Band conversion.

Before remote processing of private material, run `xiyan privacy check
--remote --question-id <id>`; require informed one-time consent if blocked.
