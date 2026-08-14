# Current product scope — V1.5

## Identity

言蹊 (Yanxi) is a local-first, Tutor-led English learning product. General
English (daily and workplace) is the default learning track; IELTS Academic
ships as the first optional exam Domain Pack on the same Teaching Runtime.
The browser UI and Python Teaching Runtime own the learning workflow. A
configured Model Provider supplies constrained inference; external CLI
Agents are optional non-teaching tools.

The application is not a redistribution channel for IELTS books or commercial
questions. Public installs start with an empty question bank and use BYOC:
learners import materials they are legally entitled to use.

## Product surfaces

1. **Today** — teacher dialogue, attachment entry, resume and next action.
2. **Practice** — Listening, Reading, Writing and Speaking workspaces.
3. **Library** — learner material and an isolated Content Studio.
4. **Progress** — review queue, errors, trends and weekly decisions.
5. **Settings** — profile, providers, data, privacy, advanced tools and health.

## Authority boundary

```text
Learning UI
→ Teaching Runtime
→ Capability Policy + complete Skill Envelope
→ Model Provider
→ Schema + semantic validation
→ SQLite / Session / Corpus / Media
```

The model cannot directly write authoritative learning records. Browser memory,
chat history and external Agent history are not data sources of record.

## Required teaching integrity

### Writing

Independent response → evidence and cautious estimate → no more than three
priorities → learner V2 → comparison → optional alternative → archive.

### Reading

Independent answer or progressive hints → answer lock → passage evidence →
paraphrase and distractor explanation → error tag → review task.

### Speaking

No correction during a mock. External Voice/Live observations and local
rubric-based review remain separate and evidence-labelled.

### Listening

Audio, question, answer and transcript evidence remain distinct. Unverified
transcripts cannot become authoritative answer evidence.

## Model and Agent scope

Supported core providers:

- ChatGPT login through an isolated managed bridge;
- OpenAI-compatible APIs;
- local OpenAI-compatible HTTP models.

Claude Code, OpenCode, Codex CLI and manual handoff are optional External
Agents. They are not prerequisites for the desktop product.

## Data and deployment

- SQLite is the production database.
- The local service binds only to `127.0.0.1` and uses a random launch token.
- Windows installer data lives outside the application directory.
- Docker, WSL, PostgreSQL, RAG and a vector database are not required.
- Cloud sync, multi-user accounts and payment are outside the current scope.

## Distribution boundary

The GitHub release contains code, Skills, schemas, UI assets, licenses and the
desktop runtime. It does not contain personal data, provider credentials,
copyrighted PDFs/audio, commercial corpora or a pre-populated learner bank.
