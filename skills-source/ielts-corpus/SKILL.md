---
name: ielts-corpus
description: Manage the local IELTS question bank and corpus provenance. Use to register user-owned materials, index passages and questions, search or draw questions, avoid repeats, inspect source metadata, and explain copyright-safe import formats.
license: MIT
compatibility: Requires IELTS_HOME and the ielts-coach CLI. Does not parse or distribute copyrighted books automatically.
metadata:
  version: "0.3.0"
---

# IELTS Corpus manager

Use deterministic CLI results rather than claiming a question exists from
conversation memory.

Read:

- `references/import-format.md` for JSONL and manifest structure;
- `references/provenance.md` for source and authenticity rules;
- `references/selection-policy.md` before recommending or drawing questions.

## Commands

```bash
ielts-coach corpus import <manifest.yaml>
ielts-coach corpus list
ielts-coach question list --module reading
ielts-coach question search "urban" --module reading
ielts-coach question show <question-id>
ielts-coach question draw --module writing --task task2 --topic education
ielts-coach question draw --module reading --type multiple_choice --exclude-completed
```

## Responsibilities

- register corpus-level permissions and local paths;
- index standard JSONL passages and questions;
- preserve question-level source type, authenticity and review status;
- detect duplicate question content by hash;
- search by module, task, type, topic, source and corpus;
- exclude completed indexed questions when requested;
- show answer keys only when the learning workflow permits it.

## Boundaries

- Do not search for pirated copies or bundle Cambridge/third-party content.
- A publicly reachable page is not automatically redistributable.
- Do not label seasonal recollections or synthetic items as official questions.
- The current importer expects structured user-prepared JSONL; it is not a full
PDF/OCR ingestion engine.
