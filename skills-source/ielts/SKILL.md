---
name: ielts
description: "Unified IELTS Academic entrypoint for generic or cross-skill requests: first-use setup, diagnostic, today's task, goals, weekly planning, or an ambiguous request to study. Do not use as a preflight when the request is already clearly about Writing, Speaking, Reading, Progress, Listening review, or Corpus; use that specialist directly."
---

# IELTS router

Route; do not teach specialist content here.

## Fast path

- If the request clearly names a module or includes an essay, passage, question,
  answer, transcript, score, or corpus operation, hand off immediately to the
  matching specialist. Do not run global status checks first.
- For a generic start, plan, goal, or first-use request, run exactly one read-only
  preflight: `ielts-coach study-context`.
- Do not separately run summary, allocation, learning-profile, onboarding status,
  and diagnostic status in the same turn; the compact context replaces them.
- Do not narrate routine file reads or CLI calls. Report only information that
  changes the learner's next action.
- Before creating another formal Session, use `ielts-coach session resume` and
  continue an active one when it matches the learner's intent.

## Routing

- Writing task, essay, scoring or revision: `ielts-writing`.
- Speaking mock, Cue Card, Voice/Live report or story: `ielts-speaking`.
- Reading practice, passage, question or language analysis: `ielts-reading`.
- Question search, draw, import or provenance: `ielts-corpus`.
- Scores, Listening review, trends, errors or allocation: `ielts-progress`.

## First use and diagnostic

If onboarding is pending, ask once for the missing setup information and save it
with `ielts-coach onboarding complete --setup-file <file>`. Do not repeatedly ask
for stored targets.

A missing baseline does not block direct practice. For a generic start, offer a
quick diagnostic or direct practice in one short choice. Read
`references/diagnostic-policy.md` only when the learner chooses a diagnostic.

IELTS Academic is the only supported exam type. Do not route General Training
Reading or letter-writing tasks into Academic workflows.

## Output

For a daily recommendation, give one primary task, one optional maintenance
task, time, a short data reason, and then start once the learner accepts. Keep AI
scores labelled as estimates and respect corpus provenance.
