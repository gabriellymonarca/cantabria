"""PostToolUse hook: aplica `ruff format` ao arquivo Python recém-editado.

Procura o ruff do `.venv` do projeto (Windows ou Linux); se não houver, sai em
silêncio — formatação é conveniência, não gate (o gate é `git up`/CI).
Só stdlib.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _ruff(root: Path) -> list[str] | None:

    for candidate in (root / ".venv/Scripts/ruff.exe", root / ".venv/bin/ruff"):
        if candidate.exists():
            return [str(candidate)]

    for python in (root / ".venv/Scripts/python.exe", root / ".venv/bin/python"):
        if python.exists():
            return [str(python), "-m", "ruff"]

    return None


def main() -> int:

    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("path")

    if not isinstance(target, str) or not target.endswith(".py"):
        return 0

    root = Path(os.environ.get("DEVIN_PROJECT_DIR") or Path.cwd()).resolve()
    ruff = _ruff(root)

    if ruff is None or not Path(target).exists():
        return 0

    subprocess.run(
        [*ruff, "format", "--quiet", target],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
