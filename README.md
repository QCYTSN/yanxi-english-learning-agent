# IELTS Study Desk

[![Tests](https://github.com/QCYTSN/ielts-ai-coach/actions/workflows/tests.yml/badge.svg)](https://github.com/QCYTSN/ielts-ai-coach/actions/workflows/tests.yml)
[![Python 3.10–3.12](https://img.shields.io/badge/Python-3.10--3.12-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/Code-MIT-0f766e.svg)](LICENSE)
[![Release: 1.4.0](https://img.shields.io/badge/release-1.4.0-334155.svg)](RELEASE_NOTES.md)

Local-first, agent-native IELTS Academic learning software.

IELTS Study Desk combines a browser learning workspace, a local Python Teaching
Runtime, structured IELTS Skills and a user-selected model provider. Models can
explain and evaluate work, but they cannot directly write authoritative
learning records. Results pass Schema and semantic validation before the local
Runtime stores them.

> This independent project is not endorsed by IELTS, Cambridge University
> Press & Assessment, the British Council or IDP Education.

## What ships

- Today, Practice, Library, Progress and Settings workspaces;
- persistent teacher conversations with image, PDF, Word and text attachments;
- Reading, Writing, Speaking and Listening learning workflows;
- local SQLite learning records, Sessions, Corpus and Media Registry;
- ChatGPT login bridge, OpenAI-compatible API and local HTTP model providers;
- optional external CLI Agents for advanced material workflows;
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
Conversation Runtime ──> bounded Tutor Agent ──> allowlisted IELTS tools
        │
        └──────────────> Formal Teaching Runtime ──> Practice / Assessment
                                      ↓
                         SQLite / Session / Corpus / Media
```

Model providers and external Agents are separate concepts:

- **Model Provider** supplies inference for core teaching workflows;
- **External Agent** is an optional advanced tool for local material and
  developer workflows;
- **Teaching Runtime** owns IELTS rules, privacy, validation and persistence.

See [Architecture V2](docs/ARCHITECTURE_V2.md) and the
[Tutor Agent architecture](docs/TUTOR_AGENT_ARCHITECTURE.md).

## Install on Windows

For a tagged release, download the Windows x64 Setup executable from the
[GitHub Releases page](https://github.com/QCYTSN/ielts-ai-coach/releases) and
double-click it. The installer includes its own Python runtime. A normal user
does not need to install Python, Node.js, Git, Docker, WSL or a CLI Agent. If no
installer release is listed yet, use the source installation below.

On first launch the application creates its private data home under:

```text
%LOCALAPPDATA%\IELTS Study Desk\data
```

Existing `IELTS_HOME` settings and legacy `~/.ielts` homes are preserved.

Full instructions: [Installation](docs/INSTALLATION.md).

## Install from source

Python 3.10–3.12 is required. Node.js is needed only to rebuild the frontend.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
ielts-coach init
ielts-coach ui open
```

Optional local OCR dependencies:

```powershell
python -m pip install -e ".[ui,ocr]"
```

Install a developer desktop shortcut:

```powershell
ielts-coach ui shortcut-install
```

The shortcut starts or reuses the local service and opens the browser UI. It
does not require Claude Code, OpenCode or Codex to already be running.

## Model connections

Core deterministic functions do not require a model. For teacher dialogue,
Writing feedback and evidence-based explanations, configure one of:

1. ChatGPT login through the isolated managed runtime;
2. an OpenAI-compatible API;
3. a local OpenAI-compatible HTTP model.

Claude Code, OpenCode and Codex CLI remain optional advanced integrations and
are not required for the main learning experience.

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
ielts-coach evaluation release --cases tests/fixtures/agent_contracts
```

Windows release builds are produced with:

```powershell
.\scripts\build-windows-release.ps1 -Version 1.4.0
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
- Credentials are stored outside SQLite and use Windows DPAPI where available.
- The local service listens only on `127.0.0.1` and uses a random launch token.

See [Data license](DATA_LICENSE.md), [Third-party notices](THIRD_PARTY_NOTICES.md)
and [Privacy and copyright](docs/PRIVACY_AND_COPYRIGHT.md).
