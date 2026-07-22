# Timed Reading practice

## Start

1. Create the Session first so answer metadata is locked at the data layer:

```bash
ielts-coach session start reading --passage-id <passage-id> \
  --mode timed-practice --time-limit-minutes 20
```

2. Show the indexed passage set without answer metadata:

```bash
ielts-coach question set <passage-id>
```

Use 20 minutes for a one-passage drill and 60 minutes only for a complete
Academic Reading test supplied by the user. Starter passages are short teaching
demos, not official full-length passage simulations.

## Before submission

- Show all selected questions and the passage.
- Do not reveal answers, correctness, locations, paraphrases, vocabulary help or
  progressive hints.
- Do not mark one answer while other answers remain open.
- Record zero hints. If the learner asks for help, ask whether to abandon exam
  mode and convert the Session to guided practice.

## Submission and review

Record `submitted_at` before any answer is revealed. After submission, use the
verified key, set `answer_revealed_at`, mark each verified item, and then run the
normal passage-grounded wrong-answer review. Do not derive a Band without a
documented conversion source.

While an unsubmitted timed Session exists for the passage, `question show
--with-answer` and `question set --with-answers` are blocked by the local data
layer. Save the submitted Session state before requesting the key.
