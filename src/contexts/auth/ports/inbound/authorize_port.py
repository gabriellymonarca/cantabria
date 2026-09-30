"""Port inbound publicado do Auth (Open Host Service) para autorização.

Reexporta a linguagem publicada — `User`, `Role`, `UserCapabilities` — de que
os contextos consumidores dependem.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from contexts.auth.domain.capabilities import UserCapabilities
from contexts.auth.domain.user import Role, User

__all__ = ["AuthorizePort", "Role", "User", "UserCapabilities"]


class AuthorizePort(ABC):
    """Resolve as capacidades que o usuário autenticado tem para a análise."""

    @abstractmethod
    def capabilities_for(self, user: User) -> UserCapabilities: ...
