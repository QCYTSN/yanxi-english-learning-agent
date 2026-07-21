# Speaking report template

The report passed to `ielts-coach speaking import-report` may be Markdown with
YAML frontmatter:

```yaml
session_id: S-YYYYMMDD-001
mode: full_mock
occurred_at: 2026-07-22T19:00:00+08:00
duration_minutes: 14
estimated_overall: 6.0
parts:
  - part: 1
    topics: [study, home]
  - part: 2
    topic: a useful skill
  - part: 3
    topics: [education, technology]
criterion_scores:
  - criterion: FC
    score: 6.0
    confidence: medium
    evidence: ["Several long pauses in Part 2"]
  - criterion: LR
    score: 6.0
    confidence: medium
    evidence: ["Repeated use of 'important'"]
errors:
  - tag: FC_LONG_PAUSE
    count: 3
    evidence: Part 2
feedback:
  priorities:
    - Extend Part 3 answers with a reason and example.
transcript: null
```

Do not invent pronunciation evidence when the report contains only text.
