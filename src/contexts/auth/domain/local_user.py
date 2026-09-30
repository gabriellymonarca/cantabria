from __future__ import annotations

from dataclasses import dataclass

from contexts.auth.domain.user import Role


@dataclass(frozen=True)
class LocalUser:
    """Credencial local: identidade de demonstração com hash e papéis."""

    username: str
    name: str
    email: str
    password_sha256: str
    roles: tuple[Role, ...]

    def __post_init__(self) -> None:

        object.__setattr__(self, "roles", tuple(self.roles))
