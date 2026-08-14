# Getting started

## Recommended Windows path

Download the latest Windows x64 Setup executable from GitHub Releases, install
it and open **言蹊 (Yanxi)**. No terminal or system Python is required.

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
xiyan init
xiyan ui open
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

1. Choose a learning track: General English (default, CEFR self-assessment)
   or IELTS Academic (test date, score target and baseline).
2. Keep cloud upload disabled unless remote model processing is intended.
3. Choose ChatGPT login, a compatible API or a local HTTP model; this can be
   skipped.
4. Say hello in the Today conversation, or start typing practice (打词) and
   listening practice (听言) right away — no model or material needed.
5. Import legally obtained PDFs, images, Word files or text into Library;
   review parsed/OCR drafts before use.
6. Start Reading, Writing, Speaking or Listening practice when material or
   a model connection is ready.

## Empty question bank is expected

A fresh install has no bundled learner questions:

```powershell
xiyan corpus stats
```

The product does not distribute Cambridge IELTS or commercial course content.
Automated tests use opt-in project-original fixtures that are excluded from the
wheel and Windows installer.

## Developer Skills

Contributors working from a Git clone may synchronise the canonical Skill
source into supported Agent directories:

```powershell
xiyan sync-skills
```

`skills-source/` remains the only editable Skill source.

## Health check

From a source checkout:

```powershell
xiyan doctor
```

For the installed desktop product, use **Settings → System**. The desktop
installer does not require a source checkout or external CLI Agent.
