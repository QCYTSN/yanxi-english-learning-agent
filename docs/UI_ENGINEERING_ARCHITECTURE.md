# UI engineering architecture

Status: current implementation authority for the local learning UI.

This document is authoritative for process, data and integration boundaries.
The current visual direction is a quiet academic study desk. The interaction
and information architecture are implemented; visual refinement may continue
without changing the contracts in this document.

The UI is a complete local learning surface for Writing, Reading, Listening and
Speaking. It includes deterministic navigation, evidence feedback,
history/progress, Media Registry, TextAnchor, structured assessment runners and
an external Voice/Live Speaking handoff. The browser never parses terminal
presentation text.

The provider/runtime decision is authoritative in
[`ARCHITECTURE_V2.md`](ARCHITECTURE_V2.md). The UI now requests versioned
Capabilities through the Teaching Runtime. Core learning uses an active Model
Provider route. Claude Code, OpenCode, Codex CLI and Manual handoff are isolated
under Advanced settings and cannot become teaching providers.

## 0. Current information architecture

The persistent shell intentionally exposes only four learning destinations:

```text
Today / Practice / Library / Progress
```

Settings is isolated at the bottom of the navigation. Normal learning pages do
not display provider diagnostics, CLI paths or configuration controls.

`Library` is learner-facing: it contains only material discovery, pack
selection and entry into practice. Raw uploads, readiness checks, human review
and import operations live in the separate `/content-studio` route. Content
Studio is reached through the Library management action and is deliberately not
a fifth primary learning destination.

Today combines deterministic learning entry with a focused material question:

```text
four module shortcuts
-> deterministic Runtime route
-> resume one active activity or start one recommended task

uploaded material plus a question
-> persistent Study Thread
-> validated IELTS teacher response
-> optional promotion into Content Studio
```

The Study Thread is not a general assistant or a formal practice Session. It
keeps its own messages and attachments, uses the fixed IELTS teacher policy,
and does not create score history. Model tokens are not used to interpret clear
navigation requests. Connection configuration lives under Settings, and
onboarding offers ChatGPT login, a custom OpenAI-compatible API, or "configure
later".

## 1. Engineering objective

Build a local study application that:

- removes terminal interaction from normal IELTS practice;
- reuses the existing Python Study Runtime and SQLite data;
- supports images, long-form editing, Reading split views and reports;
- does not duplicate IELTS rules in frontend code;
- can connect to multiple Agent implementations through adapters;
- remains usable in a limited manual mode when no callable Agent exists;
- keeps model/runtime connection details behind the Inference Broker.

The frontend is not a second IELTS system. It is a client of the current
system.

## 2. Four-layer architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ Browser UI                                                  │
│ display, input, local editor state, accessibility           │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + Server-Sent Events
┌──────────────────────────▼──────────────────────────────────┐
│ Local Application Service                                  │
│ API, launch token, orchestration, media, job state          │
└───────────────┬──────────────────────────┬──────────────────┘
                │ Python calls             │ Capability / Broker
┌───────────────▼─────────────────┐  ┌─────▼──────────────────┐
│ Existing IELTS Core             │  │ Inference Broker       │
│ Runtime, validation, corpus,    │  │ Codex/CLI/manual/mock  │
│ privacy, rubric, progress       │  │ execution profiles     │
└───────────────┬─────────────────┘  └────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│ Local persistence                                          │
│ SQLite, Session Markdown, registered corpus/media files    │
└─────────────────────────────────────────────────────────────┘
```

Dependency direction is one way:

```text
UI -> Application Service -> IELTS Core
                       \----> Inference Broker
Inference Broker -----validated output------> IELTS Core
```

The IELTS Core never imports React concerns or vendor-specific Agent code.

## 3. Process model

Recommended everyday command:

```powershell
ielts-coach ui open
```

It starts one local Python process that:

1. binds to `127.0.0.1` on an available port;
2. creates a random launch token;
3. serves the compiled frontend assets;
4. exposes the deterministic local API;
5. owns the lightweight supervisors that launch disposable Agent and content
   worker processes;
6. reuses the healthy single instance or starts it in the background;
7. opens a browser unless `--no-open` is supplied;
8. shuts down after `ielts-coach ui stop`.

The browser never launches Agent executables directly. The local Python process
does so through an approved adapter.

The UI may be launched in three ways:

- directly from PowerShell: `ielts-coach ui open`;
- from the Windows desktop shortcut installed by `ielts-coach ui shortcut-install`;
- by a terminal Agent after “启动雅思界面”;
- by a desktop Agent that can execute the same local command.

Launching the page and controlling an Agent are separate capabilities. A
desktop Agent may be able to launch the page without offering a callable
conversation interface to the page.

## 4. Technology recommendation

### Frontend

- React + TypeScript;
- Vite, because this is a local SPA and does not need SSR or server components;
- TanStack Query for server state and request invalidation;
- React Router for local routes;
- local component state for editors and in-progress form input;
- no global state library until an actual cross-page state need appears;
- Playwright for end-to-end flows;
- Vitest + Testing Library for component and accessibility behaviour.

### Local application service

- FastAPI, added as an optional `ui` dependency so the CLI core stays light;
- Uvicorn bound to localhost;
- Pydantic request/response models derived from, but not replacing, existing
  JSON Schemas;
- Server-Sent Events for one-way Agent progress streaming;
- ordinary HTTP POST for user actions and cancellation;
- no WebSocket in the first version.

### Study Thread and content workbench boundary

User-supplied screenshots, clipboard images, PDFs, Word documents and text files
first belong to a local Study Thread. Images are registered through Media
Registry; documents are stored under the thread attachment directory. A
versioned Context Engine compiles bounded recent conversation, rolling summary,
learning state, relevant local-history matches and current-message attachments
for each model request. Its trace records source IDs, omissions and a
fingerprint. The browser chat history is never the data source.

Only an explicit "整理成练习" action copies thread attachments into the content
inbox. The resulting import is prepared in the background and remains
unreviewed until OCR, page roles, question structure and local review are
complete.

Raw PDF, image and audio uploads are streamed into a bounded staging directory
and copied only into
`IELTS_HOME/corpus/inbox/<import_id>` and recorded with a hash. PDF preparation
is a persisted background job: it records page count and metadata, extracts a
short page text preview when possible, marks image-only pages as OCR-required,
and lets a reviewer assign page roles. OCR, content preparation and review-draft
generation run through the durable local background queue in isolated child
processes. The original file is served only through
an authenticated import-specific route. Preparation never claims the pages are
questions and never indexes them automatically.

A prepared `manifest.yaml` plus referenced JSONL can still be validated and
indexed. Indexed questions can then be selected into an Assessment Pack; the
Runtime derives its structure, and a reviewed full pack is blocked until all
referenced items are independently verified. OCR execution and page-plan to
question-draft conversion are explicit, isolated review stages rather than
automatic publication. Screenshots are treated as one-page documents and can
use the same local OCR and page-role review flow.

### Packaging

Development:

```text
Vite dev server -> FastAPI proxy -> IELTS Core
```

Release:

```text
Vite build -> packaged static assets -> FastAPI serves same-origin files
```

Tauri/Electron is deferred. The browser version must first prove the workflow.

## 5. Implemented repository layout

Do not move current Python modules during frontend introduction.

```text
ielts-ai-coach/
├─ frontend/
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ src/
│  │  ├─ api/             # typed HTTP client and event stream
│  │  ├─ components/      # shell and shared UI
│  │  ├─ pages/           # route-level Today/Practice/Feedback/etc.
│  │  └─ test/
│  └─ e2e/
│
└─ src/ielts_coach/
   ├─ web/
   │  ├─ auth.py          # launch token / origin checks
   │  ├─ app.py           # thin versioned HTTP routes and orchestration
   │  ├─ models.py        # request/response models
   │  ├─ server.py        # single-instance loopback service and browser launch
   │  ├─ background.py    # detached process entry point
   │  └─ shortcut.py      # Windows .lnk installation
   ├─ agent_gateway/
   │  ├─ base.py          # AgentAdapter protocol
   │  ├─ registry.py
   │  ├─ manual.py
   │  └─ mock.py
   ├─ media.py            # registered media only
   ├─ uploads.py          # bounded streaming upload staging
   ├─ background_jobs.py  # durable local heavy-job queue
   ├─ local_worker.py     # disposable Agent/OCR worker entry point
   ├─ context_engine.py   # deterministic Tutor context budgets and trace
   ├─ data_lifecycle.py   # deletion, media GC and privacy maintenance
   ├─ support_diagnostics.py # content-free support bundle
   ├─ text_anchor.py      # exact evidence locations
   ├─ locking.py          # cross-process Session locks
   └─ existing Core modules remain authoritative
```

API routers are thin. They call application services, which call existing Core
functions. A route must not reimplement scoring, state transitions, privacy or
corpus rules.

## 6. Agent compatibility model

### 6.1 What can be universal

The system can standardise:

- the input envelope;
- capability discovery;
- privacy decisions;
- required Skill/action;
- output schemas;
- progress/cancellation event types;
- Session persistence;
- error recovery.

### 6.2 What cannot be universal automatically

The system cannot assume every Agent supports:

- non-interactive invocation;
- conversation resume;
- streaming JSON;
- image input;
- tool permission control;
- cancellation;
- being awakened by a browser event.

An unknown Agent works only after an adapter implements the contract, or through
manual request/response exchange.

### 6.3 Adapter interface

Target protocol for callable process adapters:

```python
class AgentAdapter(Protocol):
    id: str

    def probe(self) -> AgentCapabilities: ...
    async def start(self, request: AgentRequest) -> AgentRunHandle: ...
    async def stream(self, handle: AgentRunHandle) -> AsyncIterator[AgentEvent]: ...
    async def cancel(self, handle: AgentRunHandle) -> None: ...
    async def resume(self, agent_session_id: str, request: AgentRequest) -> AgentRunHandle: ...
```

V0.7 deliberately implements the smaller synchronous `probe()` + `run()`
subset for MockAdapter and ManualAdapter. Run state, cancellation and SSE are
owned by the application service. A real process adapter must implement the
full lifecycle above before it is registered; the UI does not shell out to an
unverified executable.

Capability model:

```json
{
  "structured_output": true,
  "streaming": true,
  "session_resume": true,
  "image_input": false,
  "audio_input": false,
  "tool_execution": true,
  "remote_processing": true
}
```

The UI renders capabilities and disables unsupported actions. It never infers
support from the Agent brand alone.

### 6.4 Initial adapter order

1. `MockAdapter` for deterministic engineering and UI tests;
2. `ManualAdapter` as the universal fallback;
3. OpenCode adapter, because the installed client exposes `run`, `serve`,
   continuation and ACP;
4. Claude CLI adapter, because the installed client exposes non-interactive
   print, stream JSON, JSON Schema and resume;
5. Codex native adapter only after a callable local interface is verified.

Codex desktop remains useful in tool-hosted mode: it can start the UI and call
the Runtime. This is not yet the same as the UI invoking the current Codex task.

## 7. Request lifecycle

Every AI-assisted action follows this sequence:

```text
1. UI sends learner action
2. Application Service resolves or creates Study Session
3. Core checks expected revision
4. Application Service selects action and output contract
5. Core resolves provenance and privacy requirement
6. UI obtains one-time consent if required
7. Context Builder creates minimum referenced payload
8. Agent Gateway invokes selected adapter
9. UI receives status events only, not hidden reasoning
10. Adapter returns structured output
11. Core validates JSON Schema + semantic rules
12. Core persists Session atomically
13. UI fetches canonical Session and renders it
```

The frontend does not tell the model how IELTS scoring works. It supplies the
requested action and contract; the specialist Skill provides teaching policy.

## 8. Routing logic

Explicit UI actions never need model-based routing:

| UI action | Skill/action |
|---|---|
| Start Writing Task 2 | `ielts-writing / timed-practice` |
| Submit Writing V1 | runtime save, then `ielts-writing / first-review` |
| Submit Writing V2 | runtime save, then `ielts-writing / version-comparison` |
| Request Reading hint | `ielts-reading / guided-solving` |
| Submit Reading answers | runtime save, then `ielts-reading / wrong-answer-review` |
| Start Speaking mock | `ielts-speaking / full-mock` |
| Import Voice report | `ielts-speaking / transcript-review` |
| Draw a question | deterministic corpus service |
| View progress | deterministic progress service |

Only a genuinely free-form home request is sent through the `ielts` router.
This reduces token use and prevents every click from invoking a general Agent.

## 9. First-use logic

First page load calls one endpoint:

```text
GET /api/bootstrap
```

Response contains:

- app/core version;
- onboarding state;
- Academic profile summary;
- active Session summary;
- database/rubric health;
- configured Agent adapters and capabilities;
- no full history or corpus content.

If onboarding is pending, deterministic forms collect goals and preferences.
An Agent is not needed to save onboarding. A missing baseline offers diagnostic
or direct practice; it does not block the UI.

## 10. Session lifecycle and concurrency

The UI maps directly to existing states:

```text
draft
-> question_presented
-> learner_working
-> awaiting_feedback
-> awaiting_revision
-> completed
```

Rules:

- all mutations include `expected_revision`;
- HTTP conflict returns `409` plus canonical revision;
- frontend keeps unsaved editor text until conflict resolution;
- one active Agent run per Study Session/action;
- duplicate POST requests use idempotency keys;
- refresh retrieves run and Session state from the server;
- completed/cancelled Sessions cannot be mutated;
- Agent cancellation does not delete learner work.

## 11. Agent run state machine

```text
queued
-> preparing_context
-> awaiting_consent (optional)
-> running
-> validating
-> persisted

terminal alternatives:
cancelled | failed | invalid_output
```

Status events exposed to the UI:

```json
{"type":"status","stage":"running","label":"reviewing_response"}
{"type":"usage","input_tokens":1200,"output_tokens":350,"tool_calls":2}
{"type":"completed","session_id":"W-...","revision":3}
```

Never expose chain-of-thought, raw terminal output or provider secrets. Optional
usage metadata is stored through the existing metadata-only telemetry table.

## 12. Persistence changes required for UI phases

Schema v12 is implemented as a backward-compatible migration over the existing
learning-data base. It adds UI/adapter infrastructure only:

### `agent_runs`

```text
run_id, study_session_id, adapter_id, agent_session_id,
action, output_contract, status, error_code,
created_at, started_at, completed_at, usage_json
```

Do not store raw prompts or private corpus content by default.

### `agent_run_events`

Store short status and recovery metadata. Raw token streams are transient.

### `media_assets`

```text
media_id, owner_type, owner_id, media_type, mime_type,
local_path, content_hash, width, height, alt_text, metadata_json
```

Task 1 images remain files, not SQLite blobs. `local_path` is never returned to
the browser.

### `ui_settings`

Only application preferences such as last adapter, panel size and timer
visibility. IELTS profile and privacy defaults stay in existing configuration.

V0.7 also adds `study_drafts` for autosave revision checks and
`idempotency_records` for duplicate write protection. Formal Session content
remains canonical in Session Markdown plus SQLite indexes.

### `listening_items`

Stores project-original high-frequency expressions, category, Chinese meaning,
priority and structured training metadata. Attempts are not duplicated here:
they remain canonical Session question-attempt rows and reference an `item_id`
inside the validated attempt payload.

Every database change requires a backward-compatible migration and migration
test from v1 through the current version.

## 13. Evidence anchoring requirement

The current review schemas contain evidence text but not a stable UI location.
Before evidence-linked UI is integrated, add a reusable `TextAnchor`:

```json
{
  "document_kind": "writing_version",
  "document_id": "W-...:v1",
  "quote": "exact learner text",
  "start": 128,
  "end": 173,
  "occurrence": 1,
  "document_hash": "sha256"
}
```

Reading anchors use passage ID, paragraph label and offsets. Validation checks
the document hash and exact quoted text. If offsets become stale, the server may
attempt exact quote recovery; it must mark ambiguous anchors instead of linking
the wrong sentence.

This is an engineering prerequisite for precise evidence navigation, independent
of final visual style.

## 14. Task 1 image pipeline

Required flow:

```text
user/importer registers image
-> validate file type and size
-> calculate hash and dimensions
-> create media_id
-> question/session stores media_id
-> browser requests /api/media/{media_id}
-> service verifies token and allowed root
-> stream image with correct MIME and cache headers
```

Requirements:

- PNG, JPEG and WebP only in V0.7;
- SVG is deferred until a sanitisation policy is implemented;
- file-size and pixel-dimension limits;
- no arbitrary path query parameters;
- original file is never modified;
- optional structured data table is a separate asset;
- Agent adapter receives the image only when `image_input=true` and privacy
  allows the selected processing route;
- without reliable image access, numeric Task 1 scoring is disabled.

## 15. Local API surface

### Bootstrap and health

```text
GET /api/health
POST /api/auth/exchange
GET /api/v1/bootstrap
```

### Sessions

```text
GET  /api/v1/sessions?status=&module=
POST /api/v1/sessions
GET  /api/v1/sessions/{id}
POST /api/v1/sessions/{id}/transition
POST /api/v1/sessions/{id}/finish
GET  /api/v1/sessions/{id}/draft/{kind}
PUT  /api/v1/sessions/{id}/draft
```

### Writing and Reading runtime

```text
POST /api/v1/writing/{id}/versions
POST /api/v1/reading/{id}/hints
POST /api/v1/reading/{id}/answers
```

### Listening and Speaking

```text
GET  /api/v1/listening/categories
GET  /api/v1/listening/items
POST /api/v1/listening/{id}/attempts
GET  /api/v1/speaking/questions
POST /api/v1/speaking/handoffs
POST /api/v1/speaking/{id}/reports
GET  /api/v1/speaking/stories
POST /api/v1/speaking/stories
```

### Corpus and media

```text
GET  /api/v1/questions
GET  /api/v1/questions/{id}
GET  /api/v1/passages/{id}
POST /api/v1/media
GET  /api/v1/media
GET  /api/v1/media/{media_id}/content
```

Answer-bearing data uses a separate authorised endpoint and existing Reading
submission lock. A generic `with_answer=true` browser query is not accepted.

### Progress

```text
GET /api/v1/progress/summary
GET /api/v1/progress/trends
GET /api/v1/progress/errors
GET /api/v1/progress/allocation
```

### Agents

```text
GET  /api/v1/agents
POST /api/v1/agent-runs
POST /api/v1/agent-runs/{run_id}/import
GET  /api/v1/agent-runs/{run_id}
GET  /api/v1/agent-runs/{run_id}/events
POST /api/v1/agent-runs/{run_id}/cancel
```

## 16. Security model

- bind to loopback only unless a later explicit product decision changes it;
- random bearer/launch token stored in memory;
- strict same-origin and Origin validation;
- no wildcard CORS;
- do not place token in persistent browser storage;
- registered media instead of arbitrary file paths;
- allowlisted Agent executables and fixed argument construction;
- no shell string interpolation;
- child-process timeout, output-size limit and cancellation;
- redact secrets and raw private content from logs;
- privacy check immediately before private content resolution;
- one-time consent belongs to one Agent run and is not persisted;
- no direct database file download;
- content security policy for packaged UI.

## 17. Error contract

Every API error has a stable code:

```json
{
  "error": {
    "code": "SESSION_REVISION_CONFLICT",
    "message": "The Session changed in another client.",
    "recoverable": true,
    "details": {"expected": 2, "current": 3}
  }
}
```

Initial codes:

```text
SESSION_NOT_FOUND
SESSION_REVISION_CONFLICT
INVALID_SESSION_TRANSITION
ANSWER_REVEAL_LOCKED
OUTPUT_CONTRACT_INVALID
RUBRIC_UNAVAILABLE
PRIVATE_PROCESSING_BLOCKED
AGENT_UNAVAILABLE
AGENT_CAPABILITY_MISSING
AGENT_RUN_CANCELLED
MEDIA_NOT_FOUND
MEDIA_UNSUPPORTED
DATABASE_WRITE_FAILED
```

Frontend copy may translate these codes, but business decisions stay on the
server.

## 18. Testing strategy

### Core regression

Existing Python tests stay unchanged and green.

### Application API

- FastAPI route tests with temporary IELTS_HOME;
- revision conflict and idempotency tests;
- answer-lock tests through HTTP, not just direct functions;
- media path traversal and MIME tests;
- launch-token/origin tests;
- migration from V0.1 through schema v12.

### Agent Gateway

- contract tests shared by every adapter;
- MockAdapter golden paths;
- invalid JSON, wrong schema, process timeout, oversized output and cancellation;
- capability degradation tests;
- no live paid model in default CI.

### Frontend

- typed API contract generation/check;
- component tests for state and accessibility;
- Playwright: onboarding, resume, Writing V1/review/V2, Reading timed lock,
  privacy consent, image display and failure recovery;
- screenshot testing only after visual style is approved.

## 19. Engineering phases

### E0 — architecture spike — complete in V0.7

- scaffold optional FastAPI application and React/Vite workspace;
- `GET /api/health`, `GET /api/bootstrap` and tokenised localhost launch;
- no visual system and no Agent execution;
- prove editable installation, packaged static asset serving and clean shutdown;
- preserve all current tests.

### E1 — deterministic Study Runtime UI — complete in V0.7

- Session list/resume/create;
- Writing version submission;
- Reading answers/hints;
- question/passage display;
- media registry and Task 1 image delivery;
- MockAdapter returns fixture contracts;
- no real Agent subprocess.

### E2 — Agent Gateway — foundation complete in V0.7

- `agent_runs` migration, event persistence and SSE;
- MockAdapter and ManualAdapter;
- cancellation, one-time privacy consent and structured output validation;
- OpenCode and Claude adapters remain pending isolated capability/security tests;
- tool-hosted mode documentation for Codex desktop.

### E3 — remaining modules and packaging — partially complete

- Speaking handoff/report;
- Progress, Library and Settings are included in V0.7;
- optional Tauri evaluation;
- native Codex adapter only if a supported callable interface is verified.

Final style/design work can begin in parallel after E0 proves the page shell,
but visual tokens must not be hard-coded into backend contracts.

## 20. Approved decisions

Recommended defaults:

1. local browser app, not Electron/Tauri initially;
2. React + TypeScript + Vite;
3. FastAPI as optional local application dependency;
4. HTTP + SSE, no WebSocket initially;
5. MockAdapter first, no real Agent in E0;
6. existing Runtime remains authoritative;
7. direct model-provider APIs are allowed only through the versioned
   `ModelProvider` boundary and Teaching Runtime policy;
8. visual style deferred;
9. Codex desktop classified as tool-hosted until a native invocation interface
   is verified;
10. TextAnchor and media registry added before evidence/image integration.

All ten decisions were accepted for V0.7. They remain the boundary for future
adapter and visual-design work.
