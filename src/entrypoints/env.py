"""Loader mínimo de `.env` para desenvolvimento local.

O runtime de produção recebe o ambiente do hospedeiro (container/systemd);
este helper cobre a conveniência de rodar do host.

Precedência do arquivo: caminho explícito > `DOTENV_PATH` > `.env` no
diretório de trabalho atual, subindo até a raiz > `.env` ao lado do checkout
que contém este arquivo. Variáveis já presentes no ambiente prevalecem.

Regras: linhas `CHAVE=valor`, ignora vazias e comentários (`#`), suporta
aspas simples/duplas removíveis.
"""

from __future__ import annotations

import os
from pathlib import Path

LEGACY_REPO_ROOT = Path(__file__).resolve().parents[2]
DOTENV_ENV = "DOTENV_PATH"


def find_dotenv(start: Path | None = None) -> Path | None:

    origin = Path.cwd() if start is None else start

    for candidate in (origin, *origin.parents):
        path = candidate / ".env"

        if path.is_file():
            return path

    legacy = LEGACY_REPO_ROOT / ".env"

    if legacy.is_file():
        return legacy

    return None


def load_dotenv(path: Path | str | None = None) -> Path | None:

    if path is not None:
        env_path = Path(path).expanduser()
    else:
        override = os.environ.get(DOTENV_ENV)

        if override:
            env_path = Path(override).expanduser()
        else:
            found = find_dotenv()

            if found is None:
                return None

            env_path = found

    if not env_path.is_file():
        return None

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        chave, _, valor = line.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")

        if chave and chave not in os.environ:
            os.environ[chave] = valor

    return env_path
