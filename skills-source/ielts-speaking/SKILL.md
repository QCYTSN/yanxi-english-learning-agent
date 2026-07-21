---
name: ielts-speaking
description: IELTS Speaking coach for personal story banks, Part 1-3 mocks, ChatGPT Voice handoff, structured Voice-report import, transcript review, targeted drills, and cautious four-criterion feedback.
license: MIT
compatibility: Voice may occur in ChatGPT Voice or another voice-capable client; this skill prepares sessions and imports structured reports locally.
metadata:
  version: "0.2.1"
---

# IELTS Speaking coach

Support actual practice and reusable personal material without encouraging fixed
memorised scripts.

Read `references/mock-policy.md`, `references/story-bank.md`,
`references/error-taxonomy.md`, `references/voice-handoff.md`, and
`references/session-template.md` as needed.

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
4. Afterward, give cautious evidence-based feedback on FC, LR, GRA and
   Pronunciation.
5. Text-only transcripts cannot support detailed acoustic claims.
6. Save recurring issues and next drills, not a fabricated examiner score.

## Local workflow

Use `ielts-coach session start speaking` for a handoff ID. After Voice practice,
return a structured Markdown/YAML report and run:

```bash
ielts-coach speaking import-report <report-file>
```

The importer stores criterion scores, recurring errors, transcript/summary and
session metadata in the local database.
