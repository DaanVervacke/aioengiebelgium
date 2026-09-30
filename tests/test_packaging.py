"""Guard the single-source-of-truth invariants in pyproject.toml."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"
CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"


def test_required_version_matches_uv_build_bound() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (uv_build_requirement,) = data["build-system"]["requires"]
    assert uv_build_requirement.startswith("uv_build")
    bound = uv_build_requirement.removeprefix("uv_build")
    assert data["tool"]["uv"]["required-version"] == bound


def test_changelog_has_heading_for_project_version() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    headings = {
        line.removeprefix("## [").split("]", 1)[0]
        for line in CHANGELOG.read_text(encoding="utf-8").splitlines()
        if line.startswith("## [")
    }
    assert version in headings
