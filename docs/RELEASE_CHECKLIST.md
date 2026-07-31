# Release checklist

## Repository boundary

- [ ] No personal SQLite database, Session, attachment, backup or credential is tracked.
- [ ] No PDF, audio or commercial/copyrighted question material is tracked.
- [ ] `python scripts/verify_release.py --source-only` passes.
- [ ] Version numbers and release notes agree.

## Product build

- [ ] Frontend typecheck, lint, unit tests and production build pass.
- [ ] Python fast, migration and full regression suites pass.
- [ ] Wheel and source distribution build successfully.
- [ ] Wheel contains no `starter-corpus` or `original-mocks` files.
- [ ] Windows installer is built from a clean Git checkout.

## Clean-machine acceptance

- [ ] Installer works without system Python, Node, Git, Docker or WSL.
- [ ] Start menu and desktop shortcuts use the product icon.
- [ ] First launch creates an empty question bank.
- [ ] UI binds only to `127.0.0.1` and requires a launch token.
- [ ] ChatGPT login, custom API and no-model paths are tested independently.
- [ ] One Reading import, one Writing task and one persistent dialogue complete.
- [ ] Upgrade preserves the data home.
- [ ] Uninstall preserves user data and removes application binaries.

## Release assets

- [ ] Windows x64 installer.
- [ ] Python wheel and source distribution for technical users.
- [ ] `SHA256SUMS.txt`.
- [ ] Release notes and known limitations.
