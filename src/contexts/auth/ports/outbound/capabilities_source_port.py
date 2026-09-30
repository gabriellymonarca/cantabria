from abc import ABC, abstractmethod

from contexts.auth.domain.capabilities import UserCapabilities


class CapabilitiesSourcePort(ABC):
    """Fonte das capacidades por role (arquivo, diretório, banco...)."""

    @abstractmethod
    def capabilities_for_roles(self, role_ids: list[str]) -> UserCapabilities:
        """Resolve as capacidades dos papéis, na ordem; sem papel, o `default`."""
        ...
