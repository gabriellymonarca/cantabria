"""Conversation Store em memória: vive enquanto o processo vive."""

from __future__ import annotations

from dataclasses import dataclass, field

from contexts.user_interaction.domain.conversation import Conversation
from contexts.user_interaction.ports.outbound.conversation_store_port import (
    ConversationStorePort,
)


@dataclass
class InMemoryConversationStore(ConversationStorePort):
    """Guarda as conversas por `session_id`."""

    conversations: dict[str, Conversation] = field(default_factory=dict)

    def load(self, session_id: str) -> Conversation | None:

        return self.conversations.get(session_id)

    def save(self, conversation: Conversation) -> None:

        self.conversations[conversation.session_id] = conversation
