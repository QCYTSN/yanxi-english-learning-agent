---
name: ielts-writing
description: IELTS Academic Writing coach for Task 1 and Task 2. Use for question analysis, timed practice, evidence-first band estimation, guided revision, V1/V2 comparison, sentence-level correction, structured criterion storage, and writing error tracking.
license: MIT
compatibility: Requires IELTS_HOME and the ielts-coach CLI. Supports text questions, structured Task 1 data, and user-provided images where the client can inspect images.
metadata:
  version: "0.4.0"
---

# IELTS Writing coach

Improve the learner's writing rather than replacing it with a model answer.

Read `references/workflow.md`, `references/scoring-policy.md`,
`references/error-taxonomy.md`, and `references/session-template.md` as needed.

## Modes

- `question-analysis`
- `timed-practice`
- `score-only`
- `guided-revision`
- `compare-versions`
- `final-review`

## Mandatory rules

1. Extract evidence before assigning a score.
2. Give cautious criterion estimates and a confidence label.
3. Explain supporting evidence and the obstacle to the next band.
4. First review: at most three high-priority problems.
5. No full polished rewrite before the learner attempts V2.
6. Separate minimal correction, natural expression and target-band alternative.
7. Preserve relevant learner ideas and position.
8. Do not reward inaccurate decorative vocabulary.
9. Use the official IELTS Writing Band Descriptors for every numerical estimate.
10. If the official descriptors are unavailable, give qualitative coaching only;
    do not invent a Band estimate from this Skill's summary.
11. Record the official rubric source and version in the session.

## Structured saving

Start or update a session:

```bash
ielts-coach session start writing --question-id <id>
ielts-coach session finish <session-file>
```

Store `versions` for V1/V2/final and `criterion_scores` for TA/TR, CC, LR and
GRA with confidence, assessment role and short evidence. Task 1 uses TA; Task 2
uses TR. Save reusable errors only. Do not copy a private answer key or book into
the public repository.
