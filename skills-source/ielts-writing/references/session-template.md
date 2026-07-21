# Writing session template

```yaml
session_id: W-YYYYMMDD-001
module: writing
status: completed
occurred_at: 2026-07-22T10:00:00+08:00
source_id: optional-corpus-id
question_id: optional-indexed-question-id
mode: compare-versions
duration_minutes: 55
band: 6.5
versions:
  - label: v1
    content: "..."
    word_count: 278
  - label: v2
    content: "..."
    word_count: 291
criterion_scores:
  - version: v1
    criterion: TR
    score: 6.0
    confidence: medium
    evidence:
      - "Paragraph 3 states a claim without development."
  - version: v2
    criterion: TR
    score: 6.5
    confidence: medium
    evidence:
      - "The revised paragraph adds a reason and example."
errors:
  - tag: GRA_ARTICLE
    count: 3
    evidence: "a government should..."
```

Keep full learner versions in the private session file. Evidence excerpts should
be short and tied to the learner's own work.
