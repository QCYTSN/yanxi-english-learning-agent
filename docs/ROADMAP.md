# Roadmap

System completeness work after V0.7 is tracked authoritatively in
[SYSTEM_COMPLETENESS_PLAN.md](SYSTEM_COMPLETENESS_PLAN.md). Content inventory
targets remain in [CONTENT_ACQUISITION_PLAN.md](CONTENT_ACQUISITION_PLAN.md).

## Delivered through V1.2

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
- durable Agent lifecycle with queued/running/validating/persisting/persisted states, timeout, cancellation, retry, restart recovery and resumable SSE
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

## Post-1.2 increments

The detailed dependencies, deliverables and acceptance criteria live in the
system completeness plan. Version-level intent is:

Assisted PDF/audio structuring, richer analytics, optional local speech
evidence and the final visual system remain scheduled within or after those
increments as described in the authoritative plan.

## Deferred product version

Direct model API backends, authentication, cloud sync, multi-user accounts,
RAG, fine-tuning and autonomous multi-agent orchestration require a separate
scope decision. A desktop shell remains optional until the browser workflow has
enough real-study feedback.
