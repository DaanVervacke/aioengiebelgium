# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""Local CI gate: run every check tool in order and exit with the first failure's code.

Mirrors the full CI check suite (format -> lint -> type-check -> test -> coverage -> audit).
"""

import subprocess
import sys
from collections.abc import Sequence

COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "ruff", "format", "--check", "."),
    ("uv", "run", "ruff", "check", "."),
    ("uv", "run", "mypy", "src", "tests", "scripts"),
    ("uv", "run", "python", "-m", "scripts.check_bruno_drift"),
    ("uv", "run", "coverage", "run", "-m", "pytest"),
    ("uv", "run", "coverage", "report"),
    ("uv", "run", "pip-audit"),
)


def run_command(command: Sequence[str]) -> int:
    """Run *command* and return its exit code without raising on failure."""
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    """Run all check commands in sequence: stop and propagate the exit code on first failure."""
    for command in COMMANDS:
        return_code = run_command(command)
        if return_code != 0:
            if "ruff" in command:
                print(
                    "\nhint: format/lint failures are usually auto-fixable: "
                    "uv run ruff format . && uv run ruff check . --fix",
                    file=sys.stderr,
                )
            return return_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
