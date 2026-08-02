# Repository instructions

This repository implements the local-first IELTS Study Desk application.

## Product constraints

- Keep the system local-first. The React browser UI and CLI/Skill clients must
  use the same authoritative Python Teaching Runtime.
- Keep the local FastAPI service loopback-only. It serves the application and
  coordinates Runtime work; it is not a second IELTS rules engine or a hosted
  model backend.
- Keep Model Providers, the bounded internal Tutor Agent and optional External
  CLI Agents as separate concepts. External Agents are not teaching providers.
- Do not add cloud hosting, RAG/vector databases, fine-tuning, multi-user
  services or a service database without a separate product decision.
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
- Public builds must start with an empty question bank and contain no learner
  data, private Corpus files, credentials or copyrighted test material.

## Verification

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
```
