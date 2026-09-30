- [ ] `uv run python -m scripts.check` passes completely.
- [ ] The PR carries one of the seven labels: `breaking-change`, `new-feature`, `enhancement`, `bugfix`, `maintenance`, `documentation`, `dependencies`.
- [ ] There is a `[Unreleased]` entry in `CHANGELOG.md`.

For endpoint changes, all of the following are present:

- [ ] A frozen `Endpoint` row in `src/aioengiebelgium/_endpoints.py` with the complete wire contract.
- [ ] A typed `EngieBeClient` getter.
- [ ] A captured real payload under `tests/fixtures/`.
- [ ] A Bruno mirror whose request and docs satisfy `scripts.check_bruno_drift`.
- [ ] An entry under `[Unreleased]` in `CHANGELOG.md`.
