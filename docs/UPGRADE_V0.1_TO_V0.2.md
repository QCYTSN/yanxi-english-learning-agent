# Upgrade from V0.1 to V0.2

Your private `IELTS_HOME` is separate from the source repository. Do not delete
that data directory.

## Recommended Windows upgrade

1. Close Claude Code, Codex and OpenCode.
2. Back up your configured `IELTS_HOME` if it contains real study records.
3. Rename the old source folder to `ielts-ai-coach-v0.1-backup`.
4. Extract the new source folder to a location you control.
5. Activate the existing environment and reinstall the editable project:

```powershell
cd <path-to-ielts-ai-coach>
conda activate ielts-coach
python -m pip install -e .
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
```

`ielts-coach init` does not overwrite user values in profile/settings unless
`--force` is supplied. V0.2.1 merges newly introduced defaults, refreshes only
the project-owned Starter Corpus, runs backward-compatible database migrations,
and indexes the expanded Starter Corpus.

## Verify existing records

```powershell
ielts-coach session list
ielts-coach summary --days 365
ielts-coach corpus stats
```

Expected Starter Corpus count in V0.2: 41 questions, including 16 Reading
questions across 4 original passages.

`ielts-coach doctor` now treats a missing or partial Starter index as a failure.
