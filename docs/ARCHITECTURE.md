# Architecture

```text
User
  ↓
Claude Code / Codex / OpenCode
  ↓ loads one of six Skills
Skill workflow
  ↓ invokes
ielts-coach CLI
  ↓ reads/writes
SQLite + local Markdown/YAML + user-owned corpus files
```

## Skill layer

`skills-source/` is the single source of truth. `sync-skills` copies all six
Skills to:

```text
.claude/skills/
.agents/skills/
.opencode/skills/
```

Each Skill uses a short `SKILL.md` and detailed `references/` policies.

## Data layer

Core tables:

```text
sessions, errors, corpora
question_passages, questions, question_options, question_attempts
reading_answers, writing_versions, criterion_scores, speaking_reports
allocation_history, calibration_results, schema_meta
```

Markdown/YAML remains the human-editable session interchange format. SQLite is
the reporting and query source.

Scores carry provenance, confidence and rubric metadata. Planning excludes
partial profiles, low-confidence AI estimates and source-model provisional
scores.

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
content and does not run a hidden model API.
