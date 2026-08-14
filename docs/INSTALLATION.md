# Installation

## Windows: recommended installation

Download `Yanxi-<version>-Windows-x64-Setup.exe` from the GitHub
Release page and run it. The installer contains the Python runtime, local web
service and browser UI. A clean Windows computer does **not** need Python,
Node.js, Git, Docker, WSL, Claude Code, Codex CLI or OpenCode.

The installer:

- installs the application for the current Windows user;
- creates Start menu and optional desktop shortcuts with the product icon;
- creates an empty local question bank on first launch;
- stores learning data outside the installation directory;
- preserves learning data when the application is uninstalled or upgraded.

Default data location:

```text
%LOCALAPPDATA%\Yanxi\data
```

Existing users who set `IELTS_HOME` continue to use that location. Existing
legacy `~/.ielts` homes are also detected before the new default is selected.

## First launch

1. Open **言蹊 (Yanxi)** from the desktop or Start menu.
2. Complete the target and privacy setup.
3. Choose an AI connection, or skip it and use deterministic local features.
4. Import legally obtained questions or personal materials through Library.

The question bank is intentionally empty. The project does not distribute
Cambridge IELTS books, commercial questions, audio, answer keys or user data.

### AI choices

- **ChatGPT login**: the application downloads its isolated managed runtime on
  demand, then opens the login flow. This requires internet access and uses
  additional disk space.
- **OpenAI-compatible API**: enter a Base URL, API key and model ID. Keys are
  stored outside SQLite and protected with Windows DPAPI when available.
- **Local HTTP model**: connect a locally running compatible service.
- **No AI yet**: import, browse and manage local material without model calls.

## Source/developer installation

Requirements:

- Python 3.10–3.12;
- Node.js 22 only when rebuilding the frontend;
- Git only when cloning or contributing.

```powershell
git clone <repository-url>
cd yanxi-english-learning-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
xiyan init
xiyan ui open
```

OCR is optional:

```powershell
python -m pip install -e ".[ui,ocr]"
```

Install or update the developer shortcut:

```powershell
xiyan ui shortcut-install
```

## Upgrade and uninstall

Install a newer version over the existing application. Database migrations are
backward-compatible and the data directory is not replaced.

Uninstalling removes the application but deliberately preserves the data
directory. Users can delete that directory manually only after exporting or
backing up anything they want to keep.
