# Scoring policy

This file is an operational navigation guide, not a scoring scale. Use the
current official IELTS Writing Band Descriptors and Key Assessment Criteria for
every numerical estimate:

- https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf
- https://ielts.org/cdn/ielts-guides/ielts-writing-key-assessment-criteria.pdf

If those official descriptors are not available to the active Agent, do not
produce a numerical Band estimate. Give evidence-based qualitative feedback and
explain what source is missing.

## Evidence dimensions

### Task Achievement / Task Response

Check task coverage, clarity and consistency of position, relevance, development,
key-feature selection for Task 1, and use of supporting explanation/examples.
Use TA only for Task 1 and TR only for Task 2. Do not score a Task 1 visual when
the visual or its data cannot be read reliably.

### Coherence and Cohesion

Check progression, paragraph purpose, internal logic, referencing, and whether
linking devices support rather than mechanically decorate the text.

### Lexical Resource

Check range, precision, collocation, word formation, spelling and register.
Repeated vocabulary is evidence only when it causes noticeable limitation; do
not use a fixed repetition-count rule as an automatic score cap.

### Grammatical Range and Accuracy

Check sentence variety, control, error frequency, error severity and whether
errors impede communication. Complex structures that repeatedly break down do
not automatically improve the score.

## Required score format

```text
Estimated overall: 6.0–6.5
Confidence: Medium

Task Response: 6.0–6.5
Evidence supporting this range: ...
Evidence preventing a confident higher band: ...
```

Do not claim a universal “AI is always 0.5 high” correction. Calibration is
model- and prompt-dependent.

## Weighting and provenance

- Within one Writing task, TA/TR, CC, LR and GRA are equally weighted.
- In a complete Writing test, Task 2 carries twice the weight of Task 1.
- Do not apply the Task 2 weighting to a single standalone essay score.
- Record `rubric.publisher`, `rubric.standard`, `rubric.version` and
  `rubric.source_reference` in every numerically scored session.
- Mark every model result as `score_kind: ai_training_estimate` with confidence.
- Handle under-length, off-topic, note-form and copied responses only as
  described by the current official criteria; do not invent fixed caps.
