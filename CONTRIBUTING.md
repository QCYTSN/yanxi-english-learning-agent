# Contributing

Thank you for helping improve 言蹊 (Yanxi).

## Before opening a change

- Read [PRODUCT.md](PRODUCT.md) and
  [docs/ARCHITECTURE_V2.md](docs/ARCHITECTURE_V2.md).
- Do not add Cambridge IELTS books, commercial questions, answer keys, learner
  data, credentials or other material you cannot redistribute.
- Edit Skills only under `skills-source/`; generated Agent skill directories
  are not source files.
- Keep model output subordinate to Runtime validation and persistence.

## Local verification

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

Before a release-oriented change, also run:

```powershell
python scripts/verify_release.py --source-only
xiyan evaluation release --cases tests/fixtures/agent_contracts
```

## Pull requests

Keep each pull request focused. Explain the learner impact, data or privacy
impact, validation performed and any migration or compatibility concerns.
