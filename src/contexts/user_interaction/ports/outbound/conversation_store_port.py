from abc import ABC, abstractmethod

from contexts.user_interaction.domain.conversation import Conversation


# Outbound (driven) port: where conversations live. MongoDB comes with the
# persistence phase; the in-memory adapter serves tests and local development.
class ConversationStorePort(ABC):
    """Persistência do agregado `Conversation` por `session_id`."""

    @abstractmethod
    def load(self, session_id: str) -> Conversation | None: ...

    @abstractmethod
    def save(self, conversation: Conversation) -> None: ...
