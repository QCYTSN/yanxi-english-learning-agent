# Getting started

## Recommended Windows path

Download the latest Windows x64 Setup executable from GitHub Releases, install
it and open **IELTS Study Desk**. No terminal or system Python is required.

The first launch creates an empty local data home. Complete onboarding, choose
an AI connection if needed, then import material through Library.

See [Installation](INSTALLATION.md) for data locations, model choices, upgrades
and uninstall behaviour.

## Source installation

```powershell
cd <path-to-ielts-ai-coach>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
ielts-coach init
ielts-coach ui open
```

Set a custom data location only when desired:

```powershell
[Environment]::SetEnvironmentVariable(
  "IELTS_HOME",
  "D:\MyIELTSData",
  "User"
)
```

Reopen PowerShell after changing a persistent environment variable.

## First-use sequence

1. Set the Academic test date, score target and known baseline.
2. Keep cloud upload disabled unless remote model processing is intended.
3. Choose ChatGPT login, a compatible API or a local HTTP model; this can be
   skipped.
4. Import a legally obtained PDF, image, Word file, text file or structured
   corpus.
5. Review parsed/OCR drafts before publishing them to the learner catalogue.
6. Start Reading, Writing, Speaking or Listening practice.

## Empty question bank is expected

These commands should show no bundled learner questions in a fresh install:

```powershell
ielts-coach corpus stats
ielts-coach question list --module reading --limit 5
```

The product does not distribute Cambridge IELTS or commercial course content.
Automated tests use opt-in project-original fixtures that are excluded from the
wheel and Windows installer.

## Developer Skills

Contributors working from a Git clone may synchronise the canonical Skill
source into supported Agent directories:

```powershell
ielts-coach sync-skills
```

`skills-source/` remains the only editable Skill source.

## Health check

From a source checkout:

```powershell
ielts-coach doctor
```

For the installed desktop product, use **Settings → System**. The desktop
installer does not require a source checkout or external CLI Agent.
