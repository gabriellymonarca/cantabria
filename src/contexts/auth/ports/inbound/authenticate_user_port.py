from abc import ABC, abstractmethod
from dataclasses import dataclass

from contexts.auth.domain.user import User


@dataclass(frozen=True)
class ExternalIdentity:
    """Identity claims from an external authentication provider."""

    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str | None = None
    hosted_domain: str | None = None
    picture: str | None = None


# Inbound (driving) port published as OHS: the contexts that need the actor
# context (user_interaction, financial_analysis) depend on this interface. The
# adapter depends on the port; the query implements it.
class AuthenticateUserPort(ABC):
    """Authenticates an external identity and returns the actor context."""

    @abstractmethod
    async def execute(self, identity: ExternalIdentity) -> User | None: ...
