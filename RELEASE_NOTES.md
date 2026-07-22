# IELTS AI Coach v0.6.0

## Reliable study runtime and teaching contracts

### Added

- revisioned Writing and Reading runtime operations, active-Session resume and
  stale-update protection
- atomic Session document writes with rollback when SQLite recording fails
- validated `writing-review` and `reading-review` contracts that enforce the
  active-learning and answer-integrity rules
- official IELTS Writing/Speaking rubric registry with metadata, optional local
  file hashing and availability checks; official content is not bundled
- an enforced one-time privacy gate for remotely processing private sources
- optional metadata-only token, latency and tool-call telemetry
- compact criterion and Reading-type ability signals in module study context

### Fixed

- the context history window now limits error aggregation as stated instead of
  mixing all-time errors into a 14-day payload
- Session Markdown and SQLite no longer follow opposite write orders
- formal saved practice no longer requires an Agent to hand-edit frontmatter

### Migration

- database schema version 5 adds only new tables and preserves V0.1-V0.5 data
- normal `ielts-coach init` registers reference-only official rubric metadata;
  it does not download or redistribute the descriptor PDFs

---

# IELTS AI Coach v0.5.0

## Lightweight Agent runtime

### Changed

- clear Writing, Speaking, Reading, Progress and Corpus requests now bypass the
  generic router and begin in the specialist Skill
- specialist Skills skip global status checks when the learner already supplied
  the task material
- detailed references load only at the stage that needs them
- routine safe CLI work is not narrated to the learner
- a missing diagnostic baseline no longer blocks direct practice

### Added

- `ielts-coach study-context` for one compact cross-module planning payload
- `ielts-coach study-context --module <module>` for minimal personalised context
- regression tests that prevent global planning data from leaking into a narrow
  specialist preflight and limit Skill-body prompt growth

### Preserved

- official-descriptor requirements and score provenance
- active Writing revision before model alternatives
- Reading hint and answer integrity
- uninterrupted Speaking mocks and pronunciation evidence boundaries
- V0.1-V0.4 local data and database schema compatibility

---

# IELTS AI Coach v0.4.0

## Academic diagnostic and calibration foundation

### Added

- explicit IELTS Academic-only validation in Profile and onboarding
- strict Reading `timed-practice` Sessions with passage scope, timing metadata,
  zero-hint enforcement and data-layer answer locking before submission
- standard `quick` and `full` Academic diagnostic runs with requirement tracking
  and conservative baseline updates
- authorised calibration-case registry, blind scoring worksheets, input hashing,
  run import and MAE/tolerance reporting
- automatic router guidance for first-use diagnostics and intent-based specialist
  Skill activation

### Integrity

- General Training profiles are rejected instead of being silently routed into
  Academic Reading or Writing tasks
- diagnostic coverage no longer accepts arbitrary completed Sessions: it checks
  verified Listening evidence, timed Reading, required Writing tasks and all
  three Speaking parts
- active timed Reading Sessions block answer-bearing question views until the
  learner has submitted
- official calibration scores remain outside blind model worksheets

### Migration

- database schema version 4 adds timed Session fields, `diagnostic_runs` and
  `calibration_cases` without deleting V0.1-V0.3 user data

---

# IELTS AI Coach v0.3.0

## Scoring-integrity and workflow foundation

### Added

- persistent first-use onboarding state and a validated setup-file workflow
- explicit Session lifecycle states for future UI and cross-client orchestration
- score provenance: official result, verified answer-key estimate, AI training
  estimate, partial profile, and legacy/unspecified data
- database schema version metadata and backward-compatible migrations
- layered Speaking reports: source observations, source-model provisional
  estimate, and independent local IELTS-rubric evaluation

### Fixed

- Voice/Live provisional Speaking scores are no longer stored as the system's
  final Speaking band
- text-only Speaking review cannot invent Pronunciation or a four-criterion overall
- completed Speaking overall estimates are equally weighted across FC, LR, GRA
  and Pronunciation
- numeric Writing estimates require the official IELTS Writing Band Descriptors,
  the correct TA/TR criterion, four exact criteria, and consistent equal weighting
- Task 1 TA and Task 2 TR can no longer be mixed in one scored version
- unverified Reading answers are excluded from accuracy denominators rather than
  counted as wrong
- allocation and trend reports exclude partial profiles, low-confidence AI scores,
  and source-model criterion estimates
- UTF-8 and known-mojibake regression coverage was added for user-facing text

### Preserved

- V0.1/V0.2 data remains readable; legacy scores without provenance are retained
  as unspecified rather than silently reclassified
- six-Skill architecture, active Writing revision, progressive Reading hints,
  uninterrupted Speaking mocks, local-first data and BYOC boundaries

---

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
