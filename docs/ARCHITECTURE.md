# Architecture

The CLI/Skill surface and browser application are two clients of the same
authoritative IELTS Runtime:

```text
Terminal Agent -> Skill -> ielts-coach CLI ------┐
                                                 ├-> IELTS Runtime -> local data
Browser UI -> Capability -> Inference Broker ----┘
```

The primary learning experience now has two coordinated engines:

```text
Conversation Runtime -> bounded Tutor Agent -> allowlisted IELTS tools
Formal Teaching Runtime -> deterministic Practice / Assessment / Review
```

The conversation engine owns Study Threads, soft cross-turn teaching state and
confirmation-gated proposals. It cannot mutate formal Session state. See
[`TUTOR_AGENT_ARCHITECTURE.md`](TUTOR_AGENT_ARCHITECTURE.md).

Provider/runtime details and the Codex managed-runtime boundary are defined in
[`ARCHITECTURE_V2.md`](ARCHITECTURE_V2.md).

## Skill layer

`skills-source/` is the single source of truth. `sync-skills` copies all six
Skills to:

```text
.claude/skills/
.agents/skills/
.opencode/skills/
```

Each Skill uses a short `SKILL.md` and detailed `references/` policies.

## Lightweight runtime contract

Specialist requests bypass the router. If the learner already supplied the
material needed for an explanation or review, the specialist starts teaching
without reading global history. When personalisation is useful, one command
returns a compact module-specific payload:

```text
ielts-coach study-context --module writing
```

Generic planning uses `ielts-coach study-context` once. It replaces the former
sequence of separate onboarding, summary, allocation, learning-profile and
diagnostic calls. Detailed references are loaded only at the stage that needs
them; for example, a Writing scoring policy is not loaded during simple question
analysis.

```text
clear specialist intent -> specialist -> optional compact context -> teaching
generic/ambiguous intent -> router -> one compact context -> route or plan
```

## Data layer

Core tables:

```text
sessions, errors, corpora
question_passages, questions, question_options, question_attempts
reading_answers, writing_versions, criterion_scores, speaking_reports
allocation_history, calibration_results, schema_meta
rubric_registry, runtime_events, runtime_telemetry
tutor_thread_states, tutor_proposals, tutor_turn_commits
```

Markdown/YAML remains the human-readable interchange format. The revisioned
Study Runtime validates learner submissions and feedback, writes the Session
document atomically, then updates SQLite; a failed database update rolls the
file back. `session resume` reconciles stale mirrors by validated revision.

Writing and Reading feedback have separate JSON Schemas plus semantic checks.
They prevent first-review model-answer leakage, enforce four official Writing
criteria, protect guided hints, and require passage-grounded wrong-answer
evidence before a formal review is saved.

Scores carry provenance, confidence and rubric metadata. Planning excludes
partial profiles, low-confidence AI estimates and source-model provisional
scores.

Official rubric files are not bundled. The registry stores the official source
reference, declared version and optional user-owned local file hash so the
runtime can distinguish a valid reference from a missing local file.

## Speaking evidence pipeline

```text
Voice / Live conversation
  -> source observations and optional provisional estimate
  -> local Agent applies official IELTS Speaking descriptors
  -> partial FC/LR/GRA profile, or four-criterion estimate when PRON evidence exists
  -> SQLite archive and progress analysis
```

## Learning memory

- Error layer: stable tags and active/monitoring/resolved state
- Ability layer: module averages, Writing/Speaking criteria and Reading accuracy
- Behaviour layer: session count, active days, duration, inactivity and subject mix

## Corpus layer

The structured importer accepts a manifest plus JSONL passages/questions. Raw
private files may stay at an external local path. Question selection supports
module, task, type, topic, source, corpus and completed-question exclusion.

## Calibration boundary

The system stores official/reference scores and model predictions supplied by
the user, then reports absolute error. It does not bundle official calibration
content and does not run a hidden model API. Any managed runtime or external
Agent connection is explicit, attributable and selected through an Execution
Profile.
