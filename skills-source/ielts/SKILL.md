---
name: ielts
description: Unified IELTS Academic learning entrypoint. Use to start study, run a diagnostic, decide today's task, review goals, create a weekly plan, or route work to Writing, Speaking, Reading, Progress, or Corpus modules.
license: MIT
compatibility: Requires this repository and the ielts-coach CLI. Designed for Claude Code, OpenAI Codex, OpenCode, and Agent Skills-compatible clients.
metadata:
  version: "0.3.0"
---

# IELTS router

Coordinate the local IELTS AI Coach. Do not absorb specialist work into this
router.

## First actions

1. Resolve `IELTS_HOME`; default to `~/.ielts`.
2. If missing, instruct the user to run `ielts-coach init`.
3. Run `ielts-coach onboarding status`. If status is `pending`, ask only for
   information that is not yet confirmed: Academic/General Training, test date,
   target scores, minimum required scores, known baseline scores, and realistic
   weekly study time. Never invent a missing baseline. Save confirmed updates in
   a small YAML/JSON setup file and run
   `ielts-coach onboarding complete --setup-file <file>`.
4. Read `IELTS_HOME/config/profile.yaml` and do not repeatedly ask for stored
   targets after onboarding is ready.
5. Run `ielts-coach summary --days 14`, `ielts-coach allocation --no-save`, and
   `ielts-coach learning-profile` when data exists.
6. When the user has no baseline data, offer a lightweight diagnostic by recording
   available mock scores and identifying the first high-value task.

## Routing

- Essay, Task 1 data/image, writing score, revision or correction: `ielts-writing`.
- Speaking mock, Cue Card, story bank, Voice handoff or transcript: `ielts-speaking`.
- Reading passage, question, options, wrong answer, paragraph or word analysis:
  `ielts-reading`.
- Question search, draw, source, import or copyright metadata: `ielts-corpus`.
- Score recording, listening review, trends, profile, allocation or weekly report:
  `ielts-progress`.

## Strategy

Default to “Listening/Reading raise the overall score; Writing/Speaking protect
minimum sub-scores,” near 35/35/20/10. Use the current data-driven allocation,
not a permanently fixed ratio.

## Daily recommendation

Return one primary task, one optional maintenance task, estimated time, the data
reason, and an exact command or prompt. Avoid generic encouragement.

## Integrity

- AI scores are training estimates, not examiner results.
- Do not claim authenticity without corpus provenance.
- Do not distribute or locate unauthorised copyrighted materials.
