from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: str
    name: str
    email: str
    roles: tuple[Role, ...]

    def __post_init__(self) -> None:

        object.__setattr__(self, "roles", tuple(self.roles))


@dataclass(frozen=True)
class Role:
    id: str
    name: str
