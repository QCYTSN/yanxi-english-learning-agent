# Roadmap

## Delivered through V0.7

- six-Skill architecture
- independent Reading coach
- structured Corpus Manager and question search/draw
- question-level provenance and duplicate detection
- automatic Session start/finish workflow
- structured Writing versions and criterion scores
- structured Reading answers and type accuracy
- Speaking Voice-report import
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
- deterministic Writing and Reading browser workflows
- TextAnchor evidence linking and Task 1 Media Registry
- schema v6 draft, idempotency, media and Agent-run infrastructure
- MockAdapter and ManualAdapter with validated result persistence
- Today, Feedback, Library, History/Progress and Settings surfaces

## Next decision points

These are intentionally not implemented until user feedback from real study:

- better adapters for user-prepared private corpus formats
- richer time-on-question and Reading passage-level analytics
- optional local speech-to-text and acoustic evidence
- model-executed evaluation harness for Skill outputs
- local read-only Dashboard after sufficient real data exists
- verified OpenCode and Claude process adapters
- Speaking handoff and report-review UI
- final visual system and optional dark mode

## Deferred product version

Direct model API backends, authentication, cloud sync, multi-user accounts,
RAG, fine-tuning and autonomous multi-agent orchestration require a separate
scope decision. A desktop shell remains optional until the browser workflow has
enough real-study feedback.
