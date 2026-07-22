---
name: ielts
description: Unified IELTS Academic learning entrypoint. Use to start study, run a diagnostic, decide today's task, review goals, create a weekly plan, or route work to Writing, Speaking, Reading, Progress, or Corpus modules.
license: MIT
compatibility: Requires this repository and the ielts-coach CLI. Designed for Claude Code, OpenAI Codex, OpenCode, and Agent Skills-compatible clients.
metadata:
  version: "0.4.0"
---

# IELTS router

Coordinate the local IELTS AI Coach. Do not absorb specialist work into this
router.

This project supports IELTS Academic only. If a user asks for General Training,
explain that its Reading materials and Writing Task 1 letters differ and stop
before routing them into Academic practice.

## First actions

1. Resolve `IELTS_HOME`; default to `~/.ielts`.
2. If missing, instruct the user to run `ielts-coach init`.
3. Run `ielts-coach onboarding status`. If status is `pending`, ask only for
   information that is not yet confirmed: confirm Academic, test date,
   target scores, minimum required scores, known baseline scores, and realistic
   weekly study time. Never invent a missing baseline. Save confirmed updates in
   a small YAML/JSON setup file and run
   `ielts-coach onboarding complete --setup-file <file>`.
4. Read `IELTS_HOME/config/profile.yaml` and do not repeatedly ask for stored
   targets after onboarding is ready.
5. Run `ielts-coach summary --days 14`, `ielts-coach allocation --no-save`, and
   `ielts-coach learning-profile` when data exists.
6. Run `ielts-coach diagnostic status`. When the user has no usable baseline,
   use the standard diagnostic workflow in `references/diagnostic-policy.md`.
   Recommend `quick` for first use; use `full` only when the learner wants a
   complete four-skill baseline and has suitable user-owned material.

Do not require the learner to name or slash-invoke a specialist Skill. Infer the
intent from the request and route it. Explicit commands remain available for
clients that do not support automatic Skill discovery.

## Routing

- Essay, Task 1 data/image, writing score, revision or correction: `ielts-writing`.
- Speaking mock, Cue Card, story bank, Voice handoff or transcript: `ielts-speaking`.
- Reading passage, question, options, wrong answer, paragraph or word analysis:
  `ielts-reading`.
- Question search, draw, source, import or copyright metadata: `ielts-corpus`.
- Score recording, listening review, trends, profile, allocation or weekly report:
  `ielts-progress`.
- First-use placement or a new four-skill baseline: follow
  `references/diagnostic-policy.md`, then route each component normally.

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
