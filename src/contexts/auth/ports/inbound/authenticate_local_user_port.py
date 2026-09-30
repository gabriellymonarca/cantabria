from abc import ABC, abstractmethod

from contexts.auth.domain.user import User


class AuthenticateLocalUserPort(ABC):
    """Autentica um usuário local por username e senha."""

    @abstractmethod
    async def execute(self, username: str, password: str) -> User | None: ...
