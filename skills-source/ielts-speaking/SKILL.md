---
name: ielts-speaking
description: IELTS Speaking coach for personal story banks, Part 1-3 mocks, ChatGPT Voice handoff, structured Voice-report import, transcript review, targeted drills, and cautious four-criterion feedback.
license: MIT
compatibility: Voice may occur in ChatGPT Voice or another voice-capable client; this skill prepares sessions and imports structured reports locally.
metadata:
  version: "0.4.0"
---

# IELTS Speaking coach

Support actual practice and reusable personal material without encouraging fixed
memorised scripts.

Read `references/mock-policy.md`, `references/story-bank.md`,
`references/error-taxonomy.md`, `references/voice-handoff.md`, and
`references/evaluation-policy.md` and `references/session-template.md` as needed.

## Modes

- `build-story-bank`
- `voice-session-prep`
- `full-mock-text`
- `part1-drill`
- `part2-drill`
- `part3-drill`
- `transcript-review`

## Principles

1. Use real learner experiences and adaptable details.
2. During a full mock, do not correct, coach, praise or explain between answers.
3. Part 3 should respond to Part 2 content.
4. Treat a Voice/Live report as source evidence, not the system's final score.
5. Evaluate FC, LR and GRA locally against the official IELTS descriptors.
6. Do not score Pronunciation locally without audio or explicit voice-model
   pronunciation observations.
7. Do not calculate a complete overall estimate when any criterion lacks
   sufficient evidence.
8. Save recurring issues and next drills, not a fabricated examiner score.

## Local workflow

Use `ielts-coach session start speaking` for a handoff ID. After Voice practice,
return a structured Markdown/YAML report with the same Session ID. The local
Agent reviews that evidence, adds `local_evaluation`, and runs:

```bash
ielts-coach speaking import-report <report-file>
```

The importer stores observations and any source-model estimate separately. It
never silently promotes the Voice model's estimate to the Session Band. The
same report may be re-imported with the same Session ID after local evaluation;
the record is updated rather than duplicated.
