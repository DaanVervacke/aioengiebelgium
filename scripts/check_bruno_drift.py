# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""Fail when the Bruno collection has drifted away from the API client."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO = Path(__file__).resolve().parent.parent
CLIENT_PY = REPO / "src" / "aioengiebelgium" / "client.py"
CONST_PY = REPO / "src" / "aioengiebelgium" / "const.py"
BRUNO = REPO / ".bruno"
ENV_DIR = BRUNO / "environments"

CHECKED_ENVIRONMENTS = frozenset({"Local", "CI"})

EXEMPT_METHODS = frozenset({"close", "async_start_authentication"})

CLAIM_RE = re.compile(r"EngieBeClient::(\w+)")


def public_client_methods() -> set[str]:
    """Return the public, non-exempt async method names on ``EngieBeClient``."""
    tree = ast.parse(CLIENT_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "EngieBeClient":
            return {
                item.name
                for item in node.body
                if isinstance(item, ast.AsyncFunctionDef)
                and not item.name.startswith("_")
                and item.name not in EXEMPT_METHODS
            }
    msg = "EngieBeClient not found in client.py"
    raise SystemExit(msg)


def base_urls() -> dict[str, str]:
    """Return the ``{constant: url}`` http(s) base URLs declared in const.py."""
    tree = ast.parse(CONST_PY.read_text(encoding="utf-8"))
    urls: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            continue
        if isinstance(value, str) and value.startswith("http"):
            urls[target.id] = value
    return urls


def feature_flag_values() -> set[str]:
    """Return the string values of the ``FeatureFlagKey`` enum members."""
    tree = ast.parse(CONST_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "FeatureFlagKey"):
            continue
        values: set[str] = set()
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            try:
                value = ast.literal_eval(item.value)
            except ValueError:
                continue
            if isinstance(value, str):
                values.add(value)
        return values
    msg = "FeatureFlagKey not found in const.py"
    raise SystemExit(msg)


def collection_files() -> list[Path]:
    """Every collection file. Both extensions, because Bruno accepts either."""
    return sorted([*BRUNO.rglob("*.yml"), *BRUNO.rglob("*.yaml")])


def load(path: Path) -> tuple[dict[str, object] | None, str | None]:
    """Parse one collection file. Returns ``(mapping, error)``."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        return None, f"is not valid YAML: {err}"
    if not isinstance(doc, dict):
        return None, "does not contain a YAML mapping"
    return doc, None


def is_request(doc: dict[str, object]) -> bool:
    """Report whether this is a request file, not the root, a folder, or an env."""
    info = doc.get("info")
    return isinstance(info, dict) and info.get("type") == "http"


def request_docs(doc: dict[str, object]) -> str:
    """Return a request's ``docs`` text as a string."""
    return str(doc.get("docs") or "")


def queried_feature_flags(requests: Iterable[dict[str, object]]) -> set[str]:
    """Return the flag names requests query, read from each JSON body's ``name``."""
    names: set[str] = set()
    for doc in requests:
        http = doc.get("http")
        if not isinstance(http, dict):
            continue
        body = http.get("body")
        if not isinstance(body, dict):
            continue
        data = body.get("data")
        if not isinstance(data, str):
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
            names.add(parsed["name"])
    return names


def claimed_methods(requests: Iterable[dict[str, object]]) -> set[str]:
    """Return the client methods claimed by an actual request file."""
    claimed: set[str] = set()
    for doc in requests:
        claimed.update(CLAIM_RE.findall(request_docs(doc)))
    return claimed


def env_values() -> dict[Path, set[str]]:
    """Return the declared variable values per checked environment file."""
    out: dict[Path, set[str]] = {}
    for path in sorted([*ENV_DIR.glob("*.yml"), *ENV_DIR.glob("*.yaml")]):
        if path.stem not in CHECKED_ENVIRONMENTS:
            continue
        doc, _err = load(path)
        if doc is None:
            continue
        values: set[str] = set()
        variables = doc.get("variables")
        if isinstance(variables, list):
            for var in variables:
                if isinstance(var, dict) and isinstance(var.get("value"), str):
                    values.add(var["value"])
        out[path] = values
    return out


def _http_problems(rel: Path, http: dict[str, object]) -> list[str]:
    """Validate one request's ``http`` block. Returns a list of problems."""
    problems: list[str] = []

    method = http.get("method")
    if not isinstance(method, str) or method != method.upper():
        problems.append(f"{rel} http.method must be uppercase, got {method!r}.")

    url = http.get("url")
    if not isinstance(url, str) or not url:
        problems.append(f"{rel} has no http.url.")
        return problems

    query_part = url.split("?", 1)[1] if "?" in url else ""
    present = {pair.split("=", 1)[0] for pair in query_part.split("&") if pair}
    params = http.get("params")
    for param in params if isinstance(params, list) else []:
        if not isinstance(param, dict) or param.get("type") != "query" or param.get("disabled"):
            continue
        name = param.get("name")
        if name and name not in present:
            problems.append(
                f"{rel} declares query param {name!r} but it is missing from "
                f"the URL, so Bruno will not send it.",
            )
    return problems


def check_requests() -> list[str]:
    """Structurally validate every request file. Returns a list of problems."""
    problems: list[str] = []
    for path in collection_files():
        rel = path.relative_to(REPO)
        doc, err = load(path)
        if doc is None:
            problems.append(f"{rel} {err}.")
            continue

        info = doc.get("info")
        if isinstance(info, dict) and "type" in info and info.get("type") not in ("http", "folder"):
            problems.append(
                f"{rel} has info.type {info.get('type')!r}, which is neither "
                f"'http' nor 'folder'. A typo here skips validation.",
            )
            continue

        if not is_request(doc):
            continue

        http = doc.get("http")
        if not isinstance(http, dict):
            problems.append(f"{rel} has info.type http but no http block.")
            continue

        problems.extend(_http_problems(rel, http))
    return problems


def main() -> int:
    """Run every check and report. Returns a process exit code."""
    if not BRUNO.is_dir():
        print(f"error: {BRUNO} not found")
        return 1

    requests = [doc for path in collection_files() if (doc := load(path)[0]) and is_request(doc)]

    failures: list[str] = []

    claimed = claimed_methods(requests)
    failures.extend(
        f"EngieBeClient::{method} has no Bruno request. Either add one under "
        f".bruno/ whose docs say 'Mirrors EngieBeClient::{method}', or if it is "
        f"not an endpoint method, add it to EXEMPT_METHODS in this script."
        for method in sorted(public_client_methods() - claimed)
    )

    per_env = env_values()
    if not per_env:
        failures.append(f"no environment files under {ENV_DIR.relative_to(REPO)}.")
    for env_file, values in per_env.items():
        for name, url in sorted(base_urls().items()):
            if url not in values:
                failures.append(
                    f"const.py::{name} is {url}, which is not a variable value "
                    f"in {env_file.relative_to(REPO)}.",
                )

    queried = queried_feature_flags(requests)
    failures.extend(
        f"FeatureFlagKey value {flag!r} is exercised by no Bruno request. Add a "
        f"request under .bruno/07-feature-flags/ that queries it."
        for flag in sorted(feature_flag_values() - queried)
    )

    failures.extend(check_requests())

    if failures:
        print("Bruno collection has drifted from the API client:\n")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\n{len(failures)} problem(s).")
        return 1

    print(
        f"Bruno collection is in sync: {len(public_client_methods())} endpoint "
        f"methods, {len(base_urls())} base URLs and {len(feature_flag_values())} "
        f"feature flags all accounted for.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
