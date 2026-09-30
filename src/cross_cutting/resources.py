"""Resolução do diretório de dados governados (`data/`).

Precedência: caminho explícito > `CANTABRIA_DATA_DIR` > raiz do checkout.
A raiz do checkout é localizada subindo do diretório de trabalho atual e do
arquivo deste módulo até um marcador (`data/catalogs` ou `pyproject.toml`).
A imagem Docker copia `data/` e fixa `CANTABRIA_DATA_DIR`; instalações sem o
checkout apontam a variável para uma cópia dos dados.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV = "CANTABRIA_DATA_DIR"

_MARKERS = ("data/catalogs", "pyproject.toml")


def find_repo_root(start: Path | None = None) -> Path | None:

    origins = [Path.cwd() if start is None else start, Path(__file__).resolve()]

    for origin in origins:
        for candidate in (origin, *origin.parents):
            if any((candidate / marker).exists() for marker in _MARKERS):
                return candidate

    return None


def default_data_dir() -> Path:

    env = os.environ.get(DATA_DIR_ENV)

    if env:
        return Path(env).expanduser()

    root = find_repo_root()

    if root is not None:
        return root / "data"

    return Path.cwd() / "data"


def resolve_data_dir(explicit: Path | str | None = None) -> Path:

    if explicit is not None:
        return Path(explicit).expanduser()

    return default_data_dir()
