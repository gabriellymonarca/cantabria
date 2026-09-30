from abc import ABC, abstractmethod

from contexts.auth.domain.local_user import LocalUser


class LocalUserStorePort(ABC):
    """Repositório das credenciais locais de demonstração."""

    @abstractmethod
    def find_by_username(self, username: str) -> LocalUser | None: ...
