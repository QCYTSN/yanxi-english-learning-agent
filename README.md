# 言蹊 (Yanxi)

<p align="center">
  <img src="docs/assets/yanxi-logo.svg" alt="言蹊 logo · 现代印章风" width="340">
</p>

[![Tests](https://github.com/QCYTSN/yanxi-english-learning-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/QCYTSN/yanxi-english-learning-agent/actions/workflows/tests.yml)
[![Python 3.10–3.12](https://img.shields.io/badge/Python-3.10--3.12-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/Code-MIT-0f766e.svg)](LICENSE)
[![Release: 1.5.0](https://img.shields.io/badge/release-1.5.0-334155.svg)](RELEASE_NOTES.md)

> **中文文档：[README.zh-CN.md](README.zh-CN.md)** · This document is also available in Chinese.

Local-first, agent-native English learning software.

言蹊 combines a browser learning workspace, a local Python Teaching Runtime,
structured Skills and a user-selected model provider. Models can explain and
evaluate work, but they cannot directly write authoritative learning records.
Results pass Schema and semantic validation before the local Runtime stores
them.

The default track is general English (daily and workplace), backed by a
reusable Learning Agent Kernel that owns objectives, activities, skill
evidence, mastery estimates and review scheduling. IELTS Academic ships as the
first optional exam Domain Pack with its own curriculum and band policies.

> This independent project is not endorsed by IELTS, Cambridge University
> Press & Assessment, the British Council or IDP Education.

## What ships

- a conversation-first learning workspace with Today, Practice, Library,
  Progress and Settings surfaces;
- persistent teacher conversations with image, PDF, Word and text attachments;
- auto-ingested vocabulary: words the tutor explains in conversation become
  confirmable candidates with undo and already-known dedup, feeding spaced
  review;
- rich word cards: bundled offline presets for ~2900 high-frequency words
  (IPA, part of speech, definitions and inflections) plus on-demand model
  enrichment for every other word, stored with provenance;
- adaptive spaced review: recalled words climb a 1-2-4-7-14-30-60 day ladder,
  missed words return the next day;
- automatic local backups: weekly freshness check with the five most recent
  automatic backups kept, alongside manual and pre-migration snapshots;
- first-class typing and listening practice (打词 / 听言) over your own words
  plus a bundled public-domain starter-100 word list;
- Reading, Writing, Speaking and Listening learning workflows plus vocabulary
  and grammar support;
- local SQLite learning records, Sessions, Corpus and Media Registry;
- ChatGPT login bridge, OpenAI-compatible API and local HTTP model providers;
- bounded long-conversation context, indexed local history and resumable
  background OCR/content jobs;
- versioned learner memory with expiry and explicit contradiction resolution;
- typing misses feed learner memory so later conversations proactively
  explain the words you struggle to spell;
- Runtime-owned teaching cycles and privacy-safe teaching-policy regression;
- learner-facing teaching paths, editable study goals, skill-evidence views and
  learner-controlled teacher memory;
- Windows desktop installer and Python package for technical users.

## What does not ship

The public application starts with an **empty question bank**. It does not
bundle Cambridge IELTS books, past papers, commercial course questions, audio,
answer keys, user essays, credentials or private learning records. Users import
materials they are legally entitled to use.

Project tests may use small project-original fixtures. Release verification
ensures those fixtures do not enter the wheel or Windows installer.

## Architecture

```text
Browser learning UI
        ↓
Conversation Runtime ──> bounded Tutor Agent ──> allowlisted Skill tools
        │
        └──────────────> Formal Teaching Runtime ──> Practice / Assessment
                                      │
                         General English (default) / IELTS Academic
                                      ↓
                   Learning Agent Kernel / authoritative local data
                                      ↓
                         SQLite / Session / Corpus / Media
```

Model providers and the Teaching Runtime are separate concepts:

- **Model Provider** supplies inference for core teaching workflows
  (BYO OpenAI-compatible API, ChatGPT login bridge, or local HTTP model);
- **Teaching Runtime** owns track rules, privacy, validation and persistence;
- external CLI Agents are not teaching providers and are not part of the
  main learning experience.

See [Architecture V2](docs/ARCHITECTURE_V2.md) and the
[Tutor Agent architecture](docs/TUTOR_AGENT_ARCHITECTURE.md). The reusable
learning-state boundary is defined in the
[Learning Agent Kernel](docs/LEARNING_AGENT_KERNEL.md).

### Learning Agent kernel

The internal learning layer is deliberately narrower than a general autonomous
Agent:

- the General English track defines the six-dimension skill graph (listening,
  reading, writing, speaking, vocabulary, grammar) with CEFR-aligned teaching
  policies; IELTS Academic ships as an optional exam Domain Pack with its own
  four-module graph, evidence mappings and band policies;
- the Runtime derives objectives, activities, mastery evidence and review
  timing from validated learning records;
- Skills load only the reference documents the current teaching phase needs;
  a failed planner degrades to one direct answer instead of failing the turn;
- learner memory is local, revisioned, expirable and withheld from the Tutor
  whenever statements conflict;
- teaching cycles move through explicit diagnose, teach, guided-practice,
  independent-practice, assess, review and consolidate stages;
- models may recommend actions, but only the learner or Runtime may change
  formal learning state;
- release checks cover both structured-output contracts and positive/negative
  teaching-policy controls without retaining raw learner content.

This architecture can support future English-learning tracks. The default
track is General English; IELTS Academic is the first optional exam Domain
Pack. New tracks require their own curriculum, Skills, contracts and
evaluation set.

## Install on Windows

For a tagged release, download the Windows x64 Setup executable from the
[GitHub Releases page](https://github.com/QCYTSN/yanxi-english-learning-agent/releases) and
double-click it. The installer includes its own Python runtime. A normal user
does not need to install Python, Node.js, Git, Docker, WSL or a CLI Agent. If no
installer release is listed yet, use the source installation below.

On first launch the application creates its private data home under:

```text
%LOCALAPPDATA%\Yanxi\data
```

Existing `IELTS_HOME` settings and legacy `~/.ielts` homes are preserved.

Full instructions: [Installation](docs/INSTALLATION.md).

## Install from source

Python 3.10–3.12 is required. Node.js is needed only to rebuild the frontend.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
xiyan init
xiyan ui open
```

Optional local OCR dependencies:

```powershell
python -m pip install -e ".[ui,ocr]"
```

Install a developer desktop shortcut:

```powershell
xiyan ui shortcut-install
```

The shortcut starts or reuses the local service and opens the browser UI.

## Model connections

Core deterministic functions (typing, listening, wordlist, review scheduling)
do not require a model. For teacher dialogue, Writing feedback and
evidence-based explanations, configure one of:

1. an OpenAI-compatible API (BYO key, any vendor and model);
2. ChatGPT login through the isolated managed runtime;
3. a local OpenAI-compatible HTTP model.

## Development

```powershell
python -m pip install -e ".[ui,dev]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q

cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

Before publishing:

```powershell
python scripts/verify_release.py --source-only
xiyan evaluation release --cases tests/fixtures/agent_contracts
```

The release command runs contract conformance, the built-in positive/negative
teaching-quality suite and the configured local scale-performance gate.

Windows release builds are produced with:

```powershell
.\scripts\build-windows-release.ps1 -Version 1.5.0
```

See [Release checklist](docs/RELEASE_CHECKLIST.md).

## Documentation

- [Product boundary](PRODUCT.md)
- [Architecture V2](docs/ARCHITECTURE_V2.md)
- [Tutor Agent architecture](docs/TUTOR_AGENT_ARCHITECTURE.md)
- [Installation](docs/INSTALLATION.md)
- [Privacy and copyright](docs/PRIVACY_AND_COPYRIGHT.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Data, privacy and licensing

- Application code and Skills: MIT License.
- Project-original documentation and test fixtures: CC BY 4.0 unless stated otherwise.
- User material and third-party content remain owned by their respective rights holders.
- Credentials are stored outside SQLite and use Windows DPAPI or the operating
  system keyring where available, with an owner-only local fallback.
- The local service listens only on `127.0.0.1` and uses a random launch token.

See [Data license](DATA_LICENSE.md), [Third-party notices](THIRD_PARTY_NOTICES.md)
and [Privacy and copyright](docs/PRIVACY_AND_COPYRIGHT.md).
