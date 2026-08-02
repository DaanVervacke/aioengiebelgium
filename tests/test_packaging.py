"""Guard the single-source-of-truth invariants in pyproject.toml."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def test_required_version_matches_uv_build_bound() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (uv_build_requirement,) = data["build-system"]["requires"]
    assert uv_build_requirement.startswith("uv_build")
    bound = uv_build_requirement.removeprefix("uv_build")
    assert data["tool"]["uv"]["required-version"] == bound
