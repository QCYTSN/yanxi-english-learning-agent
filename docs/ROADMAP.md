# Roadmap

Historical completeness and content-inventory plans (V0.7 era) have been
retired with the General English pivot; current scope lives in
[00_PRODUCT_SCOPE.md](00_PRODUCT_SCOPE.md) and [PRODUCT.md](../PRODUCT.md).

## Delivered through the current local build

- six-Skill architecture
- independent Reading coach
- structured Corpus Manager and question search/draw
- question-level provenance and duplicate detection
- automatic Session start/finish workflow
- structured Writing versions and criterion scores
- structured Reading answers and type accuracy
- Speaking Voice/Live task-package handoff and report import
- strict Profile, Session, Question, Story, Corpus and Calibration schemas
- active/monitoring/resolved errors
- personal story-bank commands
- error, ability and behaviour profile
- allocation history and maximum-shift enforcement
- trend reports
- calibration-result framework
- Claude Code, Codex and OpenCode sync
- infrastructure and static Skill workflow tests
- first-use onboarding state and Session lifecycle foundation
- score provenance, confidence and official-rubric metadata
- independent local Speaking evaluation separated from Voice/Live provisional scores
- evidence-aware partial Speaking profiles and equal-weight score checks
- official-standard Writing task score validation
- verified-only Reading accuracy and provenance-aware planning
- IELTS Academic-only Profile and onboarding guard
- strict timed Reading with submission-before-answer enforcement
- standard quick/full Academic diagnostic runs
- blind authorised-sample calibration workflow with input hashing
- intent-first specialist routing without mandatory global preflight
- compact `study-context` payloads for module and cross-module turns
- stage-specific Skill reference loading and prompt-size regression guards
- revisioned Study Runtime, active-Session resume and stale-write protection
- atomic Session-file updates with database-failure rollback
- validated Writing/Reading teaching-output contracts
- official rubric registry with reference-only and local-hash modes
- enforced private-source remote-processing gate
- optional metadata-only cost and latency telemetry
- correctly bounded history errors and compact ability signals
- packaged loopback-only local learning UI
- deterministic Writing, Reading and high-frequency Listening browser workflows
- TextAnchor evidence linking and Task 1 Media Registry
- schema v12 drafts, idempotency, media, auditable content reviews, content imports, Listening corpus, Agent-run and AssessmentRun infrastructure
- MockAdapter and ManualAdapter with validated result persistence
- Today, four-module Practice, Feedback, Library, History/Progress and Settings surfaces
- Speaking Voice/Live handoff, transcript/structured-report review and Story Bank UI
- 10-category, 50-item original high-frequency Listening drill with spaced review state
- single-instance background UI launcher and Windows desktop shortcut
- IELTS Academic content-contract registry and schema-v8 assessment packs
- explicit full-mock, section, question-type and skill-drill classification
- deterministic Reading answer-key scoring after submission
- IELTS-aware Reading controls, Writing task limits and linked Speaking sets
- schema-v9 local content inbox with hashed PDF, image, audio and structured-file records
- four-module content readiness matrix with minimum/recommended inventory gaps
- browser content workbench for raw staging and validated manifest/JSONL import
- browser assessment-pack assembly and structural review gate
- verifiable backup archives, pre-migration snapshots, cross-home restore and post-restore consistency audit
- Agent/model identity and capability provenance with explicit unknown-state handling
- browser onboarding, editable Profile, quick/full Diagnostic and Settings health surfaces
- shared frozen-snapshot AssessmentRun, SectionRun and revisioned QuestionResponse model
- full Academic Reading runner with three passages, 40 questions, 60-minute server clock and post-submit answer evidence
- full Academic Writing runner with recoverable Task 1/Task 2 responses and Runtime-owned 1:2 score aggregation
- Audio Media Registry and full four-part Listening runner with persistent one-play state
- Speaking Part 1-3 external Voice/Live handoff and result binding on one authoritative AssessmentRun/Session
- one authoritative ScoreResult admission policy across reports, allocation and Progress
- seven versioned Agent result contracts with schemas, semantic checks and golden/failure fixtures
- durable Agent lifecycle with queued/running/validating/persisting/persisted states, expiring worker leases, checkpoints, timeout, cancellation, retry, no-repeat post-result recovery and resumable SSE
- capability-probed Claude Code and OpenCode local process adapters with explicit consent and no shell execution
- Runtime-driven Today 70/30 plan with target gaps, content readiness and fallback practice
- structured four-module Progress dashboard with eligible trends and separately labelled training observations
- schema v14 media bindings, performance indexes, coaching artifacts and recoverable Agent execution metadata
- Windows/Linux and Python 3.10-3.12 CI matrix, frontend quality gates, E2E and wheel smoke install
- `writing-mock-review@1` with separate Task 1/Task 2 evidence and Runtime-owned 1:2 aggregation
- controlled Task 1 image packages for OpenCode and Manual without exposing original media paths
- short-lived, renewable Listening playback leases that support HTTP Range requests without counting extra plays
- external Speaking source evidence followed by local Agent re-evaluation on the same AssessmentRun
- schema v15 audio-lease persistence and restart-safe enforcement
- schema v16 first-class PracticeUnit and ReviewTask persistence
- idempotent Today materialisation with Diagnostic, Practice and Review bindings
- unified review queue for active errors, due Listening expressions, Writing V2 and Reading wrong answers
- recoverable page-level rendering boundary and backward-compatible Settings diagnostics
- schema v17 structured weekly-report persistence and evidence-bounded trend summaries
- real four-module trend charts with trusted-score and training-observation separation
- executable Progress next actions backed by idempotent PracticeUnit materialisation
- weekly evidence summary, error inbox and report archive in the local UI
- schema v20 Capability Registry, Study Threads and versioned inference provenance
- schema v21 validation-aware Provider Attempts with structured, domain and
  media-capability fallback plus restart-safe audit closure
- schema v22 durable Agent checkpoints, atomic worker leases, periodic
  heartbeats and post-result recovery without a duplicate model call
- schema v23 one-run privacy decision receipts plus revision-and-hash guarded
  Session Markdown/SQLite projections with explicit reconciliation
- schema v24 canonical Agent lifecycle events, privacy-safe append-only audit
  facts, expiring launch tokens and session-bound CSRF protection
- schema v25 allowlisted Tutor domain queries, learner-managed soft memories,
  bounded long-thread summaries and local learning-history retrieval
- schema v26 privacy-safe capability evaluation history, Provider reliability
  reporting and a combined contract plus 10k/100k release gate
- schema v27 versioned Tutor thread state, confirmation-gated proposals and
  idempotent Tutor turn commits
- schema v28 Study Thread inference links, compacted terminal request envelopes
  and lifecycle-safe conversation deletion
- schema v29 durable background jobs plus SQLite FTS5 learning-history search
- schema v30 persistent Provider health, retry and circuit-breaker state
- schema v31 Learning Agent Kernel with track-aware objectives, activities,
  mastery evidence, deterministic skill state and review schedules
- IELTS Academic Domain Pack with four dimensions, 21 skill nodes, existing
  Capability contracts and deterministic Session evidence projection
- schema v32 revisioned and expirable learner memory, duplicate suppression,
  explicit contradiction resolution and bounded effective-memory retrieval
- Runtime-owned Teaching Cycles with optimistic revision checks, append-only
  events and deterministic next-phase recommendations
- privacy-safe teaching-quality regression across instructional fit, answer
  integrity, grounding, active learning, memory continuity, pedagogy authority
  and recovery, integrated into the release gate
- first-class Model Providers with one primary and optional ordered fallbacks
- complete Skill Envelope compilation from `skills-source`
- encrypted credential storage outside SQLite
- OpenAI-compatible API and local HTTP model support with domestic presets
- External Agent isolation: CLI and Manual tools are not teaching providers
- official Codex app-server JSONL integration with isolated auth, model discovery,
  structured output, registered media and cancellation
- user-triggered installation of a pinned official Codex runtime, OpenAI/ChatGPT
  browser login, device-code fallback and in-product model selection
- onboarding AI choice and a separate Models settings section
- learning-only Today launcher with deterministic intent routing
- explicit local SQLite decision with Docker/WSL reserved for optional workers or CI
- learner-facing Library separated from the local Content Studio
- persistent, retryable PDF preparation with protected preview, page-level text
  summaries, OCR-needed detection and page-role planning
- isolated OCR and review-draft conversion, local audio waveform/Transcript
  review, streaming uploads, storage quotas and restart-safe batch work
- bounded Context Engine assembly with source trace, omission reporting and
  deterministic request fingerprints
- content-free support bundles, secure credential backends and isolated Agent
  worker processes
- real Chromium packaged-app smoke tests with one-time launch-token bootstrap
- dynamic wheel smoke installation and separated compatibility/full-regression CI

## Next increments

The detailed dependencies, deliverables and acceptance criteria live in the
system completeness plan.

Delivered in the current content-engineering increment:

- isolated, user-installed local OCR with real page processing;
- page-role conversion into review-only Passage, Question, Answer Key,
  transcript and task-visual drafts;
- local audio waveform, Transcript and timestamp review;
- batch preparation/draft/import actions, confirmed failed-import deletion and
  a visible 10 GiB inbox quota;
- an executable 10k Session / 100k Question synthetic benchmark, including a
  constant-memory random-draw path.

The remaining sequence is:

1. import and human-review enough user-owned or redistributable four-module
   material for the learner's own readiness targets;
2. exercise the implemented visual system and complete learning workflows with
   real material, then resolve the resulting accessibility, performance and
   interaction findings. `DESIGN.md` is the current visual authority.
3. the General English track (track_id `general-english`) is now the default
   product surface with its own curriculum, Skills, contracts and evaluation
   set; the remaining sequence below assumes the conversation-first English
   learning agent positioning (product name 言蹊 / Yanxi).

## Deferred product decisions

Cloud sync, multi-user accounts, RAG, fine-tuning, autonomous multi-agent
orchestration and a service database require separate scope decisions. Codex
managed-runtime authentication, OpenAI-compatible APIs and local HTTP models
are implemented. A desktop shell remains optional until the browser workflow
has enough real-study feedback.
