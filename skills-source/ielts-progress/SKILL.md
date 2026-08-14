---
name: ielts-progress
description: "Record or analyse IELTS progress. Use directly for score entry, Listening error review, error aggregation, learning profiles, trends, weekly reports, target gaps, diagnostic status, calibration reports, and controlled 70/30 allocation changes."
---

# IELTS progress manager

Use local data as truth; never reconstruct history from conversation memory.

## Efficient workflow

- For a narrow score entry or Listening question, perform only that operation.
- For one-module personalisation, use `xiyan study-context --module <name>`.
- For a daily or cross-module decision, use `xiyan study-context` once.
- Run full summary, trends, learning-profile, weekly-report, allocation or
  calibration commands only when the learner explicitly requests that view.
- Do not narrate database reads or run several overlapping reports by default.

Read `references/allocation-policy.md` only before changing ratios,
`references/error-taxonomy.md` when tagging Listening/behaviour errors, and
`references/calibration-policy.md` when evaluating calibration.

## Integrity

Keep official results, verified answer-key estimates, local AI estimates,
partial profiles and legacy unspecified scores separate. Require answer-key and
Band-conversion provenance where applicable. Low-confidence AI estimates,
partial Speaking profiles and source-model provisional scores must not drive
automatic allocation.

For Listening, explain transcript-grounded language or distractors when the
question, answer and key exist. Without audio/timing evidence, do not claim an
acoustic diagnosis.

Full Reading teaching belongs to `ielts-reading`; corpus operations belong to
`ielts-corpus`. Numeric Writing/Speaking feedback requires the applicable
official Band Descriptors and remains an AI training estimate.

When counts are available, optionally record one metadata-only telemetry event;
never include prompts, answers, transcripts or corpus text.
