# IELTS AI Coach UI product and architecture specification

Status: V0.7 workflow implemented; visual direction remains provisional.
Palette, typography and decorative language are intentionally not frozen and
require a later design decision. `UI_ENGINEERING_ARCHITECTURE.md` remains
authoritative for engineering structure and integration boundaries.

V0.7 is a usable companion UI, not the final visual release. It includes Today,
practice selection, Writing, Reading, external Voice/Live Speaking handoff,
high-frequency Listening, evidence feedback, Library, History/Progress and
Settings, backed by the local Runtime. Mock and manual Agent routes are
available; verified vendor process adapters remain later product increments.

## 1. Product decision

The UI is a local **IELTS Study Desk**, not a terminal wrapper and not a generic
chat page. Its single job is to let a learner complete IELTS Academic practice,
receive evidence-grounded coaching, revise, and continue later without seeing
Agent tool traces or editing Session files.

The deterministic Python runtime remains the source of truth:

```text
Study Desk UI
    -> local application API
    -> Study Runtime / Corpus / Progress
    -> SQLite + Session documents + registered media

Agent Adapter
    -> invokes one specialist Skill
    -> returns a validated teaching contract
    -> Study Runtime validates and persists it
    -> UI renders the result
```

The UI must never parse Claude Code, Codex or OpenCode terminal presentation.
Agent integration is a replaceable adapter, while the UI and Study Runtime are
vendor-neutral.

## 2. Critical capability boundary

A local UI cannot automatically send a new message into every arbitrary Agent.
Compatibility has three levels:

1. **Process adapter**: the Agent exposes a non-interactive CLI/server and
   resumable Session. The UI can invoke it and stream structured output.
2. **Tool-hosted adapter**: a desktop Agent can run local commands and start the
   UI, but does not expose a callable conversation API. The current Agent task
   coordinates the Runtime; the UI cannot independently wake it after the task
   ends.
3. **Manual adapter**: the UI creates a structured request package and imports a
   structured response. This is the universal fallback.

Current local capability evidence:

- Claude Code exposes non-interactive `--print`, `stream-json`, JSON Schema and
  resumable sessions; it is suitable for a future process adapter.
- OpenCode exposes `run`, `serve`, session continuation and ACP; it is suitable
  for a future process/server adapter.
- The installed Codex desktop executable is app-managed and did not expose a
  callable CLI from this PowerShell environment. Codex can still launch and use
  local Runtime tools as a tool-hosted Agent. A native adapter must not be
  claimed until an invocation interface is verified.

Therefore, “works with any Agent” means the Agent can implement the documented
adapter contract. It does not mean the UI can control an unknown application.

## 3. Recommended implementation shape

### Local web application

Recommended first stack:

- React + TypeScript + Vite for the UI;
- a small FastAPI application layer inside the Python package;
- existing Python Study Runtime for all mutations;
- SQLite reads through repository/service functions, never from browser code;
- browser delivery on `127.0.0.1` only;
- optional Tauri packaging only after the browser version is stable.

The local application API is not a model API backend. It exposes deterministic
IELTS operations. Model execution lives behind the optional Agent Adapter.

Why this shape:

- strong support for split-pane reading, rich text selection, diff views,
  image zoom and keyboard navigation;
- runs from terminal Agents and desktop Agents that can launch a local command;
- preserves Python migrations, privacy gates and Session validation;
- avoids maintaining separate desktop-native UI implementations.

### Launch contract

Implemented everyday command:

```powershell
ielts-coach ui open
```

Expected behaviour:

1. bind to `127.0.0.1` on an available port;
2. create a short-lived launch token;
3. detect available adapters without selecting a model or starting an Agent silently;
4. open the browser or return the local URL;
5. show an explicit connection state;
6. continue the most recent active Session when the learner chooses Continue.

An Agent may trigger the same command after a request such as “启动雅思学习界面”.
The UI must also be directly launchable without an Agent conversation.
`ielts-coach ui shortcut-install` creates a Windows desktop entry that invokes
the same start-or-reuse path. It is a UI launcher, not an Agent launcher.

## 4. Agent Adapter contract

All adapters implement the same capabilities:

```text
probe() -> availability + capabilities
start(request) -> run_id
stream(run_id) -> typed events
resume(agent_session_id, request) -> run_id
cancel(run_id)
```

Capability flags:

```text
structured_output
streaming
session_resume
image_input
audio_input
tool_execution
local_only
```

The UI must disable unsupported actions rather than pretending they work.

### Request envelope

```json
{
  "request_version": 1,
  "request_id": "uuid",
  "study_session_id": "W-20260722-001",
  "skill": "ielts-writing",
  "action": "first_review",
  "context_ref": "runtime-generated-reference",
  "payload_refs": ["learner-version:v1", "question:START-WT2-001"],
  "output_contract": "writing-review@1",
  "privacy_decision": {
    "remote_processing": true,
    "allowed": true,
    "source_types": ["project_original"]
  }
}
```

Raw private content is resolved only after the privacy gate passes. Shell
commands use argument arrays, never interpolated strings.

### Response handling

Agent text is not the data source. Formal results must validate as one of:

- `writing-review@1`;
- `reading-review@1`;
- the existing structured Speaking report;
- a future generic qualitative-coaching contract.

Validation failure produces a recoverable UI state: “反馈格式不完整，重新生成”
with a retry action. Invalid output is not saved as an official Session result.

## 5. Information architecture

Primary navigation contains five destinations:

1. **Today** — continue work, one recommended task, optional maintenance task;
2. **Practice** — Writing, Reading, Speaking and Listening record entry;
3. **Library** — indexed questions, passages, provenance and private imports;
4. **Progress** — targets, criterion trends, recurring errors and allocation;
5. **Settings** — profile, privacy, Agent connection, rubric and storage health.

Do not create separate navigation items for every CLI command. Runtime concepts
such as schema, revision and migration remain invisible unless diagnostics are
opened.

## 6. First-use experience

Onboarding is a single four-step flow:

1. Academic test confirmation and optional test date;
2. target, minimum required and stretch scores;
3. known baseline scores, each allowing “暂时不知道”;
4. Agent connection and private-material processing preference.

The learner can skip the diagnostic and start practice. Existing onboarding
data must bypass this flow. The UI must not ask stored questions again.

Final screen:

```text
准备好了
主要目标：总分 7.0，写作不低于 6.5
[开始一次短测]  [直接练习]
```

## 7. Page specifications

### 7.1 Today

Purpose: decide and begin the next useful action in under ten seconds.

```text
┌──── rail ────┬──────────────────────────────────────────────┐
│ Today        │ Good evening                                │
│ Practice     │ ┌ Continue Reading ───────────────────────┐ │
│ Library      │ │ Passage 3 · Question 11 · 12 min saved │ │
│ Progress     │ │ [Continue]                              │ │
│ Settings     │ └─────────────────────────────────────────┘ │
│              │                                            │
│              │ Today’s focus                              │
│              │ Writing Task 2 · develop one main idea     │
│              │ 40 min · because TR is the current risk    │
│              │ [Start practice]                           │
│              │                                            │
│              │ Optional: Listening error review · 10 min │
└──────────────┴──────────────────────────────────────────────┘
```

Rules:

- one primary recommendation, not a grid of competing cards;
- active Session always appears first;
- reasons use one sentence and one piece of data;
- no dashboard charts on Today;
- generic free-text intent is optional, below the primary actions.

### 7.2 Practice selector

Four subject rows, not playful course tiles. Each shows the next meaningful
mode, estimated time and last result. Writing and Reading are visually primary.

Direct actions route deterministically to the corresponding Skill. Only the
free-text “What do you want to practise?” input uses the `ielts` router.

### 7.3 Writing workspace

The interface changes by phase rather than accumulating panels.

```text
┌ phase: Plan — Write — Review — Revise — Finish ────────────┐
├──────────── task / visual ─────────┬──── learner editor ───┤
│ Task prompt                        │                       │
│                                   │  Version 1            │
│ Task 1 image                      │                       │
│ [zoom] [fit] [open data table]    │                       │
│                                   │                       │
│ Requirements                      │                       │
├───────────────────────────────────┴───────────────────────┤
│ 38:24 remaining     276 words                  [Submit V1]│
└───────────────────────────────────────────────────────────┘
```

Requirements:

- autosave locally without creating a completed attempt;
- timer can be hidden or paused outside mock mode;
- word count always visible but quiet;
- Task 1 visual supports zoom, pan, fit, full screen and alt description;
- if structured source data exists, expose an accessible table;
- do not score Task 1 when the image is unreadable;
- preserve the learner’s exact V1 and V2;
- warn before replacing an existing version.

Review phase:

```text
┌ essay with evidence anchors ──────┬ Evidence Rail ─────────┐
│ ... highlighted learner sentence │ Estimated 6.0–6.5      │
│                                   │ Confidence: Medium     │
│ ...                               │                        │
│                                   │ TR 6.0–6.5  [evidence] │
│                                   │ CC 6.0      [evidence] │
│                                   │ LR 6.5      [evidence] │
│                                   │ GRA 6.0     [evidence] │
│                                   │                        │
│                                   │ Three priorities       │
│                                   │ 1 ...                  │
│                                   │ [Revise myself]        │
└───────────────────────────────────┴────────────────────────┘
```

Clicking evidence scrolls to and briefly outlines the supporting sentence.
Before V2, no control offers a full model answer. After V2, the diff distinguishes
minimal correction, natural expression and target-band alternative.

### 7.4 Reading workspace

Desktop split is passage 56%, questions 44%; the divider is adjustable.

```text
┌──────── Passage 2 ────────────────┬ Questions 14–26 ───────┐
│ paragraphs with stable labels     │ 14  True False NG      │
│ A                                 │ [True] [False] [NG]     │
│ ...                               │                        │
│ B                                 │ 15 ...                 │
│ ...                               │                        │
│                                   │ [Hint 1]               │
├───────────────────────────────────┴────────────────────────┤
│ 12 answered · 18:42 remaining                    [Submit] │
└────────────────────────────────────────────────────────────┘
```

Integrity rules:

- timed mode removes all hint and answer controls until full submission;
- guided mode reveals exactly one hint level at a time;
- answer palette communicates answered/unanswered/current with icons and text,
  not colour alone;
- review highlights the evidence location in the passage;
- a correct answer is shown only after submission;
- distractor explanations appear only for relevant options;
- completion answers display word limit, accepted variant, grammar, number and
  spelling checks;
- unverified keys display “未验证答案” and never produce a score.

### 7.5 Speaking workspace

The UI prepares and reviews speaking; it does not pretend to be a complete
acoustic examiner.

States:

1. choose full mock or targeted drill;
2. display questions/Cue Card and preparation timer;
3. launch a configured Voice/Live handoff or show copyable handoff package;
4. import observations/report;
5. show local evidence-based review.

During a full mock, no feedback panel appears. After import, FC/LR/GRA can be
supported by transcript/timing evidence. PRON is disabled and labelled
“需要音频证据” unless acoustic or voice-model observations exist. Content
development is explained under FC; it is never displayed as a fifth score.

### 7.6 Progress

Progress answers three questions:

- Am I at or above the minimum requirement?
- What is improving or deteriorating?
- What should I practise next?

Use:

- bullet charts for current versus minimum/target;
- line charts only after at least four comparable data points;
- grouped bars for Writing/Speaking criteria;
- a sortable table for Reading question-type accuracy;
- a frequency list for recurring errors.

Do not use gauges, radar charts, pie charts or celebratory streak mechanics.
Every chart has a visible value and table fallback. Low-confidence and partial
scores are visually differentiated and excluded from automatic planning.

### 7.7 Library

The Library is a provenance-aware index, not a file browser.

Filters: module, task/part, question type, topic, source, authenticity,
review status and attempted state. Every item shows a source badge:

```text
Project original · Practice only
Official external · Link only
Licensed private · Local only
Seasonal reported · Unverified
Synthetic · Not authentic
```

Private files remain outside the repository. Remote use invokes the privacy
gate immediately before content resolution.

### 7.8 Settings and diagnostics

Sections:

- Academic profile and score targets;
- Agent connection and capabilities;
- privacy defaults and one-time-consent explanation;
- IELTS rubric registry and local-file availability;
- data location, backup and database health;
- optional metadata-only telemetry;
- advanced diagnostics with `doctor` results.

No provider secret is displayed after storage. Do not add model selection until
the separate model-selection decision is made.

## 8. Session state and UI behaviour

| Runtime status | Learner-facing state | Allowed primary action |
|---|---|---|
| `draft` | Ready to begin | Start |
| `question_presented` | Task visible | Begin work |
| `learner_working` | Editing/answering | Save or submit |
| `awaiting_feedback` | Feedback generating | Cancel generation |
| `awaiting_revision` | Feedback ready | Revise or finish |
| `completed` | Archived | Review or practise similar |
| `cancelled` | Stopped | Start new Session |

The UI sends the expected revision on every mutation. A conflict offers:

```text
This practice changed in another window.
[Load newer version] [Compare changes]
```

Never silently overwrite a learner version.

## 9. Visual system

### Direction: Focused Study Desk

The visual language comes from an annotated exam workspace: clear paper,
stable margins, precise evidence anchors and restrained examiner marks. It is
not a colourful language-learning game, a generic SaaS dashboard, claymorphism,
glassmorphism or terminal cosplay.

Signature element: **Evidence Rail** — a narrow margin connecting every score,
correction and wrong-answer explanation to the learner’s sentence or passage
location. This is the single expressive device; the rest remains quiet.

### Colour tokens

| Token | Value | Use |
|---|---:|---|
| paper | `#F7F9FC` | application background |
| surface | `#FFFFFF` | task and editor surfaces |
| ink | `#172033` | primary text |
| navy | `#1E3A5F` | primary action and focus identity |
| evidence | `#0F766E` | grounded evidence and verified state |
| revision | `#B45309` | learner action and unresolved revision |
| danger | `#B42318` | destructive/error state only |
| muted | `#5F6B7A` | secondary text |
| border | `#CBD5E1` | structure |

No gradients. Correct/incorrect state uses icon + label + colour. Dark mode is
not MVP; preserve semantic tokens so it can be added later.

### Typography

- UI and editable text: Atkinson Hyperlegible with `Noto Sans SC`/system CJK
  fallback;
- long Reading passages and task display: Literata or Source Serif 4 with
  `Noto Serif SC` fallback;
- compact data, timers and question numbers: IBM Plex Mono or system monospace.

Fonts must be bundled under compatible licences or fall back cleanly when
offline. Body text is at least 16px; long passages use 17–18px and 1.65 line
height. Do not use serif typography in dense controls.

### Shape, depth and motion

- 6px control radius, 8px panel radius;
- 1px borders carry most structure;
- shadows only for modal/overlay elevation;
- 120–180ms interaction transitions;
- one 250ms evidence-anchor outline when navigating to evidence;
- no page-load choreography, parallax, animated gradients or bouncing rewards;
- respect `prefers-reduced-motion`.

## 10. Responsive and accessibility requirements

Primary practice target: desktop widths 1280–1600px. Fully usable at 1024px.
At smaller widths, Writing and Reading switch between task and response tabs;
mobile supports review and short practice but is not presented as an ideal full
mock environment.

Non-negotiable requirements:

- WCAG AA contrast, 4.5:1 for normal text;
- complete keyboard access and visible focus;
- minimum 44×44px touch targets;
- logical heading hierarchy and skip-to-content;
- `aria-live` for save, validation and generation status;
- no hover-only actions;
- Task 1 images require meaningful alt text, zoom controls and optional data
  table when source data exists;
- keyboard shortcuts have visible discoverability and never override standard
  browser editing shortcuts;
- charts provide a table or text equivalent.

Suggested shortcuts:

```text
Ctrl/Cmd + S        save draft
Ctrl/Cmd + Enter    submit current phase, with confirmation
Alt + 1/2/3         request guided hint level when allowed
Alt + E             open Evidence Rail
```

## 11. Loading, empty and failure states

The UI never shows model chain-of-thought or terminal logs.

Agent states:

```text
Preparing the task
Reviewing your response against the IELTS criteria
Checking feedback format
Saving your progress
```

Failures name the recovery action:

- Agent unavailable → Select another adapter / Retry / Export request;
- invalid feedback contract → Regenerate feedback;
- stale Session revision → Load newer version / Compare;
- private source blocked → Explain one-time consent / Use local-only mode;
- rubric unavailable → Continue with qualitative feedback / Register rubric;
- unreadable Task 1 visual → Replace image; scoring disabled;
- database failure → learner draft remains visible and retryable.

Empty states use direct actions: “No private corpus yet — Register a source,”
not decorative motivational copy.

## 12. Local API boundary

Proposed deterministic endpoints:

```text
GET  /api/bootstrap
GET  /api/today
GET  /api/sessions/active
POST /api/sessions
GET  /api/sessions/{id}
POST /api/sessions/{id}/finish

POST /api/writing/{id}/versions
POST /api/writing/{id}/reviews
POST /api/reading/{id}/hints
POST /api/reading/{id}/answers
POST /api/reading/{id}/reviews

GET  /api/questions
GET  /api/questions/{id}
GET  /api/passages/{id}
GET  /api/media/{media_id}
GET  /api/progress/summary
GET  /api/progress/trends

GET  /api/agents
POST /api/agent-runs
GET  /api/agent-runs/{id}/events
POST /api/agent-runs/{id}/cancel
```

Mutations call existing Python services; they do not duplicate validation in
the frontend. Streaming should use Server-Sent Events first. WebSockets are not
required for MVP.

## 13. Security boundary

- bind only to `127.0.0.1` by default;
- random launch token and strict Origin checks;
- no permissive CORS wildcard;
- registered-media IDs instead of arbitrary filesystem paths;
- allowlist file types and enforce size limits;
- never serve the SQLite file, private corpus directory or environment files;
- adapter subprocess arguments are arrays with fixed executables;
- redact secrets and private text from logs;
- explicit privacy decision attached to each remote Agent request;
- no automatic public network exposure.

## 14. Implementation phases

### UI-0 — engineering UI shell (complete in V0.7)

- static routes and real-looking fixture data;
- Today, Writing and Reading desktop screens;
- Task 1 image viewer and Evidence Rail interaction;
- responsive and keyboard review;
- no SQLite or Agent integration.

Exit: workflow and responsive shell are usable. Final visual approval is
deliberately deferred.

### UI-1 — deterministic local application (complete in V0.7)

- FastAPI shell and tokenised localhost launch;
- bootstrap/profile/session/question endpoints;
- resume active Session;
- Writing editor/autosave/version submit;
- Reading split view/hints/submission;
- Task 1 registered image serving;
- no live Agent invocation yet; use fixture feedback contracts.

Exit: the full learner workflow works without terminal editing.

### UI-2 — Agent adapters (foundation complete in V0.7)

- adapter interface and capability screen;
- MockAdapter and ManualAdapter are implemented;
- OpenCode and Claude process/server adapters follow isolated verification;
- manual request/response adapter as universal fallback;
- structured streaming and cancellation;
- privacy gate before payload resolution;
- no model-selection optimisation in this phase.

Exit for V0.7: Writing and Reading complete end-to-end through MockAdapter, and
ManualAdapter supports export/import with validation. Vendor adapter exit
criteria remain unchanged for their later increment.

### UI-3 — remaining product surfaces (partially complete)

- Speaking Voice/Live handoff and report review;
- Progress, Library and Settings are implemented;
- corpus import guidance;
- rubric/settings/doctor screens;
- optional local packaging.

The V0.7 content workbench now also exposes corpus readiness, a local raw-file
inbox and structured manifest/JSONL import. Assisted PDF/audio structuring,
human review and visual pack assembly remain subsequent increments.

## 15. MVP exclusions

- direct model-provider API backend;
- account/login/payment/multi-user features;
- public deployment or cloud sync;
- audio recording, speech-to-text or acoustic pronunciation scoring;
- automatic OCR of books;
- RAG, vectors or fine-tuning;
- model marketplace and automatic model recommendation;
- elaborate dashboard, streaks, badges or gamification;
- mobile application packaging.

## 16. Acceptance criteria

The V0.7 usable frontend is accepted only when:

1. an Agent or user can start it with one command;
2. an existing active Session resumes without data loss;
3. the learner can practise without seeing terminal traces;
4. Writing V1 cannot be replaced silently and no model answer appears before V2;
5. Reading timed mode cannot reveal hints or answers before submission;
6. Task 1 images render with zoom and an accessible fallback;
7. feedback evidence navigates to the exact learner/passage location;
8. invalid Agent output is rejected instead of rendered as a valid score;
9. private material cannot be resolved for remote processing without the
   privacy decision;
10. unsupported Agent capabilities are visible and gracefully degraded;
11. keyboard-only use completes the primary Writing and Reading flows;
12. all current backend tests remain green and frontend critical flows have
   automated tests.

## 17. Decisions deliberately left for later

- final model/provider selection;
- whether Codex receives a verified native adapter;
- whether ACP/MCP sampling becomes the generic Agent protocol;
- dark mode;
- Tauri packaging;
- local speech processing.

These decisions must not block UI-0 or UI-1.
