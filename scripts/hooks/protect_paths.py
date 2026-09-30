"""PreToolUse hook: bloqueia edição de arquivos protegidos (AGENTS.md).

Lê o evento JSON no stdin, extrai o caminho alvo do `edit`/`write` e sai com
código 2 (bloqueio) quando o caminho casa com um padrão protegido. O humano
libera pontualmente exportando `CANTABRIA_ALLOW_PROTECTED=1` na sessão.

Só stdlib: precisa rodar com o `python` do sistema, sem venv.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

PROTECTED = (
    "data/oracle/*",
    "data/oracle/**",
    "data/eval/test.yaml",
    "docs/architecture/definitions.md",
)


def _target(tool_input: dict) -> str | None:

    for key in ("file_path", "path", "filePath", "notebook_path"):
        value = tool_input.get(key)

        if isinstance(value, str) and value:
            return value

    return None


def _relative(path: str) -> str:

    root = Path(os.environ.get("DEVIN_PROJECT_DIR") or Path.cwd()).resolve()
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


def main() -> int:

    if os.environ.get("CANTABRIA_ALLOW_PROTECTED") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    target = _target(event.get("tool_input") or {})

    if target is None:
        return 0

    relative = _relative(target)

    for pattern in PROTECTED:
        if fnmatch.fnmatch(relative, pattern):
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            f"'{relative}' é protegido (gold/definições). Proponha o "
                            "diff ao humano; ele libera com CANTABRIA_ALLOW_PROTECTED=1."
                        ),
                    }
                )
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
