# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is an individual English learner studying on a personal
desktop computer. The first public release is designed for a single learner
rather than a classroom, school administrator or multi-user organisation.
The default learning track is general (daily / workplace) English; exam
preparation (IELTS, and later CET, postgraduate or TOEFL) is an optional
Domain Pack the learner can enable.

Windows is the primary packaged experience. The source installation and core
browser workflow must remain fully usable on macOS and Linux, with equivalent
learning functionality and a coherent interface on all three platforms.

## Product Purpose

言蹊 (Yanxi) is a local-first, Tutor-led English learning product for
discussing, planning, practising, reviewing and tracking English across
Listening, Reading, Writing and Speaking plus vocabulary and grammar. It
combines a bounded, tool-using Tutor Agent with a deterministic Learning Agent
Kernel, so learners can use their own materials and model connection without
making a model conversation the authority for scores, answers or learning
history. IELTS Academic remains the first exam Domain Pack on top of the
general English track.

Success means a learner can install the product, connect an optional model,
import material they are entitled to use, learn through teacher-like dialogue
with photos, documents or pasted English, retain a recoverable local learning
record and revise through spaced review without operating an Agent or
terminal during normal study.

## Positioning

The product is a bounded Tutor Agent on top of an authoritative Teaching
Runtime rather than a generic chat wrapper or a general autonomous Agent.
Versioned Capabilities, complete Skills, teaching integrity rules and output
contracts constrain every assisted teaching action. Candidate model output
must pass Schema and semantic validation before the Runtime may persist it.

The default public surface is the general English learning track, while the
internal longitudinal learning state is implemented by a reusable Learning
Agent Kernel. The general English Domain Pack owns the daily / workplace skill
graph and CEFR-aligned assessment scale; the IELTS Academic Domain Pack owns
the exam-specific skill graph, band scale, Capabilities and evidence mappings.
Exam packs are additions, not the default learner interface.

The product is also bring-your-own-content and bring-your-own-model. Public
builds start with an empty question bank, support multiple provider routes and
keep external CLI Agents optional and separate from the primary teaching
model.

## Operating Context

- The learner launches a packaged local application or the source-installed
  CLI, then studies in a browser UI served from a loopback-only FastAPI service.
- SQLite, Session projections, Corpus files and registered Media assets live in
  the learner's local data home and remain the sources of record.
- Deterministic browsing, editing, practice and history functions remain usable
  without a model connection. Assisted dialogue, explanation and evaluation
  use the learner's configured provider.
- Learners may import screenshots, PDFs, Word documents, text, Task 1 visuals
  and audio they are legally entitled to use. Imported content stays local
  unless the learner authorises the required remote-processing scope.
- Normal learning does not require Python, Node.js, Git, Docker, WSL or a CLI
  Agent on a clean Windows installation.

## Capabilities and Constraints

- The product covers Listening, Reading, Writing and Speaking, plus persistent
  teacher dialogue, Library and Content Studio workflows, evidence feedback,
  review queues, progress and local settings.
- Writing preserves the evidence-first V1/V2 learning loop. Reading preserves
  progressive hints and answer integrity. Speaking mocks do not correct the
  learner mid-mock. Listening keeps audio, transcript and answer evidence
  distinct.
- AI scores are cautious estimates with confidence and provenance, never
  official examiner scores.
- The Teaching Runtime owns privacy, revision checks, idempotency, validation
  and persistence. Models and external Agents cannot write authoritative
  learning records directly.
- Simple Tutor turns use one constrained model call. Material-, history- and
  planning-dependent turns may use at most three planning rounds and six
  allowlisted Runtime tool calls. Shell, arbitrary filesystem and direct SQL
  access are never exposed.
- Study Threads, versioned soft teaching state and Runtime-owned Teaching
  Cycles save locally. Learner memories are revisioned, expirable and excluded
  when contradictory. Errors, review tasks, memory proposals, material
  promotion and formal Practice actions require learner confirmation before
  the Runtime applies them.
- Revisioned objectives, learning activities, mastery evidence and spaced
  review schedules are stored by the generic learning kernel. Its estimates
  are derived from admitted evidence and never replace official-score
  provenance or IELTS-specific rules.
- Learners see this state as a plain-language teaching path, editable goals,
  skill evidence and teacher memory controls. Internal phase names, database
  keys and model reasoning remain outside the learning interface.
- Release evidence includes deterministic positive and negative teaching-policy
  controls in addition to output Schema checks and runtime reliability samples;
  evaluation history never retains the raw learner content used by a case.
- One primary Model Provider and optional fallbacks support ChatGPT login,
  OpenAI-compatible APIs and local compatible HTTP services. External CLI
  Agents are optional advanced tools, not teaching providers.
- SQLite remains the production database for the local single-user product.
  Docker, WSL, PostgreSQL, a vector database and a separate model API backend
  are not runtime requirements.
- Cloud sync, organisational accounts, payments, multi-user collaboration,
  public hosting and autonomous multi-Agent orchestration are outside the
  current product scope.
- Public distributions do not bundle Cambridge IELTS books, commercial course
  material, past papers, credentials or learner data.
- UI fonts, icons and visual assets must be bundled with the product or use
  reliable platform fallbacks. Normal interface rendering must not depend on a
  remote font service, CDN or third-party asset host.

## Brand Commitments

The product name is **言蹊 (Yanxi)**. It is an independent study product and
must not imply endorsement by IELTS, Cambridge University Press & Assessment,
the British Council, IDP Education or any examination board.

The experience should remain practical, academically credible and focused on
learning. It must not become a colourful language-learning game, a generic AI
dashboard, terminal cosplay or a model-and-Agent configuration showcase.
Visual references such as DeepTutor are evidence for proportion, typography,
spacing and interaction restraint, not branding or product taxonomy to copy.

## Evidence on Hand

- The implemented React/TypeScript/Vite UI, Python Teaching Runtime, local
  application service and packaged static assets in this repository.
- Authoritative architecture, product workflow, teaching-integrity, privacy,
  release and content-conformance documents under `docs/`.
- Project-original Skills, Schemas, contract fixtures, UI tests and packaged
  desktop smoke tests.
- No public user testimonials, official IELTS endorsement, licensed commercial
  question bank or redistributable Cambridge corpus may be fabricated or
  implied.

## Product Principles

1. **Teaching integrity before model fluency.** IELTS rules, evidence and
   learner revision order outrank a persuasive model response.
2. **Local authority and recoverability.** Formal learning state belongs to the
   Runtime and the learner's local data, not a browser tab or model history.
3. **Learning first, configuration second.** Normal surfaces show study work;
   providers, external Agents and diagnostics stay in Settings.
4. **Practical speed over decorative complexity.** Navigation, typing,
   streaming, long transcripts and large local libraries must remain smooth as
   data grows.
5. **Open connections without hidden lock-in.** Learners may choose a supported
   provider and import lawful material without changing the teaching contract.

## Accessibility & Inclusion

The desktop browser UI must support keyboard-only operation, visible focus,
semantic landmarks, reduced motion, meaningful non-colour state labels and
WCAG AA text contrast. Core workflows must remain usable at 200% zoom. Reading
passages, long teacher replies, Task 1 visuals and charts require accessible
text or structured alternatives where the source permits them.
