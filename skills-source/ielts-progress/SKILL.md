---
name: ielts-progress
description: Record and analyse IELTS Listening, Reading, Writing and Speaking sessions. Use for score entry, listening-error review, error aggregation, learning profiles, weekly reports, target-gap analysis, and controlled adjustment of the 70/30 study allocation.
license: MIT
compatibility: Requires IELTS_HOME and the ielts-coach CLI.
metadata:
  version: "0.4.0"
---

# IELTS progress manager

Use database and CLI output as the source of truth. Do not invent historical
scores from conversation memory.

## Commands

```bash
ielts-coach session start <module>
ielts-coach session finish <session-file>
ielts-coach session list
ielts-coach summary --days 14
ielts-coach learning-profile
ielts-coach allocation
ielts-coach weekly-report
ielts-coach diagnostic status
ielts-coach calibration report
```

Read `references/allocation-policy.md` before changing study ratios and
`references/error-taxonomy.md` for Listening and cross-module tags. Read
`references/calibration-policy.md` before claiming a model's estimates are
well-calibrated.

## Responsibilities

- record structured practice sessions and stable error tags;
- maintain error, ability and behaviour views;
- analyse Listening mistakes by spelling, number, distractor, lost position,
  map, multiple choice, attention and timing;
- compare averages and criterion scores with target and minimum requirements;
- respect the maximum per-period allocation shift;
- recommend one operational next task.

## Score provenance

Never merge unlike scores as if they had the same evidential status.

- `official_result`: a score reported by an authorised IELTS test result;
- `answer_key_estimate`: Listening/Reading result calculated from a verified key;
- `ai_training_estimate`: Writing/Speaking estimate produced locally against the
  official IELTS descriptors, with a confidence label;
- `partial_profile`: criterion evidence is incomplete, so no full overall score;
- `unspecified`: legacy data whose provenance is not yet known.

A Voice/Live model's provisional opinion is source evidence, not the stored
Speaking result. Low-confidence AI estimates and partial profiles must not drive
the automatic allocation. Do not call any AI estimate an examiner score.

For `answer_key_estimate`, record `answer_key_source`. If a Band is derived from
the raw score, also record `band_conversion_source`; otherwise keep the raw score
without inventing a Band conversion.

## Listening-review mode

When transcript, question, answer and key are supplied, explain the local
language or distractor evidence. When audio or timing evidence is absent, do not
claim to diagnose pronunciation, acoustic confusion or exact time position.

## Boundaries

- Full Reading explanation belongs to `ielts-reading`.
- Question selection and source management belong to `ielts-corpus`.
- Writing/Speaking estimates remain uncertain until calibrated.
- Numeric Writing/Speaking feedback must cite the applicable official IELTS
  Band Descriptors; otherwise keep the feedback qualitative.
