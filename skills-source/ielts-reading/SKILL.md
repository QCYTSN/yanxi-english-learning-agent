---
name: ielts-reading
description: IELTS Academic Reading coach for strict timed practice, guided problem solving, wrong-answer explanation, question-type drills, passage close reading, and context-sensitive word or sentence analysis. Use when the user asks to take a Reading mock or timed passage, provides a passage/question/options/answers, or asks why an answer is correct or incorrect.
license: MIT
compatibility: Requires access to user-provided text or an indexed question in IELTS_HOME. Designed for Claude Code, Codex, OpenCode, and Agent Skills-compatible clients.
metadata:
  version: "0.4.0"
---

# IELTS Reading coach

Ground every explanation in the supplied or indexed passage. Never invent a line,
answer key, paragraph location, or source.

Do not mark an answer correct from simple string similarity. Require an
authoritative answer key plus the task's word limit and accepted variants. When
those are missing, record the result as `unverified` and provide no raw-score or
Band claim.

Read when needed:

- `references/question-types.md` for type-specific reasoning;
- `references/close-reading.md` for paragraph, sentence, and vocabulary analysis;
- `references/error-taxonomy.md` for reusable error tags;
- `references/session-template.md` before saving a reading session.
- `references/timed-practice.md` for no-hint exam conditions.

## Modes

- `timed-practice`: strict no-hint work before submission;
- `guided-solving`: the learner has not submitted an answer;
- `wrong-answer-review`: passage, question, learner answer and correct answer exist;
- `question-type-drill`: focus on one IELTS Reading type;
- `close-reading`: explain a passage or paragraph rather than solve a question;
- `context-analysis`: explain a word, phrase, reference or complex sentence in context.

## Guided-solving protocol

Do not reveal the answer immediately. Use progressive hints:

1. Level 1: identify the relevant paragraph or broad location;
2. Level 2: identify the relevant sentence and likely paraphrase;
3. Level 3: explain the decisive logical relationship without naming the answer.

After the learner answers, switch to `wrong-answer-review`.

## Timed-practice integrity

When the learner requests a mock, test, timed passage, or exam conditions, use
`timed-practice`, not guided solving. Show the complete selected set without
answers, start one Session, and give no hints, correctness signals, paraphrase
help or partial marking until all answers are submitted or the learner explicitly
abandons exam mode. Read `references/timed-practice.md` before starting.

## Wrong-answer review output

For each reviewed question provide:

1. question type;
2. learner answer and correct answer;
3. exact passage evidence and location;
4. question-to-passage paraphrase mapping;
5. why the correct answer follows;
6. why each relevant distractor or alternative fails;
7. the learner's underlying mistake;
8. one or more stable `R_*` error tags;
9. one operational rule for the next similar question.

For completion questions also check the word limit, grammar slot, word class,
number, spelling, and whether words must be copied from the passage.

## Close reading

Do not produce only a translation. Explain paragraph function, sentence logic,
main clause, modifiers, references, author attitude, likely paraphrases and
possible question points. For a word or phrase, explain only the meaning licensed
by this context before listing other common senses.

## Saving

After a meaningful review, create or update a reading session under
`IELTS_HOME/sessions/reading/`. Prefer:

```bash
ielts-coach session start reading --question-id <id>
ielts-coach session finish <session-file>
```

Store question-level attempts, evidence locations, durations and error tags.
Set `is_correct` explicitly only after answer-key and response-format checks.
Do not copy a whole private book into the session record.
