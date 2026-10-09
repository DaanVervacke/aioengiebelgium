- [ ] `uv run python -m scripts.check` passes completely.
- [ ] The PR carries one of the seven labels: `breaking-change`, `new-feature`, `enhancement`, `bugfix`, `maintenance`, `documentation`, `dependencies`.
- [ ] Every commit subject follows conventional commits. git-cliff generates `CHANGELOG.md` from them, so do not edit it by hand.

For endpoint changes, all of the following are present:

- [ ] A frozen `Endpoint` row in `src/aioengiebelgium/_endpoints.py` with the complete wire contract.
- [ ] A typed `EngieBeClient` getter.
- [ ] A captured real payload under `tests/fixtures/`.
- [ ] A Bruno mirror whose request and docs satisfy `scripts.check_bruno_drift`.
- [ ] A `feat:` commit subject that names the new getter.
