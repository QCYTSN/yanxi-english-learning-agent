# IELTS Content Conformance

This document is the engineering contract that prevents the UI from presenting
generic English exercises as complete IELTS practice.

## Two independent labels

Every item or pack has both:

- provenance: where it came from and whether it may be stored or redistributed;
- conformance: what kind of IELTS practice it can legitimately support.

`official_external`, `licensed_private`, `project_original`, `seasonal_reported`
and `synthetic` are source labels. They do not by themselves make a question a
verified IELTS item.

## Practice modes

| Mode | Meaning | May produce an IELTS Band? |
|---|---|---|
| `full_mock` | A complete module matching the pinned structure | Only when reviewed and verified |
| `section_practice` | A passage, part, Writing task or Speaking part/set | No |
| `question_type_drill` | Focused practice for an official question family | No |
| `skill_drill` | Supporting language work such as high-frequency listening expressions | No |

Conformance statuses are `verified`, `provisional`, `skill_only`, and
`rejected`. The UI must display both mode and status. It must never infer a Band
from a drill or an incomplete pack.

## Pinned full-module contracts

The runtime exposes the current profile at
`GET /api/v1/standards/ielts-academic` and `ielts-coach conformance standard`.

- Listening: four parts, ten questions per part, recording played once.
- Academic Reading: three passages, 40 questions, 60 minutes, total source-text
  length of 2,150-2,750 words.
- Academic Writing: Task 1 minimum 150 words, Task 2 minimum 250 words, 60
  minutes total, Task 2 weighted twice as much.
- Speaking: Parts 1, 2 and 3 in order, 11-14 minutes total, one minute Part 2
  preparation, and an explicit thematic link between Parts 2 and 3.

The source URLs are stored in `src/ielts_coach/conformance.py`. Updating the
profile requires a deliberate version change and regression tests.

## Question-level rules

Reading and Listening objective questions use a closed registry of IELTS
question families. Completion questions must declare a word limit. True/False/
Not Given and Yes/No/Not Given are not interchangeable. Multiple-choice and
matching tasks require option banks. Verified review quality should include an
evidence location.

Writing Task 1 requires a complete readable visual or structured data. Speaking
Part 2 stores cue points structurally, and every Part 3 item must link to a Part
2 topic set.

## Answer and scoring boundary

Reading and Listening keys are graded deterministically after submission.
Agents explain evidence and errors; they do not invent the answer key. Answers
remain hidden during active timed Reading. AI Writing and Speaking results stay
explicitly estimated and confidence-labelled.

## Importing owned or private material

The repository does not bundle Cambridge IELTS books, commercial course packs,
or copied third-party website banks. Legally obtained private content remains
outside the repository and is registered as `local_private` or an external
reference. Prepared passage/question/assessment-pack JSONL may be imported;
PDF/OCR conversion is a separate preprocessing workflow and must preserve page
and source references.

The local UI content workbench records raw files, hashes and processing status.
It also reports the gap between current verified content and the adjustable
inventory targets documented in `CONTENT_ACQUISITION_PLAN.md`. These planning
targets never override the IELTS structural contract.
