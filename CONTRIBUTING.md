# Contributing to aioengiebelgium

Thanks for your interest in contributing. This project is an async Python client
for ENGIE Belgium's reverse-engineered consumer API, targeting Python >= 3.14.

## Setup

Use [uv](https://docs.astral.sh/uv/) (>= 0.12.21, < 0.13) to install the
environment:

```bash
uv sync
```

## Running the checks

Before opening a pull request, run the full gate:

```bash
uv run python -m scripts.check
```

This is the canonical check. It stops at the first failure and runs exactly:

```text
ruff format --check .
ruff check .
mypy src tests scripts
python -m scripts.check_bruno_drift
coverage run -m pytest
coverage report
uv build
uv audit
```

Coverage measures branches in `src/` and requires 98%. `uv audit` needs network
access. Your pull request must pass this gate completely.

## Adding an endpoint

An endpoint change is complete only when all of the following are present:

1. A frozen `Endpoint` row in `src/aioengiebelgium/_endpoints.py` with the
   complete wire contract.
2. A typed `EngieBeClient` getter.
3. A captured real payload under `tests/fixtures/`. Do not guess fixture
   shapes.
4. A Bruno mirror whose request and docs satisfy `scripts.check_bruno_drift`.
5. An entry under `[Unreleased]` in `CHANGELOG.md`.

## Changelog

Every user-visible change needs an entry under `[Unreleased]` in
`CHANGELOG.md`, using the Keep a Changelog categories (`Breaking changes`,
`Added`, `Changed`, `Removed`, `Fixed`, `Security`, `Documentation`,
`Maintenance`). Breaking changes must be listed under a `Breaking changes`
heading.

## Commit style

One conventional-commit subject line, no body. Write the description as a
humanized sentence, for example: `chore: add the EPEX day-ahead endpoint`. Do
not mention the plan or issue number in the subject.

## Deprecation policy

- While the project is on 0.x: breaking changes are allowed in minor releases,
  provided they carry a `Breaking changes` changelog entry.
- From 1.0 onwards: deprecated APIs emit a `DeprecationWarning` for at least
  one minor release before being removed in a major release.

## Pull requests

Every pull request must carry one of the seven repository labels
(`breaking-change`, `new-feature`, `enhancement`, `bugfix`, `maintenance`,
`documentation`, `dependencies`). CI fails otherwise. Dependabot pull requests
are labeled `dependencies` automatically.
