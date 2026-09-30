"""Adapter outbound que lê as credenciais locais de demonstração do Auth.

O núcleo só conhece `LocalUserStorePort`; o I/O e o formato ficam aqui. O
arquivo guarda apenas hashes SHA-256 de senhas de demonstração, nunca
segredos reais — o conteúdo é público e documentado no README.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contexts.auth.domain.local_user import LocalUser
from contexts.auth.domain.user import Role
from contexts.auth.ports.outbound.local_user_store_port import LocalUserStorePort

_USERS_SUBDIR = Path("data") / "auth"
_USERS_FILE = "users.yaml"


class UserStoreConfigurationError(RuntimeError):
    """O arquivo de usuários locais está ausente ou inválido."""


class YamlLocalUserStoreAdapter(LocalUserStorePort):
    """Resolve credenciais locais a partir do arquivo do Auth."""

    def __init__(self, config_path: Path | str | None = None):

        relative = (
            Path(config_path) if config_path else Path(_USERS_SUBDIR, _USERS_FILE)
        )

        # Caminho absoluto vale como está; relativo resolve contra o cwd (é
        # como o container roda, com o pacote em site-packages) e só então
        # contra a raiz do checkout.
        if relative.is_absolute():
            self._path = relative
        elif (Path.cwd() / relative).is_file():
            self._path = Path.cwd() / relative
        else:
            self._path = _project_root() / relative

        self._cache: dict[str, LocalUser] | None = None

    def find_by_username(self, username: str) -> LocalUser | None:

        users = self._load()

        return users.get(username.strip().lower())

    def _load(self) -> dict[str, LocalUser]:

        if self._cache is not None:
            return self._cache

        if not self._path.is_file():
            raise UserStoreConfigurationError(
                f"arquivo de usuários não encontrado: {self._path}."
            )

        raw = yaml.safe_load(self._path.read_text(encoding="utf-8"))

        if not isinstance(raw, dict) or not isinstance(raw.get("users"), list):
            raise UserStoreConfigurationError(
                "o arquivo de usuários precisa de um mapa com a lista `users`."
            )

        users: dict[str, LocalUser] = {}

        for entry in raw["users"]:
            user = _parse_user(entry)
            users[user.username] = user

        self._cache = users

        return users


def _parse_user(entry: Any) -> LocalUser:

    if not isinstance(entry, dict):
        raise UserStoreConfigurationError("cada usuário precisa ser um mapa.")

    username = str(entry.get("username") or "").strip().lower()

    if not username:
        raise UserStoreConfigurationError("cada usuário precisa de `username`.")

    password_sha256 = str(entry.get("password_sha256") or "").strip().lower()

    if len(password_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in password_sha256
    ):
        raise UserStoreConfigurationError(
            f"usuário '{username}' precisa de `password_sha256` hexadecimal de 64 chars."
        )

    roles = [Role(id=str(role), name=str(role)) for role in entry.get("roles") or []]

    return LocalUser(
        username=username,
        name=str(entry.get("name") or username),
        email=str(entry.get("email") or ""),
        password_sha256=password_sha256,
        roles=roles,
    )


def _project_root() -> Path:

    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    raise UserStoreConfigurationError(
        "não encontrei a raiz do projeto (pyproject.toml)."
    )
