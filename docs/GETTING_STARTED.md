# Getting started

## Install and initialise

```powershell
cd D:\Github_Ku\ielts-ai-coach
conda create -n ielts-coach python=3.12 -y
conda activate ielts-coach
python -m pip install -e .

$env:IELTS_HOME = "D:\IELTS_AI\data"
[Environment]::SetEnvironmentVariable("IELTS_HOME", "D:\IELTS_AI\data", "User")

ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
```

Initialisation creates configuration, SQLite, corpus directories, Session
folders, story bank, reports, backups and calibration folders. It indexes the
original starter corpus.

## Verify the question bank

```powershell
ielts-coach corpus stats
ielts-coach question list --module reading --limit 5
ielts-coach question draw --module writing --task task2
```

## Start the Agent

Always start from the project root.

Claude Code:

```powershell
claude
```

Then `/ielts`.

Codex: open the repository and use `$ielts`.

OpenCode: open the repository and ask the Agent to load the `ielts` skill.

## Start a structured Session manually

```powershell
ielts-coach session start reading --question-id START-R-003
```

Edit the generated Markdown file. Finish it with:

```powershell
ielts-coach session finish "D:\IELTS_AI\data\sessions\reading\R-YYYYMMDD-001.md"
```

## Review progress

```powershell
ielts-coach summary --days 14
ielts-coach learning-profile
ielts-coach trends
ielts-coach allocation
```
