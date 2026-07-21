# Repository instructions

This repository implements an agent-native IELTS learning system.

## Product constraints

- Keep the system local-first and CLI/Skill based.
- Do not add a frontend, model API backend, RAG/vector database or fine-tuning
  without a separate product decision.
- Do not bundle copyrighted Cambridge IELTS or commercial course material.
- Preserve the active-learning Writing loop: evidence and score first, learner
  revision second, model alternative last.
- Preserve Reading answer integrity: progressive hints before answer reveal and
  passage-grounded explanation afterward.
- Preserve Speaking mock integrity: no correction during the mock.
- AI scores are estimates with confidence labels, not official examiner scores.
- `skills-source/` is the only editable Skill source. Generate `.claude/skills`,
  `.agents/skills`, and `.opencode/skills` with `ielts-coach sync-skills`.
- Keep database migrations backward-compatible with V0.1 user data.

## Verification

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
```
