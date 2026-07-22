# Usage workflows

## Writing

```text
/ielts-writing
Draw an unused starter Task 2 question. Do not show an outline or model answer.
Start timed practice and create a structured writing Session.
```

Expected: independent V1 → evidence score → three priorities → learner V2 →
comparison → final review → `versions`, `criterion_scores`, and errors saved.

## Reading guided solving

```text
/ielts-reading
Use START-R-003. Show the passage and question without the answer. Give only
Level 1 hints until I answer.
```

## Reading wrong-answer review

```text
/ielts-reading
For this passage and question, my answer was B and the key is C. Locate the exact
evidence, map the paraphrases, explain C, explain why B and the other distractors
fail, tag my underlying error, and save a reading Session.
```

## Close reading and vocabulary

```text
/ielts-reading
Explain Paragraph C: its purpose, sentence logic, references, long sentences,
paraphrases and possible question points. Then explain "account for" only in this
context.
```

## Speaking with Voice

Create a handoff ID:

```powershell
ielts-coach session start speaking
```

Voice/Live performs the uninterrupted interaction and returns structured
observations. Any score it gives is explicitly provisional. Save the report and
run:

```powershell
ielts-coach speaking import-report voice-report.md
```

The local Agent then evaluates only criteria supported by the evidence against
the official IELTS Speaking Band Descriptors. A transcript can support FC, LR
and GRA, but it cannot support Pronunciation or a full overall score. A full
four-criterion estimate requires audio access or explicit Voice-model
pronunciation observations. Content is not a fifth criterion: relevance,
development and logical sequencing are considered within FC, and appropriacy
and flexibility within LR.

## Listening review

Record scores independently. When transcript and question evidence exist, ask
`ielts-progress` to explain distractors or local language. Do not claim acoustic
analysis from text alone.

## Corpus and weekly planning

```powershell
ielts-coach question draw --module reading --type true_false_not_given --exclude-completed
ielts-coach learning-profile
ielts-coach trends
ielts-coach weekly-report
```
