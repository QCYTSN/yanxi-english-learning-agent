# UI implementation handoff

Status: V0.9 functional UI implemented on 2026-07-23. Final visual style is not
approved and must not be inferred from the current engineering shell.

## Project

```text
Repository:   D:\Github_Ku\ielts-ai-coach
Private data: D:\IELTS_AI\data
Core version: v0.9.0
UI form:      packaged local browser application
```

The Python Study Runtime, Session Markdown, SQLite, Corpus, validation, privacy
and rubrics remain authoritative. React renders state and collects actions; it
does not contain a second IELTS rules engine.

## Run the UI

Install the optional UI dependencies, initialise a local data directory, and
start the loopback service:

```powershell
python -m pip install -e ".[ui]"
ielts-coach init
ielts-coach ui open
```

Useful options:

```powershell
ielts-coach ui open --port 8765
ielts-coach ui open --no-open
ielts-coach ui open --home D:\IELTS_AI\data
ielts-coach ui status
ielts-coach ui stop
ielts-coach ui shortcut-install
```

The server always binds to `127.0.0.1`. `ui open` reuses a healthy instance or
starts one in the background, then issues a fresh one-time launch token. The
token is exchanged for a SameSite HttpOnly browser session and removed from the
address bar. The Windows shortcut follows the same path; it does not start an
Agent.

## Implemented through V0.9

- React + TypeScript + Vite application packaged inside the Python wheel;
- Today, Practice, Writing, Reading, Speaking, Listening, Feedback, Library, History/Progress and
  Settings routes;
- Writing autosave, revision-safe V1/V2 submission and evidence anchors;
- Reading guided hints, timed answer integrity and structured review;
- Task 1 structured tables, registered PNG/JPEG/WebP media and original-image
  viewing;
- Speaking Voice/Live task packages, transcript/structured-report import and Story Bank;
- 10-category, 50-item original Listening high-frequency corpus with deterministic attempts and review state;
- schema v12 infrastructure for drafts, idempotency, media, auditable content reviews, content imports, assessment packs, AssessmentRun/SectionRun/QuestionResponse, Listening items and Agent runs;
- one full-mock runner shared by Reading, Writing, Listening and Speaking, with frozen pack snapshots, server-owned state and submission;
- Reading three-passage/40-question execution, Writing Task 1/Task 2 execution and Runtime-owned 1:2 aggregation;
- registered Listening audio with persistent one-play state and Speaking Voice/Live handoff bound to the same authoritative Session;
- cross-process Session locks, revision conflicts and duplicate-write safety;
- MockAdapter for deterministic end-to-end coaching flows;
- ManualAdapter request export and validated result import;
- HTTP + SSE run status, cancellation and one-time privacy consent;
- compact bootstrap, corpus, progress and 70/30 allocation APIs;
- stable JSON error codes and canonical Session refetch after mutations.

## Explicitly not implemented in V0.7

- OpenCode, Claude or Codex process adapters;
- browser control of an already-open desktop Agent conversation;
- direct model-provider APIs;
- built-in Speaking audio capture, speech recognition or acoustic pronunciation scoring;
- final visual system, dark mode, desktop shell, cloud sync or multi-user auth.

An Agent that can run local commands can start the UI. That does not imply the
UI can call back into the same Agent conversation. Until a vendor adapter passes
isolated invocation, cancellation, privacy and output-contract tests, use the
ManualAdapter.

## Source map

```text
frontend/                         React source and browser tests
src/ielts_coach/web/              FastAPI app, auth and loopback server
src/ielts_coach/listening_corpus.py  deterministic Listening corpus/review service
src/ielts_coach/speaking_handoff.py  external Voice/Live task packages
src/ielts_coach/agent_gateway/    adapter contract, Mock and Manual adapters
src/ielts_coach/media.py          Media Registry
src/ielts_coach/text_anchor.py    exact evidence anchoring
src/ielts_coach/locking.py        cross-process mutation locks
tests/test_v07_ui.py              API/security/concurrency/media integration
tests/test_v07_four_modules.py    Listening/Speaking/launcher integration
```

`skills-source/` remains the only editable Skill source. Do not edit generated
`.claude/skills`, `.agents/skills` or `.opencode/skills` copies directly.

## Next implementation gate

The next task should add one real process adapter at a time, beginning with a
capability probe and security fixture outside learner data. It must prove:

1. fixed executable and argument-array construction;
2. no parsing of terminal presentation text;
3. structured output or an explicit adapter-owned conversion boundary;
4. timeout, output-size cap, cancellation and process-tree cleanup;
5. image/privacy capability degradation;
6. invalid output never reaches canonical Session records;
7. Writing and Reading complete end-to-end through that adapter.

Do not combine this gate with final visual redesign. Visual work can replace
tokens and presentation components later without changing Runtime/API contracts.

## Release verification

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q

cd frontend
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e  # requires IELTS_E2E_LAUNCH_URL from a running local UI
npm audit

cd ..
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
python -m build
```

The E2E test uses the installed Microsoft Edge channel and does not download a
browser into the product package.
