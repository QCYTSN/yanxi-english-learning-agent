# Reading session structure

```yaml
session_id: R-YYYYMMDD-001
module: reading
status: completed
occurred_at: 2026-07-22T10:00:00+08:00
source_id: optional-corpus-or-test-id
question_id: optional-primary-question-id
passage_id: START-RP-001
duration_minutes: 22
mode: timed-practice
time_limit_minutes: 20
started_at: 2026-07-22T09:00:00+08:00
submitted_at: 2026-07-22T09:20:00+08:00
answer_revealed_at: 2026-07-22T09:20:05+08:00
hints_used: 0
band: null
score_kind: answer_key_estimate
answer_key_source: user-owned Cambridge IELTS 20 Test 2 answer key
band_conversion_source: null
score:
  correct: 9
  total: 13
questions:
  - question_id: optional-indexed-id
    question_number: 17
    question_type: true_false_not_given
    user_answer: FALSE
    correct_answer: NOT GIVEN
    is_correct: false
    duration_seconds: 85
    evidence_location: Paragraph C
    explanation: The passage mentions the topic but not the claimed comparison.
    error_tags:
      - R_TFNG_OVER_INFERENCE
errors:
  - tag: R_TFNG_OVER_INFERENCE
    count: 1
    evidence: Q17
```

Save short evidence and analysis. Keep copyrighted full passages in the user's
private corpus, not duplicated into public project files.
