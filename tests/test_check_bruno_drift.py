"""Tests for the Bruno collection drift check.

``scripts/`` is outside the coverage source, so these are regression guards for
the failure branches rather than coverage contributors: they prove each check
still fires, catching a refactor that silently stops one.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
from scripts import check_bruno_drift as drift

if TYPE_CHECKING:
    from pathlib import Path

_CLIENT_SRC = """
    class EngieBeClient:
        async def close(self) -> None: ...
        async def async_start_authentication(self) -> None: ...
        async def async_get_prices(self, ban: str) -> None: ...
        async def async_get_feature_flag(self, key: str) -> None: ...
        async def _private(self) -> None: ...
"""

_CONST_SRC = """
    from enum import StrEnum

    FOO_BASE_URL = "https://api.example/foo"

    class FeatureFlagKey(StrEnum):
        ALPHA = "alpha-flag"
"""

_PRICES_REQ = """
    info:
      name: Prices
      type: http
    http:
      method: GET
      url: '{{fooBaseUrl}}/prices'
    docs: |
      Mirrors EngieBeClient::async_get_prices.
"""

_FLAG_REQ = """
    info:
      name: Alpha flag
      type: http
    http:
      method: POST
      url: '{{featureFlagsUrl}}'
      body:
        type: json
        data: |-
          {"name": "alpha-flag"}
    docs: |
      Mirrors EngieBeClient::async_get_feature_flag.
"""

_ENV = """
    name: {name}
    variables:
      - name: fooBaseUrl
        value: https://api.example/foo
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal in-sync repo and point the drift module's paths at it."""
    monkeypatch.setattr(drift, "REPO", tmp_path)
    monkeypatch.setattr(drift, "CLIENT_PY", tmp_path / "client.py")
    monkeypatch.setattr(drift, "CONST_PY", tmp_path / "const.py")
    monkeypatch.setattr(drift, "BRUNO", tmp_path / ".bruno")
    monkeypatch.setattr(drift, "ENV_DIR", tmp_path / ".bruno" / "environments")
    _write(tmp_path / "client.py", _CLIENT_SRC)
    _write(tmp_path / "const.py", _CONST_SRC)
    _write(tmp_path / ".bruno" / "prices.yml", _PRICES_REQ)
    _write(tmp_path / ".bruno" / "flag.yml", _FLAG_REQ)
    _write(tmp_path / ".bruno" / "environments" / "Local.yml", _ENV.format(name="Local"))
    _write(tmp_path / ".bruno" / "environments" / "CI.yml", _ENV.format(name="CI"))
    return tmp_path


@pytest.mark.usefixtures("repo")
def test_public_client_methods_excludes_private_and_exempt() -> None:
    assert drift.public_client_methods() == {"async_get_prices", "async_get_feature_flag"}


def test_public_client_methods_missing_class_raises(repo: Path) -> None:
    (repo / "client.py").write_text("class Other: ...\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        drift.public_client_methods()


def test_feature_flag_values_missing_enum_raises(repo: Path) -> None:
    (repo / "const.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        drift.feature_flag_values()


@pytest.mark.usefixtures("repo")
def test_base_urls_reads_http_constants() -> None:
    assert drift.base_urls() == {"FOO_BASE_URL": "https://api.example/foo"}


def test_queried_feature_flags_matches_name_exactly_not_substring() -> None:
    request = {
        "info": {"type": "http"},
        "http": {"body": {"type": "json", "data": '{"name": "alpha-flag-extra"}'}},
    }
    queried = drift.queried_feature_flags([request])
    assert queried == {"alpha-flag-extra"}
    assert "alpha-flag" not in queried


@pytest.mark.usefixtures("repo")
def test_main_in_sync_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert drift.main() == 0
    assert "in sync" in capsys.readouterr().out


def test_main_reports_uncovered_flag(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".bruno" / "flag.yml").unlink()
    assert drift.main() == 1
    assert "alpha-flag" in capsys.readouterr().out


def test_main_reports_unclaimed_method(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".bruno" / "prices.yml").unlink()
    assert drift.main() == 1
    assert "async_get_prices" in capsys.readouterr().out


def test_main_reports_missing_base_url(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo / ".bruno" / "environments" / "CI.yml", "name: CI\nvariables: []\n")
    assert drift.main() == 1
    assert "FOO_BASE_URL" in capsys.readouterr().out


def test_check_requests_flags_query_param_missing_from_url(repo: Path) -> None:
    _write(
        repo / ".bruno" / "bad.yml",
        """
        info:
          name: Bad
          type: http
        http:
          method: GET
          url: 'https://api.example/foo'
          params:
            - name: from
              type: query
        docs: |
          Mirrors EngieBeClient::async_get_prices.
        """,
    )
    problems = drift.check_requests()
    assert any("from" in p and "missing from" in p for p in problems)


def test_check_requests_flags_lowercase_method(repo: Path) -> None:
    _write(
        repo / ".bruno" / "bad.yml",
        """
        info:
          name: Bad
          type: http
        http:
          method: get
          url: 'https://api.example/foo'
        docs: |
          Mirrors EngieBeClient::async_get_prices.
        """,
    )
    problems = drift.check_requests()
    assert any("uppercase" in p for p in problems)
