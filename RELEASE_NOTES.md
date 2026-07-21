# IELTS AI Coach v0.2.1

## Maintenance release

### Fixed

- safely upgrades the bundled V0.1 Starter Manifest and indexes all 41 V0.2 questions without `init --force`
- makes `doctor` fail on a stale package, stale Skill copy, incomplete database, or missing Starter index
- rejects cross-corpus question/passage ID collisions and mismatched item provenance
- separates Writing and Speaking criterion analytics
- makes saved allocation recommendations idempotent within an ISO-week planning period
- rejects empty completed Sessions and inconsistent score ranges
- excludes resolved errors from active learning profiles and summaries
- recursively hides answer metadata in learner-facing question output
- records the actual tolerance used by calibration reports
- applies configured database filename, weekly report window, and question draw limit

### Upgrade safety

Normal `ielts-coach init` refreshes only the project-owned Starter Corpus and
merges new configuration defaults into existing files. It does not replace
user targets, private corpora, Sessions, stories, or calibration records.

## Major upgrade

V0.2 completes the agreed six-module learning core.

### Added

- `ielts-reading` with guided solving, wrong-answer review, type drills, close
  reading and context analysis
- `ielts-corpus` with structured imports, search, draw, show, reindex, stats,
  provenance and duplicate detection
- 4 original Reading passages and 16 original Reading questions
- structured question/passages/options/attempts tables
- Writing versions and criterion scores
- Reading answer, evidence, time and error storage
- Speaking Voice-report import
- Session start/finish/show/list
- error status commands, personal story-bank commands and learning profiles
- trend reports, allocation history and enhanced controlled allocation
- calibration record/report framework
- OpenCode Skill synchronisation
- strict schema validation and expanded workflow tests

### Preserved

- active-learning Writing sequence
- uninterrupted Speaking mocks
- 70/30 score strategy with dynamic adjustment
- local-first BYOC and copyright boundaries

### Still deferred

Frontend, model API backend, automatic audio analysis, RAG, fine-tuning,
multi-user cloud features and copyrighted question distribution.
